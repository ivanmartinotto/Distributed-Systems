import zmq
import time

context = zmq.Context()
socket = context.socket(zmq.PUB)
socket.bind("tcp://*:5555")

while True:
    message = "Hello, World!"
    socket.send_string(message)
    print(f"Sent: {message}")
    time.sleep(1)