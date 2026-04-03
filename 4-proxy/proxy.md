
# Proxy Broker System

A message broker implementation using ZMQ (ZeroMQ) for asynchronous publish-subscribe messaging.

## Overview

This project demonstrates a distributed messaging system with:
- **Broker**: Central message hub using ZMQ proxy pattern
- **Publisher**: Sends multipart messages to subscribers
- **Subscribers**: Receive and process published messages

## Components

### Broker
Routes messages between publishers and subscribers using ZMQ's proxy functionality.

### Publisher
Publishes multipart messages to connected subscribers through the broker.

### Subscribers (x2)
Listen for and receive messages from the publisher via the broker.

## Requirements

```bash
pip install zmq
```

## Usage

1. Start the broker
2. Start subscribers
3. Run the publisher to send messages

## ZMQ Pattern

Uses the classic **Pub-Sub** pattern with a broker intermediary for reliable message distribution.
