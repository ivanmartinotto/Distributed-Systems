import zmq
import cv2 as cv
import numpy as np
import pyaudio
import threading
from queue import Queue

context = zmq.Context()

# video Publisher and Subscriber sockets
video_pub = context.socket(zmq.PUB)
video_pub.connect("tcp://localhost:5555") # Broker XSUB binded address
video_sub = context.socket(zmq.SUB)
video_sub.connect("tcp://localhost:5556") # Broker XPUB binded address
video_sub.setsockopt_string(zmq.SUBSCRIBE, "video")

# audio Publisher and Subscriber sockets
audio_pub = context.socket(zmq.PUB)
audio_pub.connect("tcp://localhost:5557") # Broker XSUB binded address
audio_sub = context.socket(zmq.SUB)
audio_sub.connect("tcp://localhost:5558") # Broker XPUB binded address
audio_sub.setsockopt_string(zmq.SUBSCRIBE, "audio")

# text Publisher and Subscriber sockets
text_pub = context.socket(zmq.PUB)
text_pub.connect("tcp://localhost:5559") # Broker XSUB binded address
text_sub = context.socket(zmq.SUB)
text_sub.connect("tcp://localhost:5560") # Broker XPUB binded address
text_sub.setsockopt_string(zmq.SUBSCRIBE, "text")

# using pyaudio for audio capture
p = pyaudio.PyAudio()

# instantiating queues for video, audio and text
video_render_queue = Queue(200)
audio_render_queue = Queue(100)
text_render_queue = Queue(100)

# topics
topics = ["video", "audio", "text"]

# main thread for rendering video, audio and text
def main_thread():
    stream_out = p.open(format=pyaudio.paInt16, channels=1, rate=16000, output=True)

    while True:
        try:
            frame = video_render_queue.get_nowait()
            cv.imshow("Received Video", frame)
        except:
            pass

        try:
            audio_chunk = audio_render_queue.get_nowait()
            stream_out.write(audio_chunk)
        except:
            pass

        try:
            text_message = text_render_queue.get_nowait()
            print(f"Received Text: {text_message}")
        except:
            pass

        if cv.waitKey(1) & 0xFF == ord('b'):
            break

# receive video and put in queue function
def receive_video():
    while True:
        msg = video_sub.recv_multipart()
        frame = cv.imdecode(np.frombuffer(msg[1], dtype=np.uint8), cv.IMREAD_COLOR)
        video_render_queue.put_nowait(frame)

#receive audio and put in queue function
def receive_audio():
    while True:
        msg = audio_sub.recv_multipart()
        audio_render_queue.put_nowait(msg[1]) # put speaker chunks in queue

# receive text and put in queue function
def receive_text():
    while True:
        msg = text_sub.recv_multipart()
        text_render_queue.put_nowait(msg[1].decode('utf-8')) # put text messages in queue

# send video function
def send_video():
    cap = cv.VideoCapture(0)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        _, buffer = cv.imencode('.jpg', frame)
        video_pub.send_multipart([topics[0].encode('utf-8'), buffer.tobytes()])
        if cv.waitKey(1) & 0xFF == ord('b'):
            break

    cap.release()

# send audio function
def send_audio():
    stream_in = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)

    try:
        while True:
            data = stream_in.read(1024) # read mic chunks
            audio_pub.send_multipart([topics[1].encode('utf-8'), data]) # send message to broker
    except KeyboardInterrupt:
        pass

    stream_in.stop_stream()
    stream_in.close()
    p.terminate()

# send text function
def send_text():
    while True:
        text = input("Enter a message to send (or 'exit' to quit): ")
        if text.lower() == 'exit':
            break
        text_pub.send_multipart([topics[2].encode('utf-8'), text.encode('utf-8')])


# create threads for receiving video, audio and text
video_receive_thread = threading.Thread(target=receive_video)
audio_receive_thread = threading.Thread(target=receive_audio, daemon=True) # set as daemon to allow graceful exit
text_receive_thread = threading.Thread(target=receive_text, daemon=True) # set as daemon to allow graceful exit

#create threads for sending video, audio and text
video_send_thread = threading.Thread(target=send_video) # set as daemon to allow graceful exit
audio_send_thread = threading.Thread(target=send_audio, daemon=True) # set as daemon to allow graceful exit
text_send_thread = threading.Thread(target=send_text, daemon=True) # set as daemon to allow graceful exit

# start threads for receiving and sending video, audio and text
video_receive_thread.start()
audio_receive_thread.start()
video_send_thread.start()
audio_send_thread.start()   
text_send_thread.start()

# start main thread for rendering video, audio and text
main_thread()