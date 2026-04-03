# 6-self-stream-supression

This project demonstrates a multi-broker architecture using the ZeroMQ (ZMQ) Python library. It implements a publisher-subscriber model with multiple brokers, each handling a different topic to emulate text, audio, and video streams. On top of that, the subscribers filter the messages sent, ignoring the messages from itself.

## Overview

- **Brokers**: Multiple brokers are set up, each dedicated to a specific topic (e.g., text, audio, video). They facilitate message routing between publishers and subscribers.
- **Publisher**: Sends multipart string messages simulating video, audio, and text data to the appropriate brokers.
- **Subscribers**: Two subscribers are implemented, each subscribing to one distinct topic to receive and process the corresponding messages with are not their own.

## Architecture

The system uses ZMQ's pub-sub pattern with proxies to manage message distribution. Publishers connect to brokers, which forward messages to subscribers based on topics.

## Requirements

- Python 3.x
- ZeroMQ (pyzmq library): Install via `pip install pyzmq`

## Usage

1. Run the brokers (one for each topic).
2. Start the publisher to send messages.
3. Launch the subscribers to receive messages on their respective topics.

## Notes

This implementation emulates real-time media streams using string messages. Ensure ZMQ is properly configured for your network setup.