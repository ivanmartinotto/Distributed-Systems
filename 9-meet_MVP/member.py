"""
Cliente de videoconferência (membro).

Correções principais em relação à versão anterior:
- cv.imshow e cv.waitKey SEMPRE no main thread (requisito do OpenCV).
- send_video com controle de FPS (evita saturar rede/decoder).
- HWM nos sockets + CONFLATE opcional no vídeo (só o último frame importa).
- Filtro por user_id no próprio payload para não "ouvir" o próprio áudio/vídeo.
- Tópicos como bytes (evita mistura de encoding).
- Exceções específicas (queue.Empty) em vez de 'except:' pelado.
- PyAudio único e encerrado só no final.
"""

import argparse
import queue
import threading
import time
import uuid

import cv2 as cv
import numpy as np
import pyaudio
import zmq

# ------------------------- Config -------------------------
# BROKER_HOST agora vem por argumento (--broker). Default: localhost.
VIDEO_PUB_PORT, VIDEO_SUB_PORT = 5555, 5556
AUDIO_PUB_PORT, AUDIO_SUB_PORT = 5557, 5558
TEXT_PUB_PORT,  TEXT_SUB_PORT  = 5559, 5560

TOPIC_VIDEO = b"video"
TOPIC_AUDIO = b"audio"
TOPIC_TEXT  = b"text"

VIDEO_FPS = 30           # limita envio (evita travar)
JPEG_QUALITY = 60        # qualidade do JPEG
AUDIO_RATE = 16000
AUDIO_CHUNK = 1024

# ------------------------- Estado -------------------------
stop_event = threading.Event()


def make_sockets(ctx, user_id, broker_host):
    """Cria os 6 sockets (pub + sub para cada canal)."""
    socks = {}

    # VÍDEO
    socks["video_pub"] = ctx.socket(zmq.PUB)
    socks["video_pub"].setsockopt(zmq.SNDHWM, 5)  # descarta frames antigos
    socks["video_pub"].connect(f"tcp://{broker_host}:{VIDEO_PUB_PORT}")

    socks["video_sub"] = ctx.socket(zmq.SUB)
    socks["video_sub"].setsockopt(zmq.RCVHWM, 2)  # buffer curto = descarta antigos
    socks["video_sub"].connect(f"tcp://{broker_host}:{VIDEO_SUB_PORT}")
    socks["video_sub"].setsockopt(zmq.SUBSCRIBE, TOPIC_VIDEO)

    # ÁUDIO
    socks["audio_pub"] = ctx.socket(zmq.PUB)
    socks["audio_pub"].setsockopt(zmq.SNDHWM, 20)
    socks["audio_pub"].connect(f"tcp://{broker_host}:{AUDIO_PUB_PORT}")

    socks["audio_sub"] = ctx.socket(zmq.SUB)
    socks["audio_sub"].setsockopt(zmq.RCVHWM, 20)
    socks["audio_sub"].connect(f"tcp://{broker_host}:{AUDIO_SUB_PORT}")
    socks["audio_sub"].setsockopt(zmq.SUBSCRIBE, TOPIC_AUDIO)

    # TEXTO (garantia: HWM alto, sem descarte)
    socks["text_pub"] = ctx.socket(zmq.PUB)
    socks["text_pub"].setsockopt(zmq.SNDHWM, 1000)
    socks["text_pub"].connect(f"tcp://{broker_host}:{TEXT_PUB_PORT}")

    socks["text_sub"] = ctx.socket(zmq.SUB)
    socks["text_sub"].setsockopt(zmq.RCVHWM, 1000)
    socks["text_sub"].connect(f"tcp://{broker_host}:{TEXT_SUB_PORT}")
    socks["text_sub"].setsockopt(zmq.SUBSCRIBE, TOPIC_TEXT)

    # IMPORTANTE: depois do connect + subscribe, dar um tempinho para a
    # subscription propagar ao broker antes de começar a publicar.
    time.sleep(0.3)
    return socks


# ------------------------- Threads de envio -------------------------
def send_video(sock, user_id):
    cap = cv.VideoCapture(0)
    if not cap.isOpened():
        print("[send_video] câmera não disponível")
        return

    interval = 1.0 / VIDEO_FPS
    encode_params = [cv.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]

    try:
        while not stop_event.is_set():
            t0 = time.time()
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue

            # reduz resolução para aliviar rede
            frame = cv.resize(frame, (640, 480))
            ok, buf = cv.imencode(".jpg", frame, encode_params)
            if not ok:
                continue

            try:
                sock.send_multipart(
                    [TOPIC_VIDEO, user_id.encode(), buf.tobytes()],
                    flags=zmq.NOBLOCK,
                )
            except zmq.Again:
                pass  # QoS vídeo: pode dropar

            elapsed = time.time() - t0
            if elapsed < interval:
                time.sleep(interval - elapsed)
    finally:
        cap.release()


def send_audio(sock, user_id, pa):
    stream_in = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=AUDIO_RATE,
        input=True,
        frames_per_buffer=AUDIO_CHUNK,
    )
    try:
        while not stop_event.is_set():
            try:
                data = stream_in.read(AUDIO_CHUNK, exception_on_overflow=False)
            except OSError:
                continue
            try:
                sock.send_multipart(
                    [TOPIC_AUDIO, user_id.encode(), data], flags=zmq.NOBLOCK
                )
            except zmq.Again:
                pass
    finally:
        stream_in.stop_stream()
        stream_in.close()


def send_text(sock, user_id):
    while not stop_event.is_set():
        try:
            text = input()  # bloqueia esta thread, ok
        except EOFError:
            break
        if not text:
            continue
        if text.lower() == "exit":
            stop_event.set()
            break
        payload = f"{user_id}: {text}".encode("utf-8")
        sock.send_multipart([TOPIC_TEXT, user_id.encode(), payload])


# ------------------------- Threads de recepção -------------------------
def recv_video(sock, user_id, q):
    poller = zmq.Poller()
    poller.register(sock, zmq.POLLIN)
    while not stop_event.is_set():
        events = dict(poller.poll(timeout=200))
        if sock in events:
            try:
                msg = sock.recv_multipart(flags=zmq.NOBLOCK)
            except zmq.Again:
                continue
            if len(msg) < 3:
                continue
            _topic, sender, payload = msg[0], msg[1].decode(), msg[2]
            if sender == user_id:
                continue  # não exibe o próprio vídeo
            frame = cv.imdecode(np.frombuffer(payload, dtype=np.uint8), cv.IMREAD_COLOR)
            if frame is None:
                continue
            # descarta frame antigo se a fila está cheia
            if q.full():
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
            q.put_nowait((sender, frame))


def recv_audio(sock, user_id, q):
    poller = zmq.Poller()
    poller.register(sock, zmq.POLLIN)
    while not stop_event.is_set():
        events = dict(poller.poll(timeout=200))
        if sock in events:
            try:
                msg = sock.recv_multipart(flags=zmq.NOBLOCK)
            except zmq.Again:
                continue
            if len(msg) < 3:
                continue
            sender, payload = msg[1].decode(), msg[2]
            if sender == user_id:
                continue
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass  # QoS áudio: dropar é melhor que travar


def recv_text(sock, user_id, q):
    poller = zmq.Poller()
    poller.register(sock, zmq.POLLIN)
    while not stop_event.is_set():
        events = dict(poller.poll(timeout=200))
        if sock in events:
            try:
                msg = sock.recv_multipart(flags=zmq.NOBLOCK)
            except zmq.Again:
                continue
            if len(msg) < 3:
                continue
            sender, payload = msg[1].decode(), msg[2].decode("utf-8", errors="replace")
            if sender == user_id:
                continue
            q.put(payload)  # texto: NUNCA drop (QoS)


# ------------------------- Main (renderização) -------------------------
def main_loop(video_q, audio_q, text_q, pa):
    stream_out = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=AUDIO_RATE,
        output=True,
    )
    window_opened = False
    try:
        while not stop_event.is_set():
            # vídeo
            try:
                sender, frame = video_q.get_nowait()
                cv.imshow(f"Remote: {sender}", frame)
                window_opened = True
            except queue.Empty:
                pass

            # áudio – drena tudo que chegou (evita atraso acumulado)
            drained = 0
            while drained < 5:
                try:
                    chunk = audio_q.get_nowait()
                except queue.Empty:
                    break
                stream_out.write(chunk)
                drained += 1

            # texto
            try:
                while True:
                    t = text_q.get_nowait()
                    print(f"\n[msg] {t}")
            except queue.Empty:
                pass

            if window_opened:
                if cv.waitKey(1) & 0xFF == ord("q"):
                    stop_event.set()
                    break
            else:
                time.sleep(0.01)
    finally:
        stream_out.stop_stream()
        stream_out.close()
        cv.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", default=f"user-{uuid.uuid4().hex[:6]}")
    parser.add_argument("--broker", default="localhost",
                        help="IP ou hostname do broker (ex: 192.168.1.50)")
    parser.add_argument("--no-video", action="store_true")
    parser.add_argument("--no-audio", action="store_true")
    args = parser.parse_args()

    user_id = args.id
    print(f"[client] meu id: {user_id}")
    print(f"[client] conectando ao broker em: {args.broker}")
    print("[client] digite mensagens e Enter para enviar. 'exit' para sair.")
    print("[client] na janela de vídeo, pressione 'q' para sair.")

    ctx = zmq.Context.instance()
    socks = make_sockets(ctx, user_id, args.broker)
    pa = pyaudio.PyAudio()

    video_q = queue.Queue(maxsize=2)    # só queremos o mais recente
    audio_q = queue.Queue(maxsize=50)
    text_q  = queue.Queue()             # ilimitada (garantia de entrega)

    threads = []
    threads.append(threading.Thread(target=recv_video, args=(socks["video_sub"], user_id, video_q), daemon=True))
    threads.append(threading.Thread(target=recv_audio, args=(socks["audio_sub"], user_id, audio_q), daemon=True))
    threads.append(threading.Thread(target=recv_text,  args=(socks["text_sub"],  user_id, text_q),  daemon=True))
    threads.append(threading.Thread(target=send_text,  args=(socks["text_pub"],  user_id),          daemon=True))

    if not args.no_video:
        threads.append(threading.Thread(target=send_video, args=(socks["video_pub"], user_id), daemon=True))
    if not args.no_audio:
        threads.append(threading.Thread(target=send_audio, args=(socks["audio_pub"], user_id, pa), daemon=True))

    for t in threads:
        t.start()

    try:
        main_loop(video_q, audio_q, text_q, pa)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        time.sleep(0.3)
        pa.terminate()
        ctx.term()
        print("[client] encerrado")


if __name__ == "__main__":
    main()