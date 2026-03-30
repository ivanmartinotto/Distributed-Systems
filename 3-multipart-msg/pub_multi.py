import zmq
import time

context = zmq.Context()
socket = context.socket(zmq.PUB)
socket.bind("tcp://*:5555")

topic1 = "Sports"
topic2 = "Entertainment"
data_1 = "Michael Phelps is the GOAT"
data_2 = "Pacific Rim is the best movie ever"

# loop alternating between sending messages for topic1 and topic2
while True:
    socket.send_multipart([topic1.encode(), data_1.encode()])
    print(f"Sent:{topic1}")
    time.sleep(1)
    socket.send_multipart([topic2.encode(), data_2.encode()])
    print(f"Sent:{topic2}")
    time.sleep(1)