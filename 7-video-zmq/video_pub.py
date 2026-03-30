import cv2 as cv
import zmq

context = zmq.Context()

video = context.socket(zmq.PUB)
video.connect("tcp://localhost:5555") # Broker XSUB binded address

def video_capture():
    i=1
    topic = "video"
    cap = cv.VideoCapture(0)

    if not cap.isOpened():
        print("Cannot open camera")
        exit()

    while True:
        # capture webcam frames
        ret, frame = cap.read()

        if not ret:
            print("Can't receive frame. Exiting...")
            break

        # encode frame to jpg
        retval, buffer = cv.imencode(".jpg", frame)

        # test imencode return
        if not retval:
            print("Failed compressing the frame")
            break

        video.send_multipart([topic.encode(), buffer.tobytes()])
        print(f"Sent frame {i}")
        i = i+1

video_capture()

