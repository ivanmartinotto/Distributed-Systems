# 8-audio-zmq

This folder demonstrates real-time audio streaming over a network using ZeroMQ (ZMQ) in a publish-subscribe pattern with a message broker.

## What's Implemented

- **Audio Broker** (`audio_broker.py`): A message broker using ZMQ's proxy functionality to route audio data between publishers and subscribers.
- **Audio Publisher** (`audio_pub.py`): Captures audio from a microphone using PyAudio, and publishes the audio chunks as multipart messages with the topic "audio".
- **Audio Subscriber** (`audio_sub.py`): Subscribes to the "audio" topic, receives the multipart messages, and plays back the audio data using PyAudio.
- **Microphone Test** (`mic_test.py`): A simple loopback test script to verify microphone and speaker setup before running the streaming example.

The system uses ZMQ's XPUB/XSUB sockets for the broker, allowing multiple publishers and subscribers to connect seamlessly for audio streaming.

## Architecture

- **Publisher** connects to the broker's XSUB socket (port 5555) and sends audio chunks.
- **Broker** forwards messages from publishers to subscribers using ZMQ proxy.
- **Subscriber** connects to the broker's XPUB socket (port 5556) and receives audio chunks for playback.

## Prerequisites

- Python 3.x
- ZeroMQ library: Install via `pip install pyzmq`
- PyAudio library: Install via `pip install pyaudio`
- A microphone and speakers/headphones for audio input and output

## How to Run

1. Ensure prerequisites are installed.
2. (Optional) Test your audio setup by running the microphone test:
   ```bash
   python mic_test.py
   ```
   This should create a loopback where you hear your microphone input through speakers. Press Ctrl+C to stop.
3. Start the broker in one terminal:
   ```bash
   python audio_broker.py
   ```
4. Start the publisher in another terminal (this will begin capturing from your microphone):
   ```bash
   python audio_pub.py
   ```
5. Start the subscriber in a third terminal (this will play the audio stream):
   ```bash
   python audio_sub.py
   ```

The audio will stream in real-time. Use Ctrl+C in each terminal to stop the processes.

## Notes

- The publisher sends audio chunks continuously until stopped.
- The subscriber plays back received audio chunks in real-time.
- Audio parameters are set to: 16-bit, mono, 16kHz sample rate, 1024 frames per buffer.
- This implementation demonstrates low-latency audio streaming over ZMQ using multipart messages.
- For production use, consider adding error handling, audio compression, echo cancellation, and synchronization features.