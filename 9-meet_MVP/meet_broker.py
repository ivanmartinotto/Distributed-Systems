import zmq
import threading
import time

context = zmq.Context()

# channel 1 - video
xsub, xpub = context.socket(zmq.XSUB), context.socket(zmq.XPUB)
xsub.bind("tcp://*:5555")
xpub.bind("tcp://*:5556")

# channel 2 - audio
xsub2, xpub2 = context.socket(zmq.XSUB), context.socket(zmq.XPUB)
xsub2.bind("tcp://*:5557")
xpub2.bind("tcp://*:5558")

# channel 3 - text
xsub3, xpub3 = context.socket(zmq.XSUB), context.socket(zmq.XPUB)
xsub3.bind("tcp://*:5559")
xpub3.bind("tcp://*:5560")

def proxy_with_audio_debug(xsub, xpub):
    """Manual proxy for audio channel with real-time byte debugging."""
    poller = zmq.Poller()
    poller.register(xsub, zmq.POLLIN)
    poller.register(xpub, zmq.POLLIN)
    while True:
        socks = dict(poller.poll())
        if xsub in socks and socks[xsub] == zmq.POLLIN:
            msg = xsub.recv_multipart()
            xpub.send_multipart(msg)
            if msg:
                topic = msg[0].decode('utf-8', errors='replace')
                payload = msg[1] if len(msg) > 1 else b''
                preview = payload[:20]
                print(f"[AUDIO DEBUG] topic='{topic}' | bytes={len(payload)} | head={preview}")
        if xpub in socks and socks[xpub] == zmq.POLLIN:
            msg = xpub.recv_multipart()
            xsub.send_multipart(msg)

# start the proxy in separate threads for non-blocking behavior
threading.Thread(target=zmq.proxy, args=(xsub, xpub), daemon=True).start()
threading.Thread(target=proxy_with_audio_debug, args=(xsub2, xpub2), daemon=True).start()
threading.Thread(target=zmq.proxy, args=(xsub3, xpub3), daemon=True).start()

try:
    threading.Event().wait()
except KeyboardInterrupt:
    print("Broker shutting down...")