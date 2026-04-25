import zmq
import cv2 as cv
import numpy as np
import sounddevice as sd
import threading
import sys
from queue import Queue, Full, Empty

member_id = sys.argv[1] if len(sys.argv) > 1 else "1"

context = zmq.Context()

video_pub = context.socket(zmq.PUB)
video_pub.connect("tcp://localhost:5555")
video_sub = context.socket(zmq.SUB)
video_sub.connect("tcp://localhost:5556")
video_sub.setsockopt_string(zmq.SUBSCRIBE, "video")

audio_pub = context.socket(zmq.PUB)
audio_pub.connect("tcp://localhost:5557")
audio_sub = context.socket(zmq.SUB)
audio_sub.connect("tcp://localhost:5558")
audio_sub.setsockopt_string(zmq.SUBSCRIBE, "audio")

text_pub = context.socket(zmq.PUB)
text_pub.connect("tcp://localhost:5559")
text_sub = context.socket(zmq.SUB)
text_sub.connect("tcp://localhost:5560")
text_sub.setsockopt_string(zmq.SUBSCRIBE, "text")

video_render_queue = Queue(200)
audio_render_queue = Queue(100)
text_render_queue = Queue(100)

topics = ["video", "audio", "text"]

def main_thread():
    while True:
        try:
            frame = video_render_queue.get_nowait()
            cv.imshow(f"Member {member_id} - Video", frame)
        except Empty:
            pass
        try:
            chunk = audio_render_queue.get_nowait()
            try:
                sd.play(np.frombuffer(chunk, dtype=np.int16), samplerate=16000)
            except sd.PortAudioError:
                pass
        except Empty:
            pass
        try:
            msg = text_render_queue.get_nowait()
            print(f"[Member {member_id}] Received: {msg}")
        except Empty:
            pass
        if cv.waitKey(1) & 0xFF == ord('b'):
            break

def receive_video():
    while True:
        msg = video_sub.recv_multipart()
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
        video_pub.send_multipart([topics[0].encode(), buffer.tobytes()])
        if cv.waitKey(1) & 0xFF == ord('b'): break
    cap.release()

def send_audio():
    try:
        with sd.RawInputStream(samplerate=16000, channels=1, dtype='int16', blocksize=1024) as stream:
            while True:
                data, _ = stream.read(1024)
                audio_pub.send_multipart([topics[1].encode(), bytes(data)])
    except sd.PortAudioError:
        print(f"[Member {member_id}] No audio device found, skipping audio capture.")

def send_text():
    while True:
        text = input(f"[Member {member_id}] Message (or 'exit'): ")
        if text.lower() == 'exit': break
        text_pub.send_multipart([topics[2].encode(), text.encode()])

threading.Thread(target=receive_video, daemon=True).start()
threading.Thread(target=receive_audio, daemon=True).start()
threading.Thread(target=receive_text, daemon=True).start()
threading.Thread(target=send_video, daemon=True).start()
threading.Thread(target=send_audio, daemon=True).start()
threading.Thread(target=send_text, daemon=True).start()

main_thread()
