import zmq

context = zmq.Context()

xsub, xpub = context.socket(zmq.XSUB),  context.socket(zmq.XPUB)

xsub.bind("tcp://*:5555")
xpub.bind("tcp://*:5556")

try:
    zmq.proxy(xsub, xpub)
except KeyboardInterrupt:
    pass