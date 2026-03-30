import zmq
import time

context = zmq.Context()
socket = context.socket(zmq.PUB)
socket.bind("tcp://*:5555")

topic1 = "topic1"
topic2 = "topic2"

# loop alternating between sending messages for topic1 and topic2
while True:
    socket.send_string(f"{topic1}: data_A")
    print(f"Sent:{topic1}")
    time.sleep(1)
    socket.send_string(f"{topic2}: data_B")
    print(f"Sent:{topic2}")
    time.sleep(1)