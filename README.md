# Distributed Systems with ZeroMQ

A collection of Python examples demonstrating various patterns and concepts in distributed systems using ZeroMQ (ZMQ).

## Prerequisites

- Python 3.x
- pyzmq library: Install with pip install pyzmq
- For video streaming examples (7-video-zmq): pip install opencv-python
- For audio streaming examples (8-audio-zmq): pip install pyaudio

## Examples Overview

This repository contains 9 progressive examples, each building on the previous to demonstrate distributed systems concepts:

1. **ZMQ Basics** (1-zmq-basics/): Introduction to basic ZeroMQ patterns (Pub-Sub, Req-Rep).
2. **Topic Filtering** (2-topic-filter/): Filtering messages based on topics in pub-sub systems.
3. **Multipart Messages** (3-multipart-msg/): Handling messages split into multiple parts.
4. **Proxy Broker** (4-proxy/): Using a message broker for pub-sub communication.
5. **Multi-Proxy** (5-multi-proxy/): Multiple brokers handling different topics (text, audio, video simulation).
6. **Self-Stream Suppression** (6-self-stream-supression/): Subscribers ignore messages from themselves.
7. **Video over ZMQ** (7-video-zmq/): Streaming video frames from webcam using ZMQ.
8. **Audio over ZMQ** (8-audio-zmq/): Streaming audio data using ZMQ.
9. **Meet MVP** (9-meet_MVP/): A meeting system MVP with multiple participants.

## How to Run

Each example folder contains Python scripts and a markdown file with detailed instructions. Generally:

1. Navigate to the desired example folder.
2. Install prerequisites if not already done.
3. Run the broker/server first (if applicable).
4. Run publishers/subscribers in separate terminals.

### Example: Running ZMQ Basics

```bash
cd 1-zmq-basics
python socket_pub.py  # In one terminal
python socket_sub.py  # In another terminal
```

### Example: Running Video Streaming

```bash
cd 7-video-zmq
python video_broker.py  # Start broker
python video_pub.py     # Start publisher (camera)
python video_sub.py     # Start subscriber (viewer)
```

## Architecture Patterns Demonstrated

- **Publish-Subscribe (Pub-Sub)**: One-to-many communication
- **Request-Reply (Req-Rep)**: Synchronous communication
- **Proxy/Broker Patterns**: Message routing and load balancing
- **Multipart Messaging**: Efficient large data transmission
- **Topic Filtering**: Selective message reception
- **Multi-Broker Systems**: Scalable distributed architectures

## Learning Path

Start with 1-zmq-basics and progress through the folders in order. Each example introduces new concepts while building on previous ones.

## Contributing

Feel free to contribute additional examples or improvements to existing ones.