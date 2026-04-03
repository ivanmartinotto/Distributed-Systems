# 7-video-zmq

This folder demonstrates real-time video streaming over a network using ZeroMQ (ZMQ) in a publish-subscribe pattern with a message broker.

## What's Implemented

- **Video Broker** (`video_broker.py`): A message broker using ZMQ's proxy functionality to route video frames between publishers and subscribers.
- **Video Publisher** (`video_pub.py`): Captures frames from a webcam, encodes them as JPEG images, and publishes them as multipart messages with the topic "video".
- **Video Subscriber** (`video_sub.py`): Subscribes to the "video" topic, receives the multipart messages, decodes the JPEG frames, and displays them in a window using OpenCV.

The system uses ZMQ's XPUB/XSUB sockets for the broker, allowing multiple publishers and subscribers to connect seamlessly.

## Architecture

- **Publisher** connects to the broker's XSUB socket (port 5555) and sends video frames.
- **Broker** forwards messages from publishers to subscribers using ZMQ proxy.
- **Subscriber** connects to the broker's XPUB socket (port 5556) and receives video frames for display.

## Prerequisites

- Python 3.x
- ZeroMQ library: Install via `pip install pyzmq`
- OpenCV library: Install via `pip install opencv-python`
- A webcam or video capture device

## How to Run

1. Ensure prerequisites are installed.
2. Start the broker in one terminal:
   ```bash
   python video_broker.py
   ```
3. Start the publisher in another terminal (this will begin capturing from your webcam):
   ```bash
   python video_pub.py
   ```
4. Start the subscriber in a third terminal (this will display the video stream):
   ```bash
   python video_sub.py
   ```

The video will stream in real-time. Press 'b' in the subscriber window to stop viewing.

## Notes

- The publisher sends frames continuously until stopped.
- The subscriber displays frames in a window and can be stopped by pressing 'b'.
- This implementation demonstrates efficient binary data transmission over ZMQ using multipart messages.
- For production use, consider adding error handling, frame rate control, and compression optimization.

