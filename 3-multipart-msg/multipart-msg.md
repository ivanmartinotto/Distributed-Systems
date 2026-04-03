# 3-multipart-msg

This folder contains an implementation of a distributed system component for handling multipart messages. The project demonstrates how to send, receive, and process messages that are split into multiple parts across a network, ensuring reliability and order in a distributed environment.

## What's Implemented

- **Message Splitting and Reassembly**: Logic to divide large messages into smaller parts for transmission and reassemble them at the receiver end.
- **Distributed Nodes**: Simulation publisher and subscribers nodes communicating over sockets.

## Prerequisites

- Python installed (version 3.X)
- ZMQ Library installed: `pip install pyzmq`

## How to Run

1. Clone the repository and navigate to this folder.
2. Run the following files: `python publisher.py`, `python sub_A.py`, `python sub_B.py`
3. Watch the multipart messages sent from the publisher and the received (and reconstructed) messages from the subscribers.