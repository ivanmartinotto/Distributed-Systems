import zmq

context = zmq.Context()
socket = context.socket(zmq.SUB)
socket.connect("tcp://localhost:5556") # Connect to the Broker XPUB binded address
socket.setsockopt_string(zmq.SUBSCRIBE, "Sports")  # Subscribe to messages starting with "Sports"

# loop to receive messages
while True:
    message = socket.recv_multipart()
    if message:
        print(f"Topic: {message[0].decode()} / Message: {message[1].decode()}")
        message = None