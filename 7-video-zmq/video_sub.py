import cv2 as cv
import zmq
import numpy as np

context = zmq.Context()

video = context.socket(zmq.SUB)
video.connect("tcp://localhost:5556") # Broker XPUB binded address
video.setsockopt_string(zmq.SUBSCRIBE, "video")

def receive_video():
    while True:
        msg = video.recv_multipart()
        if msg:        
            frame_array = cv.imdecode(np.frombuffer(msg[1], dtype=np.uint8), cv.IMREAD_COLOR) # decoding: bytes -> np.array -> jpg
            cv.imshow("Video", frame_array)
            msg = None

        # break loop when 'b'key is pressed
        if cv.waitKey(1) == ord('b'):
            break

receive_video()