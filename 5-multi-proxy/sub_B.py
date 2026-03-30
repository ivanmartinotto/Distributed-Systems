import zmq
import threading

context = zmq.Context()

sub_video = context.socket(zmq.SUB)
sub_video.connect("tcp://localhost:5556") # Broker XPUB binded address
sub_video.setsockopt_string(zmq.SUBSCRIBE, "video:room2") # Subscribe to video:room2

sub_audio = context.socket(zmq.SUB)
sub_audio.connect("tcp://localhost:5558") # Broker XPUB binded address
sub_audio.setsockopt_string(zmq.SUBSCRIBE, "audio:room2") # Subscribe to audio:room2

sub_text = context.socket(zmq.SUB)
sub_text.connect("tcp://localhost:5560") # Broker XPUB binded address
sub_text.setsockopt_string(zmq.SUBSCRIBE, "text:room2") # Subscribe to text:room2

def receive_video():
    while True:
        message = sub_video.recv_multipart()
        if message:
            print(f"Received Video - Topic: {message[0].decode()} / Message: {message[1].decode()}")
            message = None

def receive_audio():
    while True:
        message = sub_audio.recv_multipart()
        if message:
            print(f"Received Audio - Topic: {message[0].decode()} / Message: {message[1].decode()}")
            message = None

def receive_text():
    while True:
        message = sub_text.recv_multipart()
        if message:
            print(f"Received Text - Topic: {message[0].decode()} / Message: {message[1].decode()}")
            message = None

# Start receiving messages in separate threads for non-blocking behavior
threading.Thread(target=receive_video).start()
threading.Thread(target=receive_audio).start()
threading.Thread(target=receive_text).start()

