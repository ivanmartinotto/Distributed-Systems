import zmq
import threading

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

# start the proxy in separate threads for non-blocking behavior
threading.Thread(target=zmq.proxy, args=(xsub, xpub), daemon=True).start()
threading.Thread(target=zmq.proxy, args=(xsub2, xpub2), daemon=True).start()
threading.Thread(target=zmq.proxy, args=(xsub3, xpub3), daemon=True).start()

try:
    threading.Event().wait()
except KeyboardInterrupt:
    print("Broker shutting down...")