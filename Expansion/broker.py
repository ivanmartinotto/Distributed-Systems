"""
Broker — XSUB/XPUB proxy for video/audio/text/presence + mesh + control REP.

Bind layout (every socket on tcp://* — every interface, so any LAN/VPN client
can reach the broker). Advertises its own RADMIN IP via discovery.

Loop-free mesh:
- Each broker has a dedicated `mesh` PUB port (base+8) that ONLY carries
  messages originated by local clients (filtered by topic origin == my_id).
- Peer brokers SUB to that port. They do not SUB to the regular XPUB anymore.
- When a peer's mesh-injected message arrives, it goes to local clients
  (via XSUB→XPUB) but is NOT re-emitted on our mesh port (origin filter).
- This breaks the infinite reinjection loop that a full N≥3 mesh would have.

Reliable text:
- Per-room circular text history (HISTORY_PER_ROOM) with msg_id dedup.
- Control REP socket (base+9) answers HISTORY queries from clients/peers.
- New peers backfill history on first connection.
"""
import argparse
import json
import threading
import time
from collections import defaultdict, deque

import zmq

from common import (
    DISCOVERY_PORT, HEARTBEAT_INTERVAL,
    CMD_REGISTER, CMD_HEARTBEAT, CMD_UNREGISTER, CMD_LIST,
    CMD_HISTORY, CMD_INFO,
    channel_ports, parse_topic, parse_text_payload,
    detect_radmin_ip,
)

# ----- Per-room text history (delivery guarantee) -----
HISTORY_PER_ROOM = 500
text_history = defaultdict(lambda: deque(maxlen=HISTORY_PER_ROOM))
text_history_lock = threading.Lock()
seen_msg_ids = set()
seen_msg_ids_lock = threading.Lock()
SEEN_IDS_MAX = 50000


def remember_text(room, msg_id, sender, text, ts):
    """Store text in room history. Returns False if duplicate."""
    if not msg_id:
        return False
    with seen_msg_ids_lock:
        if msg_id in seen_msg_ids:
            return False
        seen_msg_ids.add(msg_id)
        if len(seen_msg_ids) > SEEN_IDS_MAX:
            seen_msg_ids.clear()
    with text_history_lock:
        text_history[room].append({
            "msg_id": msg_id, "sender": sender, "text": text, "ts": ts,
        })
    return True


def text_logger_thread(text_xpub_port, stop_event):
    """Subscribes to local text XPUB, persists every message to room history."""
    ctx = zmq.Context.instance()
    sub = ctx.socket(zmq.SUB)
    sub.connect(f"tcp://127.0.0.1:{text_xpub_port}")
    sub.setsockopt_string(zmq.SUBSCRIBE, "text:")
    sub.setsockopt(zmq.RCVHWM, 5000)
    poller = zmq.Poller()
    poller.register(sub, zmq.POLLIN)
    while not stop_event.is_set():
        events = dict(poller.poll(timeout=500))
        if sub not in events:
            continue
        try:
            msg = sub.recv_multipart(flags=zmq.NOBLOCK)
        except zmq.Again:
            continue
        if len(msg) < 2:
            continue
        topic = msg[0].decode("utf-8", errors="ignore")
        parsed = parse_topic(topic)
        if not parsed:
            continue
        _, _, room, sender = parsed
        payload = parse_text_payload(msg[1])
        if not payload:
            continue
        remember_text(
            room=room,
            msg_id=payload.get("msg_id", ""),
            sender=payload.get("sender", sender),
            text=payload.get("text", ""),
            ts=payload.get("ts", time.time()),
        )
    sub.close(linger=0)


def control_thread(control_port, broker_id, stop_event):
    """REP socket: HISTORY (text backfill), INFO (status)."""
    ctx = zmq.Context.instance()
    rep = ctx.socket(zmq.REP)
    rep.bind(f"tcp://*:{control_port}")
    rep.setsockopt(zmq.RCVTIMEO, 500)
    print(f"[broker] control REP on tcp://*:{control_port}")
    while not stop_event.is_set():
        try:
            raw = rep.recv_string()
        except zmq.Again:
            continue
        try:
            req = json.loads(raw)
        except Exception:
            rep.send_string(json.dumps({"ok": False, "error": "invalid json"}))
            continue
        cmd = req.get("cmd")
        if cmd == CMD_HISTORY:
            room = req.get("room")
            already_seen = set(req.get("seen_msg_ids", []))
            with text_history_lock:
                msgs = [
                    dict(m) for m in text_history.get(room, [])
                    if m["msg_id"] not in already_seen
                ]
            rep.send_string(json.dumps({"ok": True, "messages": msgs}))
        elif cmd == CMD_INFO:
            with text_history_lock:
                rooms_info = {r: len(d) for r, d in text_history.items()}
            rep.send_string(json.dumps({
                "ok": True, "id": broker_id, "rooms": rooms_info
            }))
        else:
            rep.send_string(json.dumps({"ok": False, "error": f"unknown cmd: {cmd}"}))
    rep.close(linger=0)


def start_channel(ctx, pub_port, sub_port, name):
    """XSUB/XPUB proxy for one channel. Binds to all interfaces."""
    frontend = ctx.socket(zmq.XSUB)
    frontend.bind(f"tcp://*:{pub_port}")
    backend = ctx.socket(zmq.XPUB)
    backend.bind(f"tcp://*:{sub_port}")

    if name == "video":
        frontend.setsockopt(zmq.RCVHWM, 5)
        backend.setsockopt(zmq.SNDHWM, 5)
    elif name == "audio":
        frontend.setsockopt(zmq.RCVHWM, 20)
        backend.setsockopt(zmq.SNDHWM, 20)
    else:  # text, presence
        frontend.setsockopt(zmq.RCVHWM, 5000)
        backend.setsockopt(zmq.SNDHWM, 5000)

    t = threading.Thread(
        target=zmq.proxy, args=(frontend, backend), daemon=True, name=f"proxy-{name}"
    )
    t.start()
    return t


def mesh_forwarder_thread(my_broker_id, ports, mesh_port, stop_event):
    """Aggregates local-origin messages from all 4 channels into the mesh PUB.
    A message is forwarded only if its topic origin == my_broker_id, so peer
    re-injections never bounce out again. This is the loop break."""
    ctx = zmq.Context.instance()
    mesh_pub = ctx.socket(zmq.PUB)
    mesh_pub.bind(f"tcp://*:{mesh_port}")
    mesh_pub.setsockopt(zmq.SNDHWM, 5000)

    subs = {}
    poller = zmq.Poller()
    for ch in ("video", "audio", "text", "presence"):
        s = ctx.socket(zmq.SUB)
        s.connect(f"tcp://127.0.0.1:{ports[ch][1]}")
        s.setsockopt_string(zmq.SUBSCRIBE, f"{ch}:")
        if ch == "video":
            s.setsockopt(zmq.RCVHWM, 5)
        elif ch == "audio":
            s.setsockopt(zmq.RCVHWM, 20)
        else:
            s.setsockopt(zmq.RCVHWM, 5000)
        subs[ch] = s
        poller.register(s, zmq.POLLIN)

    print(f"[broker] mesh forwarder PUB on tcp://*:{mesh_port}")
    while not stop_event.is_set():
        events = dict(poller.poll(timeout=500))
        for ch, s in subs.items():
            if s in events:
                try:
                    msg = s.recv_multipart(flags=zmq.NOBLOCK)
                except zmq.Again:
                    continue
                if not msg:
                    continue
                topic = msg[0].decode("utf-8", errors="ignore")
                parsed = parse_topic(topic)
                if not parsed:
                    continue
                if parsed[1] != my_broker_id:
                    continue  # only forward locally-originated traffic
                try:
                    mesh_pub.send_multipart(msg, flags=zmq.NOBLOCK)
                except zmq.Again:
                    pass

    for s in subs.values():
        s.close(linger=0)
    mesh_pub.close(linger=0)


def discovery_client(broker_id, host, base_port, discovery_addr, stop_event):
    """Registers the broker in discovery and maintains heartbeat."""
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVTIMEO, 2000)
    sock.connect(discovery_addr)

    def send(req):
        sock.send_string(json.dumps(req))
        return json.loads(sock.recv_string())

    try:
        send({"cmd": CMD_REGISTER, "id": broker_id,
              "host": host, "base_port": base_port})
        print(f"[broker] registered with {discovery_addr} as '{broker_id}' @ {host}:{base_port}")
    except zmq.Again:
        print(f"[broker] WARNING: discovery {discovery_addr} did not respond")

    while not stop_event.wait(HEARTBEAT_INTERVAL):
        try:
            resp = send({"cmd": CMD_HEARTBEAT, "id": broker_id})
            if resp.get("need_register"):
                send({"cmd": CMD_REGISTER, "id": broker_id,
                      "host": host, "base_port": base_port})
                print("[broker] re-registered (discovery had lost the state)")
        except zmq.Again:
            print("[broker] heartbeat timeout — recreating REQ socket")
            sock.close(linger=0)
            sock = ctx.socket(zmq.REQ)
            sock.setsockopt(zmq.LINGER, 0)
            sock.setsockopt(zmq.RCVTIMEO, 2000)
            sock.connect(discovery_addr)

    try:
        send({"cmd": CMD_UNREGISTER, "id": broker_id})
    except Exception:
        pass
    sock.close(linger=0)


def fetch_peer_history(peer_host, peer_control_port, ctx):
    """Pulls all text history from a peer; merges into ours via remember_text."""
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVTIMEO, 1500)
    sock.connect(f"tcp://{peer_host}:{peer_control_port}")
    new_count = 0
    try:
        for room in "ABCDEFGHIJK":
            with seen_msg_ids_lock:
                seen_list = list(seen_msg_ids)[:500]
            sock.send_string(json.dumps({
                "cmd": CMD_HISTORY, "room": room, "seen_msg_ids": seen_list
            }))
            resp = json.loads(sock.recv_string())
            for m in resp.get("messages", []):
                if remember_text(room, m.get("msg_id", ""), m.get("sender", "?"),
                                 m.get("text", ""), m.get("ts", time.time())):
                    new_count += 1
    except (zmq.Again, json.JSONDecodeError):
        pass
    finally:
        sock.close(linger=0)
    if new_count:
        print(f"[mesh] backfilled {new_count} text msgs from peer @ {peer_host}")


def mesh_bridge(my_broker_id, my_base_port, discovery_addr, stop_event):
    """SUBs to peers' mesh PUB port and reinjects messages into our local XSUBs.
    Loop break is enforced upstream by mesh_forwarder_thread (origin filter),
    so this side just has to inject — no risk of re-emit-back."""
    ctx = zmq.Context.instance()
    my_ports = channel_ports(my_base_port)

    # PUBs that inject peer messages into OUR OWN XSUB frontends (via loopback).
    inject = {}
    for ch in ("video", "audio", "text", "presence"):
        s = ctx.socket(zmq.PUB)
        s.connect(f"tcp://127.0.0.1:{my_ports[ch][0]}")
        inject[ch] = s

    # ONE SUB per peer connecting to that peer's mesh PUB port. We use one
    # combined SUB socket per channel and connect it to every peer's mesh port.
    # (PUB→SUB many-to-one fan-in is a normal ZMQ pattern.)
    mesh_in = ctx.socket(zmq.SUB)
    mesh_in.setsockopt_string(zmq.SUBSCRIBE, "")  # accept any topic from mesh
    mesh_in.setsockopt(zmq.RCVHWM, 10000)

    connected_peers = set()

    disc = ctx.socket(zmq.REQ)
    disc.setsockopt(zmq.LINGER, 0)
    disc.setsockopt(zmq.RCVTIMEO, 2000)
    disc.connect(discovery_addr)

    def refresh_peers():
        nonlocal disc
        try:
            disc.send_string(json.dumps({"cmd": CMD_LIST}))
            resp = json.loads(disc.recv_string())
        except zmq.Again:
            disc.close(linger=0)
            disc = ctx.socket(zmq.REQ)
            disc.setsockopt(zmq.LINGER, 0)
            disc.setsockopt(zmq.RCVTIMEO, 2000)
            disc.connect(discovery_addr)
            return

        current = {b["id"]: b for b in resp.get("brokers", []) if b["id"] != my_broker_id}
        for peer_id, b in current.items():
            if peer_id in connected_peers:
                continue
            peer_ports = channel_ports(b["base_port"])
            mesh_in.connect(f"tcp://{b['host']}:{peer_ports['mesh']}")
            connected_peers.add(peer_id)
            print(f"[mesh] connected to peer {peer_id} @ {b['host']}:{b['base_port']}")
            try:
                fetch_peer_history(b["host"], peer_ports["control"], ctx)
            except Exception as e:
                print(f"[mesh] history sync from {peer_id} failed: {e}")

    poller = zmq.Poller()
    poller.register(mesh_in, zmq.POLLIN)

    last_refresh = 0
    REFRESH_INTERVAL = 3.0

    while not stop_event.is_set():
        now = time.time()
        if now - last_refresh > REFRESH_INTERVAL:
            refresh_peers()
            last_refresh = now

        events = dict(poller.poll(timeout=500))
        if mesh_in in events:
            try:
                msg = mesh_in.recv_multipart(flags=zmq.NOBLOCK)
            except zmq.Again:
                continue
            if not msg:
                continue
            topic = msg[0].decode("utf-8", errors="ignore")
            parsed = parse_topic(topic)
            if not parsed:
                continue
            ch, origin_broker, _, _ = parsed
            if origin_broker == my_broker_id:
                continue  # defense (mesh PUB filter should already exclude these)
            if ch not in inject:
                continue
            try:
                inject[ch].send_multipart(msg, flags=zmq.NOBLOCK)
            except zmq.Again:
                pass

    mesh_in.close(linger=0)
    for s in inject.values():
        s.close(linger=0)
    disc.close(linger=0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True, help="Unique broker ID (e.g., B1)")
    parser.add_argument("--base-port", type=int, default=5555,
                        help="base port; uses base..base+9 (10 ports total)")
    parser.add_argument("--discovery", default=None,
                        help="discovery address (default: tcp://<radmin-ip>:5570)")
    parser.add_argument("--host", default=None,
                        help="IP advertised to clients (default: auto-detected RADMIN IP)")
    args = parser.parse_args()

    advertised_ip = args.host or detect_radmin_ip()
    discovery_addr = args.discovery or f"tcp://{advertised_ip}:{DISCOVERY_PORT}"

    ctx = zmq.Context.instance()
    ports = channel_ports(args.base_port)

    start_channel(ctx, ports["video"][0],    ports["video"][1],    "video")
    start_channel(ctx, ports["audio"][0],    ports["audio"][1],    "audio")
    start_channel(ctx, ports["text"][0],     ports["text"][1],     "text")
    start_channel(ctx, ports["presence"][0], ports["presence"][1], "presence")

    stop_event = threading.Event()
    threading.Thread(
        target=discovery_client,
        args=(args.id, advertised_ip, args.base_port, discovery_addr, stop_event),
        daemon=True,
    ).start()
    threading.Thread(
        target=mesh_forwarder_thread,
        args=(args.id, ports, ports["mesh"], stop_event),
        daemon=True,
    ).start()
    threading.Thread(
        target=mesh_bridge,
        args=(args.id, args.base_port, discovery_addr, stop_event),
        daemon=True,
    ).start()
    threading.Thread(
        target=text_logger_thread,
        args=(ports["text"][1], stop_event),
        daemon=True,
    ).start()
    threading.Thread(
        target=control_thread,
        args=(ports["control"], args.id, stop_event),
        daemon=True,
    ).start()

    print(f"[broker] '{args.id}' bound on tcp://* — advertised as {advertised_ip}, "
          f"base_port={args.base_port}")
    print(f"[broker] discovery at {discovery_addr}")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[broker] shutting down...")
        stop_event.set()
        time.sleep(0.3)
        ctx.term()


if __name__ == "__main__":
    main()
