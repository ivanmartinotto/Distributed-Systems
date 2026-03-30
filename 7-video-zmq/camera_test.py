import cv2 as cv

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

    # display frame
    cv.imshow('Live Stream',  frame)

    # break loop when 'b'key is pressed
    if cv.waitKey(1) == ord('b'):
        break

# release capture and close windows
cap.release()
cv.destroyAllWindows()