import zmq
import threading


def start_channel(ctx, pub_port, sub_port, name):
    # create a XPUB/XSUB proxy to forward messages from publishers to subscribers
    frontend = ctx.socket(zmq.XSUB)   # receive from the PUBs
    frontend.bind(f"tcp://*:{pub_port}")

    backend = ctx.socket(zmq.XPUB)    # send to the SUBs
    backend.bind(f"tcp://*:{sub_port}")

    # HWM for non acumulating messages when subscribers are slow or disconnected
    frontend.setsockopt(zmq.RCVHWM, 10)
    backend.setsockopt(zmq.SNDHWM, 10)

    t = threading.Thread(
        target=zmq.proxy, args=(frontend, backend), daemon=True, name=f"proxy-{name}"
    )
    t.start()
    return t


def main():
    ctx = zmq.Context.instance()
    start_channel(ctx, 5555, 5556, "video")
    start_channel(ctx, 5557, 5558, "audio")
    start_channel(ctx, 5559, 5560, "text")

    print("[broker] on. Ctrl+C to stop.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n[broker] stopping...")
        ctx.term()


if __name__ == "__main__":
    main()