# Topic Filter

This folder contains an implementation of a topic filter for a distributed systems project. The topic filter is designed to filter messages based on predefined topics in a publish-subscribe system.

## What's Implemented

- A publisher that sends messages repeatedly for the topics "topic1" and "topic2"
- Subscriber A has a topic filter that only receives "topic1" messages.
- Subscriber B has a topic filter that only receives "topic2" messages.

## How to Run It

1. Ensure you have Python 3.x installed.
2. ZeroMQ library: Install via `pip install pyzmq`
3. Clone the repository and navigate to this folder.
4. Run the following files: `python publisher.py`, `python sub_A.py`, `python sub_B.py`
5. Watch the messages sent from the publisher and the filtered messages received by the subscribers.