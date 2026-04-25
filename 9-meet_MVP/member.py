import zmq
import cv2 as cv
import numpy as np
import sounddevice as sd
import threading
import sys
import time
from queue import Queue, Full, Empty

member_id = sys.argv[1] if len(sys.argv) > 1 else "1"
audio_delay = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
muted = False

# print("="*60)
# print(f"[Member {member_id}] Audio devices available:")
# print(sd.query_devices())
# print(f"[Member {member_id}] Default input/output device: {sd.default.device}")
# if output_device is not None:
#     print(f"[Member {member_id}] Forcing output device: {output_device}")
# print("="*60)

context = zmq.Context()

video_pub = context.socket(zmq.PUB)
video_pub.connect("tcp://localhost:5555")
video_sub = context.socket(zmq.SUB)
video_sub.connect("tcp://localhost:5556")
video_sub.setsockopt_string(zmq.SUBSCRIBE, "video:")

audio_pub = context.socket(zmq.PUB)
audio_pub.connect("tcp://localhost:5557")
audio_sub = context.socket(zmq.SUB)
audio_sub.connect("tcp://localhost:5558")
audio_sub.setsockopt_string(zmq.SUBSCRIBE, "audio:")

text_pub = context.socket(zmq.PUB)
text_pub.connect("tcp://localhost:5559")
text_sub = context.socket(zmq.SUB)
text_sub.connect("tcp://localhost:5560")
text_sub.setsockopt_string(zmq.SUBSCRIBE, "text:")

video_render_queue = Queue(200)
audio_render_queue = Queue(100)
text_render_queue = Queue(100)

topics = ["video", "audio", "text"]

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
            print(f"[Member {member_id}] Received: {msg}")
        except Empty:
            pass
        key = cv.waitKey(1) & 0xFF
        if key == ord('b'):
            break
        elif key == ord('m'):
            muted = not muted
            print(f"[Member {member_id}] Muted: {muted}")

def receive_video():
    while True:
        msg = video_sub.recv_multipart()
        sender_id = msg[0].decode().split(":")[-1]
        if sender_id == member_id:
            continue
        frame = cv.imdecode(np.frombuffer(msg[1], dtype=np.uint8), cv.IMREAD_COLOR)
        try:
            video_render_queue.put_nowait(frame)
        except Full:
            try:
                video_render_queue.get_nowait()
            except Empty:
                pass
            video_render_queue.put_nowait(frame)

def receive_audio():
    while True:
        msg = audio_sub.recv_multipart()
        sender_id = msg[0].decode().split(":")[-1]
        if sender_id == member_id:
            continue
        try:
            audio_render_queue.put_nowait(msg[1])
        except Full:
            try:
                audio_render_queue.get_nowait()
            except Empty:
                pass
            audio_render_queue.put_nowait(msg[1])

def receive_text():
    while True:
        msg = text_sub.recv_multipart()
        sender_id = msg[0].decode().split(":")[-1]
        if sender_id == member_id:
            continue
        try:
            text_render_queue.put_nowait(msg[1].decode('utf-8'))
        except Full:
            try:
                text_render_queue.get_nowait()
            except Empty:
                pass
            text_render_queue.put_nowait(msg[1].decode('utf-8'))

def send_video():
    cap = cv.VideoCapture(0)
    while True:
        ret, frame = cap.read()
        if not ret: break
        _, buffer = cv.imencode('.jpg', frame)
        video_pub.send_multipart([f"{topics[0]}:{member_id}".encode(), buffer.tobytes()])
        if cv.waitKey(1) & 0xFF == ord('b'): break
    cap.release()

def send_audio():
    try:
        with sd.RawInputStream(samplerate=16000, channels=1, dtype='int16', blocksize=1024) as stream:
            while True:
                data, _ = stream.read(1024)
                audio_pub.send_multipart([f"{topics[1]}:{member_id}".encode(), bytes(data)])
    except sd.PortAudioError:
        print(f"[Member {member_id}] No audio device found, skipping audio capture.")

def play_audio():
    try:
        with sd.RawOutputStream(samplerate=16000, channels=1, dtype='int16', blocksize=1024) as stream:
            while True:
                try:
                    chunk = audio_render_queue.get(timeout=0.1)
                    if muted:
                        continue
                    if audio_delay > 0:
                        time.sleep(audio_delay)
                    audio_data = np.frombuffer(chunk, dtype=np.int16)
                    stream.write(audio_data)
                except Empty:
                    pass
    except sd.PortAudioError as e:
        print(f"[Member {member_id}] Audio output error: {e}")

def send_text():
    while True:
        text = input(f"[Member {member_id}] Message (or 'exit'): ")
        if text.lower() == 'exit': break
        text_pub.send_multipart([f"{topics[2]}:{member_id}".encode(), text.encode()])

threading.Thread(target=receive_video, daemon=True).start()
threading.Thread(target=receive_audio, daemon=True).start()
threading.Thread(target=receive_text, daemon=True).start()
threading.Thread(target=send_video, daemon=True).start()
threading.Thread(target=send_audio, daemon=True).start()
threading.Thread(target=play_audio, daemon=True).start()
threading.Thread(target=send_text, daemon=True).start()

main_thread()
