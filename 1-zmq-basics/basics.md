# ZMQ Basics

This project provides basic examples of using ZeroMQ (ZMQ) for distributed systems communication.

## What's Implemented

- **Publisher-Subscriber Pattern**: A simple pub-sub example where a publisher sends messages to multiple subscribers.
- Basic socket creation, binding, and connection handling in Python using the `zmq` library.

## Prerequisites

- Python 3.x
- ZeroMQ library: Install via `pip install pyzmq`

## How to Run

1. Clone the repository and navigate to the `1-zmq-basics` directory.
2. Run the publisher example: `python publisher.py` (or `python3 pyblisher.py`)
3. In another terminal, run the subscriber: `python subscriber.py`
4. For request-reply: Run `python server.py` in one terminal, then `python client.py` in another.

Ensure ports are not in use and adjust as needed for your setup.