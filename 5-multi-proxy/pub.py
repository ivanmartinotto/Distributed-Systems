import zmq
import time
import threading

context = zmq.Context()

video = context.socket(zmq.PUB)
video.connect("tcp://localhost:5555") # Broker XSUB binded address

audio = context.socket(zmq.PUB)
audio.connect("tcp://localhost:5557") # Broker XSUB binded address

text = context.socket(zmq.PUB)
text.connect("tcp://localhost:5559") # Broker XSUB binded address
    
v_topics = ["video:room1:userA", "video:room1:userB", "video:room2:userA", "video:room2:userB"]
a_topics = ["audio:room1:userA", "audio:room1:userB", "audio:room2:userA", "audio:room2:userB"]
t_topics = ["text:room1:userA", "text:room1:userB", "text:room2:userA", "text:room2:userB"]

def publish_video():
    while True:
        for topic in v_topics:
            video.send_multipart([topic.encode(), b"Video data"])
            print(f"Sent: {topic}")
            time.sleep(0.1)

def publish_audio():
    while True:
        for topic in a_topics:
            audio.send_multipart([topic.encode(), b"Audio data"])
            print(f"Sent: {topic}")
            time.sleep(0.1)

def publish_text():
    while True:
        for topic in t_topics:
            text.send_multipart([topic.encode(), b"Text data"])
            print(f"Sent: {topic}")
            time.sleep(2)

# start publishing in separate threads for non-blocking behavior
threading.Thread(target=publish_video).start()
threading.Thread(target=publish_audio).start()
threading.Thread(target=publish_text).start()
