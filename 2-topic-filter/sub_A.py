import zmq

context = zmq.Context()
socket = context.socket(zmq.SUB)
socket.connect("tcp://localhost:5555")
socket.setsockopt_string(zmq.SUBSCRIBE, "topic1")  # Subscribe to messages starting with "topic1"

# loop to receive messages
while(1):
    message = socket.recv_string()
    if message:
        print(f"Received: {message}")
        message = None