"""
Member (client) — captures/renders video/audio/text, connects to a broker
via discovery, fails over automatically, supports rooms.

Reliable text features:
- Each text msg has a unique msg_id ("{sender}-{seq}").
- Sender keeps a pending queue; broker echoes the message back via XPUB
  and that echo serves as the ACK.
- Background retry loop re-publishes un-ACKed msgs (up to N times).
- On broker swap, all pending msgs are re-published.
- On room switch (or after failover), client fetches text history from
  the broker's control REP socket to backfill anything missed.
- Receivers dedup by msg_id.
"""
import argparse
import json
import os
import random
import sys
import threading
import time
import uuid
from collections import deque
from queue import Queue, Full, Empty

import cv2 as cv
import numpy as np
import sounddevice as sd
import zmq

from common import (
    ROOMS, PRESENCE_INTERVAL, DISCOVERY_PORT,
    CMD_LIST, CMD_HISTORY,
    channel_ports, parse_topic, make_topic,
    make_text_payload, parse_text_payload,
    detect_radmin_ip,
)

parser = argparse.ArgumentParser()
parser.add_argument("--id", default=uuid.uuid4().hex[:6])
parser.add_argument("--room", default="A", choices=ROOMS)
parser.add_argument("--discovery", default=None,
                    help="discovery addr (default: tcp://<radmin-ip>:5570)")
parser.add_argument("--no-video", action="store_true", help="disable video capture")
parser.add_argument("--no-audio", action="store_true", help="disable audio capture")
args = parser.parse_args()

member_id = args.id
my_room = args.room
discovery_addr = args.discovery or f"tcp://{detect_radmin_ip()}:{DISCOVERY_PORT}"

print(f"[client] id={member_id} room={my_room} discovery={discovery_addr}")

online_members = set()
online_lock = threading.Lock()

muted = False
stop_event = threading.Event()

# ---- Reliable text state ----
my_text_seq = 0
my_text_seq_lock = threading.Lock()

# pending_text: msg_id -> {text, room, retries, last_send_ts, ts}
pending_text = {}
pending_text_lock = threading.Lock()
TEXT_RETRY_INTERVAL = 2.0
TEXT_MAX_RETRIES = 5

# Receiver dedup: msg_ids we've already shown
seen_text_msg_ids = set()
seen_text_lock = threading.Lock()
SEEN_TEXT_MAX = 10000


def fetch_broker(discovery_addr, ctx):
    """Asks discovery which brokers are alive and picks one at random."""
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVTIMEO, 3000)
    sock.connect(discovery_addr)
    try:
        sock.send_string(json.dumps({"cmd": CMD_LIST}))
        resp = json.loads(sock.recv_string())
    except zmq.Again:
        raise RuntimeError(f"discovery {discovery_addr} did not respond")
    finally:
        sock.close(linger=0)

    brokers = resp.get("brokers", [])
    if not brokers:
        raise RuntimeError("no broker available in discovery")
    chosen = random.choice(brokers)
    print(f"[client] discovery returned {len(brokers)} broker(s); "
          f"chosen: {chosen['id']} @ {chosen['host']}:{chosen['base_port']}")
    return chosen


class Conn:
    """Thread-safe holder of current ZMQ sockets. Recreates context on swap."""

    def __init__(self, ctx, member_id, room):
        self.ctx = ctx
        self.member_id = member_id
        self.room = room
        self.broker_id = None
        self.host = None
        self.control_port = None
        self._lock = threading.Lock()
        self.video_pub = self.video_sub = None
        self.audio_pub = self.audio_sub = None
        self.text_pub  = self.text_sub  = None
        self.presence_pub = self.presence_sub = None

    def _build_with_ctx(self, ctx, broker):
        host = broker["host"]
        ports = channel_ports(broker["base_port"])

        v_pub = ctx.socket(zmq.PUB); v_pub.connect(f"tcp://{host}:{ports['video'][0]}")
        v_sub = ctx.socket(zmq.SUB); v_sub.connect(f"tcp://{host}:{ports['video'][1]}")
        v_sub.setsockopt_string(zmq.SUBSCRIBE, "video:")
        v_sub.setsockopt(zmq.RCVHWM, 30)

        a_pub = ctx.socket(zmq.PUB); a_pub.connect(f"tcp://{host}:{ports['audio'][0]}")
        a_sub = ctx.socket(zmq.SUB); a_sub.connect(f"tcp://{host}:{ports['audio'][1]}")
        a_sub.setsockopt_string(zmq.SUBSCRIBE, "audio:")
        a_sub.setsockopt(zmq.RCVHWM, 50)

        t_pub = ctx.socket(zmq.PUB); t_pub.connect(f"tcp://{host}:{ports['text'][0]}")
        t_sub = ctx.socket(zmq.SUB); t_sub.connect(f"tcp://{host}:{ports['text'][1]}")
        t_sub.setsockopt_string(zmq.SUBSCRIBE, "text:")
        t_sub.setsockopt(zmq.RCVHWM, 5000)

        p_pub = ctx.socket(zmq.PUB); p_pub.connect(f"tcp://{host}:{ports['presence'][0]}")
        p_sub = ctx.socket(zmq.SUB); p_sub.connect(f"tcp://{host}:{ports['presence'][1]}")
        p_sub.setsockopt_string(zmq.SUBSCRIBE, "presence:")
        p_sub.setsockopt(zmq.RCVHWM, 5000)

        # Generous wait for subscriptions to propagate to the broker.
        time.sleep(0.5)
        return (v_pub, v_sub, a_pub, a_sub, t_pub, t_sub,
                p_pub, p_sub, host, broker["id"], ports["control"])

    def swap(self, broker):
        """Atomic switch to a new broker. Recreates the entire ZMQ context."""
        is_first_swap = (self.broker_id is None)
        if is_first_swap:
            new_ctx = self.ctx
            old_ctx_to_term = None
        else:
            new_ctx = zmq.Context()
            old_ctx_to_term = self.ctx

        new = self._build_with_ctx(new_ctx, broker)

        with self._lock:
            old_sockets = (self.video_pub, self.video_sub,
                           self.audio_pub, self.audio_sub,
                           self.text_pub,  self.text_sub,
                           self.presence_pub, self.presence_sub)
            self.ctx = new_ctx
            (self.video_pub, self.video_sub,
             self.audio_pub, self.audio_sub,
             self.text_pub,  self.text_sub,
             self.presence_pub, self.presence_sub,
             self.host, self.broker_id, self.control_port) = new

        for s in old_sockets:
            if s is not None:
                try: s.close(linger=0)
                except Exception: pass

        if old_ctx_to_term is not None:
            try:
                old_ctx_to_term.destroy(linger=0)
            except Exception:
                pass

        msg = f"[client] connected to {self.broker_id} @ {self.host} (room {self.room})"
        if not is_first_swap:
            msg += " — context recreated"
        print(msg)

        with online_lock:
            online_members.clear()

        time.sleep(0.3)

        # Re-publish any un-ACKed text (delivery guarantee across failover).
        resend_pending_text()

        # Fetch text history for current room (recover anything missed).
        fetch_history_for_room(self.host, self.control_port, self.room)

        # Announce presence + ask everyone else to identify.
        join_topic = make_topic("presence", self.broker_id, self.room, self.member_id).encode()
        for _ in range(3):
            try:
                self.presence_pub.send_multipart([join_topic, b"JOIN"])
                self.presence_pub.send_multipart([join_topic, b"WHOIS"])
                time.sleep(0.15)
            except Exception:
                pass


def fetch_history_for_room(host, control_port, room):
    """Pulls text history from the broker's control REP and enqueues new msgs."""
    if host is None or control_port is None:
        return
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVTIMEO, 1500)
    try:
        sock.connect(f"tcp://{host}:{control_port}")
        with seen_text_lock:
            seen_list = list(seen_text_msg_ids)[:500]
        sock.send_string(json.dumps({
            "cmd": CMD_HISTORY, "room": room, "seen_msg_ids": seen_list
        }))
        resp = json.loads(sock.recv_string())
        new_count = 0
        for m in resp.get("messages", []):
            mid = m.get("msg_id", "")
            with seen_text_lock:
                if mid in seen_text_msg_ids:
                    continue
                seen_text_msg_ids.add(mid)
                if len(seen_text_msg_ids) > SEEN_TEXT_MAX:
                    seen_text_msg_ids.clear()
            sender = m.get("sender", "?")
            text = m.get("text", "")
            if sender == member_id:
                # Our own past msg coming back as history → just ACK it.
                with pending_text_lock:
                    pending_text.pop(mid, None)
                continue
            try:
                text_render_queue.put_nowait(f"{sender}:{text}")
                new_count += 1
            except Full:
                pass
        if new_count:
            print(f"[client] backfilled {new_count} historic text msg(s) for room {room}")
    except (zmq.Again, json.JSONDecodeError):
        print("[client] history fetch failed (broker may be busy)")
    finally:
        sock.close(linger=0)


def resend_pending_text():
    """Re-publish all un-ACKed text on the current connection."""
    with pending_text_lock:
        items = list(pending_text.items())
    if not items:
        return
    print(f"[client] re-sending {len(items)} pending text msg(s)")
    for msg_id, info in items:
        try:
            topic = make_topic("text", conn.broker_id, info["room"], member_id).encode()
            payload = make_text_payload(msg_id, member_id, info["text"], info["ts"])
            conn.text_pub.send_multipart([topic, payload], flags=zmq.NOBLOCK)
        except Exception:
            pass


def text_retry_loop():
    """Background: every TEXT_RETRY_INTERVAL/2 sec, retry pending msgs."""
    while not stop_event.is_set():
        time.sleep(TEXT_RETRY_INTERVAL / 2)
        now = time.time()
        to_retry, dropped = [], []
        with pending_text_lock:
            for mid, info in list(pending_text.items()):
                if now - info["last_send_ts"] < TEXT_RETRY_INTERVAL:
                    continue
                if info["retries"] >= TEXT_MAX_RETRIES:
                    dropped.append(mid)
                else:
                    info["retries"] += 1
                    info["last_send_ts"] = now
                    to_retry.append((mid, dict(info)))
            for mid in dropped:
                pending_text.pop(mid, None)
        for mid in dropped:
            print(f"[client] WARNING: gave up on msg {mid} after {TEXT_MAX_RETRIES} retries")
        for mid, info in to_retry:
            try:
                topic = make_topic("text", conn.broker_id, info["room"], member_id).encode()
                payload = make_text_payload(mid, member_id, info["text"], info["ts"])
                conn.text_pub.send_multipart([topic, payload], flags=zmq.NOBLOCK)
            except Exception:
                pass


def drain_pending_for_room(room, timeout=1.0):
    """Wait up to `timeout` for all pending text addressed to `room` to ACK.
    Used before leaving a room so messages aren't orphaned."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with pending_text_lock:
            still = [mid for mid, info in pending_text.items() if info["room"] == room]
        if not still:
            return True
        time.sleep(0.05)
    with pending_text_lock:
        leftover = [mid for mid, info in pending_text.items() if info["room"] == room]
    if leftover:
        print(f"[client] WARNING: {len(leftover)} text msg(s) still pending in room {room}; "
              f"will keep retrying in background")
    return not leftover


# ----- Connection bootstrap -----
# Queues must exist before swap() because swap triggers history fetch
# which enqueues into text_render_queue.
video_render_queue = Queue(200)
audio_render_queue = Queue(100)
text_render_queue = Queue(500)

watchdog_ctx = zmq.Context()
member_ctx = zmq.Context()

conn = Conn(member_ctx, member_id, my_room)
broker = fetch_broker(discovery_addr, watchdog_ctx)
conn.swap(broker)


def watchdog(conn, discovery_addr, stop_event):
    """Every 2s, asks discovery if our broker is alive. If not, swap."""
    sock = watchdog_ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVTIMEO, 2000)
    sock.connect(discovery_addr)

    def list_brokers():
        nonlocal sock
        try:
            sock.send_string(json.dumps({"cmd": CMD_LIST}))
            return json.loads(sock.recv_string()).get("brokers", [])
        except zmq.Again:
            sock.close(linger=0)
            sock = watchdog_ctx.socket(zmq.REQ)
            sock.setsockopt(zmq.LINGER, 0)
            sock.setsockopt(zmq.RCVTIMEO, 2000)
            sock.connect(discovery_addr)
            return None

    while not stop_event.wait(2.0):
        brokers = list_brokers()
        if brokers is None:
            continue
        alive_ids = {b["id"] for b in brokers}
        if conn.broker_id in alive_ids:
            continue
        if not brokers:
            print("[watchdog] no broker alive, waiting...")
            continue
        new_broker = random.choice(brokers)
        print(f"[watchdog] broker '{conn.broker_id}' down — migrating to '{new_broker['id']}'")
        try:
            conn.swap(new_broker)
        except Exception as e:
            print(f"[watchdog] migration failed: {e}")


def main_thread():
    global muted
    while True:
        try:
            frame = video_render_queue.get_nowait()
            cv.imshow(f"Member {member_id} - Video", frame)
        except Empty:
            pass
        try:
            msg = text_render_queue.get_nowait()
            sender, content = msg.split(":", 1)
            print(f"[Member {sender}] Sent: {content}")
        except Empty:
            pass
        key = cv.waitKey(1) & 0xFF
        if key == ord('b'):
            break
        elif key == ord('m'):
            muted = not muted
            print(f"[Member {member_id}] Muted: {muted}")


def receive_video():
    while not stop_event.is_set():
        try:
            msg = conn.video_sub.recv_multipart()
        except zmq.ZMQError:
            time.sleep(0.1)
            continue
        if len(msg) < 2:
            continue
        topic = msg[0].decode('utf-8', errors='ignore')
        parsed = parse_topic(topic)
        if not parsed:
            continue
        _, _, room, sender_id = parsed
        if room != conn.room or sender_id == member_id:
            continue
        frame = cv.imdecode(np.frombuffer(msg[1], dtype=np.uint8), cv.IMREAD_COLOR)
        if frame is None:
            continue
        try:
            video_render_queue.put_nowait(frame)
        except Full:
            try: video_render_queue.get_nowait()
            except Empty: pass
            video_render_queue.put_nowait(frame)


def receive_audio():
    while not stop_event.is_set():
        try:
            msg = conn.audio_sub.recv_multipart()
        except zmq.ZMQError:
            time.sleep(0.1)
            continue
        if len(msg) < 2:
            continue
        topic = msg[0].decode('utf-8', errors='ignore')
        parsed = parse_topic(topic)
        if not parsed:
            continue
        _, _, room, sender_id = parsed
        if room != conn.room or sender_id == member_id:
            continue
        try:
            audio_render_queue.put_nowait(msg[1])
        except Full:
            try: audio_render_queue.get_nowait()
            except Empty: pass
            audio_render_queue.put_nowait(msg[1])


def receive_text():
    """Receives text. Uses echo-of-own-msg as ACK. Dedups by msg_id."""
    while not stop_event.is_set():
        try:
            msg = conn.text_sub.recv_multipart()
        except zmq.ZMQError:
            time.sleep(0.1)
            continue
        if len(msg) < 2:
            continue
        topic = msg[0].decode('utf-8', errors='ignore')
        parsed = parse_topic(topic)
        if not parsed:
            continue
        _, _, room, sender_id = parsed
        payload = parse_text_payload(msg[1])
        if not payload:
            continue
        msg_id = payload.get("msg_id", "")
        text = payload.get("text", "")

        # ACK our own message regardless of room (it traveled successfully).
        if sender_id == member_id:
            with pending_text_lock:
                pending_text.pop(msg_id, None)
            continue

        # Filter by current room.
        if room != conn.room:
            continue

        # Dedup at receiver.
        with seen_text_lock:
            if msg_id in seen_text_msg_ids:
                continue
            seen_text_msg_ids.add(msg_id)
            if len(seen_text_msg_ids) > SEEN_TEXT_MAX:
                seen_text_msg_ids.clear()

        try:
            text_render_queue.put_nowait(f"{sender_id}:{text}")
        except Full:
            try: text_render_queue.get_nowait()
            except Empty: pass
            text_render_queue.put_nowait(f"{sender_id}:{text}")


def send_video():
    if args.no_video:
        return
    cap = cv.VideoCapture(0)
    if not cap.isOpened():
        print(f"[Member {member_id}] No camera available, skipping video capture.")
        return
    cap.set(cv.CAP_PROP_FRAME_WIDTH, 480)
    cap.set(cv.CAP_PROP_FRAME_HEIGHT, 360)
    target_fps = 12
    frame_interval = 1.0 / target_fps
    encode_params = [int(cv.IMWRITE_JPEG_QUALITY), 55]
    while not stop_event.is_set():
        loop_start = time.time()
        ret, frame = cap.read()
        if not ret:
            break
        ok, buffer = cv.imencode('.jpg', frame, encode_params)
        if not ok:
            continue
        topic = make_topic("video", conn.broker_id, conn.room, member_id).encode()
        try:
            conn.video_pub.send_multipart([topic, buffer.tobytes()], flags=zmq.NOBLOCK)
        except zmq.Again:
            pass
        elapsed = time.time() - loop_start
        sleep_for = frame_interval - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)
    cap.release()


def send_audio():
    if args.no_audio:
        return
    try:
        with sd.RawInputStream(samplerate=16000, channels=1, dtype='int16', blocksize=1024) as stream:
            while not stop_event.is_set():
                data, _ = stream.read(1024)
                topic = make_topic("audio", conn.broker_id, conn.room, member_id).encode()
                try:
                    conn.audio_pub.send_multipart([topic, bytes(data)], flags=zmq.NOBLOCK)
                except zmq.Again:
                    pass
    except sd.PortAudioError:
        print(f"[Member {member_id}] No audio device found, skipping audio capture.")


def play_audio():
    if args.no_audio:
        return
    try:
        with sd.RawOutputStream(samplerate=16000, channels=1, dtype='int16', blocksize=1024) as stream:
            while not stop_event.is_set():
                try:
                    chunk = audio_render_queue.get(timeout=0.1)
                    if muted:
                        continue
                    audio_data = np.frombuffer(chunk, dtype=np.int16)
                    stream.write(audio_data)
                except Empty:
                    pass
    except sd.PortAudioError as e:
        print(f"[Member {member_id}] Audio output error: {e}")


def next_text_msg_id():
    global my_text_seq
    with my_text_seq_lock:
        my_text_seq += 1
        return f"{member_id}-{my_text_seq}"


def publish_text(text):
    """Builds, registers in pending, and publishes a text message."""
    msg_id = next_text_msg_id()
    ts = time.time()
    info = {
        "text": text, "room": conn.room,
        "retries": 0, "last_send_ts": ts, "ts": ts,
    }
    with pending_text_lock:
        pending_text[msg_id] = info
    topic = make_topic("text", conn.broker_id, conn.room, member_id).encode()
    payload = make_text_payload(msg_id, member_id, text, ts)
    try:
        conn.text_pub.send_multipart([topic, payload], flags=zmq.NOBLOCK)
    except (zmq.Again, zmq.ZMQError) as e:
        print(f"[client] text send failed (will retry): {e}")
    return msg_id


def send_text():
    while not stop_event.is_set():
        try:
            text = input(f"[{member_id}@{conn.room}] > ")
        except EOFError:
            break
        if text == "":
            continue
        if text.lower() == 'exit':
            try:
                topic = make_topic("presence", conn.broker_id, conn.room, member_id).encode()
                conn.presence_pub.send_multipart([topic, b"LEAVE"])
                time.sleep(0.2)
            except Exception:
                pass
            os._exit(0)
        if text == '/who':
            with online_lock:
                others = sorted(online_members)
            print(f"[room {conn.room}] online: {[member_id] + others}")
            continue
        if text.startswith('/room '):
            parts = text.split()
            if len(parts) < 2:
                print("usage: /room <A-K>")
                continue
            new_room = parts[1].upper()
            if new_room not in ROOMS:
                print(f"invalid room. valid: {ROOMS}")
                continue
            old_room = conn.room

            # Drain pending text for old room before switching (delivery guarantee).
            print(f"[client] draining pending text for room {old_room}...")
            drain_pending_for_room(old_room, timeout=1.0)

            # LEAVE old room.
            old_topic = make_topic("presence", conn.broker_id, old_room, member_id).encode()
            try:
                conn.presence_pub.send_multipart([old_topic, b"LEAVE"])
            except Exception:
                pass

            with online_lock:
                online_members.clear()
            conn.room = new_room
            print(f"[client] moved to room {new_room}")

            # Fetch history for the new room.
            fetch_history_for_room(conn.host, conn.control_port, new_room)

            # Re-announce presence in new room.
            new_topic = make_topic("presence", conn.broker_id, new_room, member_id).encode()
            for _ in range(3):
                try:
                    conn.presence_pub.send_multipart([new_topic, b"JOIN"])
                    conn.presence_pub.send_multipart([new_topic, b"WHOIS"])
                    time.sleep(0.15)
                except Exception:
                    pass
            continue

        publish_text(text)


def announce_presence():
    """Periodic JOIN re-announcement so latecomers learn we exist."""
    while not stop_event.is_set():
        topic = make_topic("presence", conn.broker_id, conn.room, member_id).encode()
        try:
            conn.presence_pub.send_multipart([topic, b"JOIN"], flags=zmq.NOBLOCK)
        except (zmq.Again, zmq.ZMQError):
            pass
        time.sleep(PRESENCE_INTERVAL)


def receive_presence():
    last_seen = {}
    while not stop_event.is_set():
        try:
            msg = conn.presence_sub.recv_multipart()
        except zmq.ZMQError:
            time.sleep(0.1)
            continue
        if len(msg) < 2:
            continue
        topic = msg[0].decode()
        parsed = parse_topic(topic)
        if not parsed:
            continue
        _, _, room, sender_id = parsed
        if room != conn.room or sender_id == member_id:
            continue
        action = msg[1].decode(errors='ignore')

        with online_lock:
            now = time.time()
            if action == "JOIN":
                if sender_id not in online_members:
                    online_members.add(sender_id)
                    print(f"[room {conn.room}] {sender_id} joined")
                last_seen[sender_id] = now
            elif action == "LEAVE":
                if sender_id in online_members:
                    online_members.discard(sender_id)
                    last_seen.pop(sender_id, None)
                    print(f"[room {conn.room}] {sender_id} left")
            elif action == "WHOIS":
                reply = make_topic("presence", conn.broker_id, conn.room, member_id).encode()
                try:
                    conn.presence_pub.send_multipart([reply, b"JOIN"])
                except Exception:
                    pass

            timeout = PRESENCE_INTERVAL * 4
            stale = [u for u, t in last_seen.items() if now - t > timeout]
            for u in stale:
                online_members.discard(u)
                last_seen.pop(u, None)
                print(f"[room {conn.room}] {u} left (timeout)")


# ----- Spawn worker threads -----
threading.Thread(target=receive_video,    daemon=True).start()
threading.Thread(target=receive_audio,    daemon=True).start()
threading.Thread(target=receive_text,     daemon=True).start()
threading.Thread(target=send_video,       daemon=True).start()
threading.Thread(target=send_audio,       daemon=True).start()
threading.Thread(target=play_audio,       daemon=True).start()
threading.Thread(target=send_text,        daemon=True).start()
threading.Thread(target=announce_presence, daemon=True).start()
threading.Thread(target=receive_presence, daemon=True).start()
threading.Thread(target=text_retry_loop,  daemon=True).start()
threading.Thread(target=watchdog,         args=(conn, discovery_addr, stop_event), daemon=True).start()

main_thread()
