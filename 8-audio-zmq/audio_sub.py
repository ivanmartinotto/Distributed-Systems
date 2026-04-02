import zmq
import pyaudio

context = zmq.Context()

audio = context.socket(zmq.SUB)
audio.connect("tcp://localhost:5556") # Broker XPUB binded address

audio.setsockopt_string(zmq.SUBSCRIBE, "audio")

def receive_audio():
    # using pyaudio for audio playback
    p = pyaudio.PyAudio()

    stream_out = p.open(format=pyaudio.paInt16, channels=1, rate=16000, output=True, frames_per_buffer=1024)

    try:
        while True:
            msg = audio.recv_multipart()
            if msg:
                stream_out.write(msg[1]) # write speaker chunks
                msg = None
    except KeyboardInterrupt:
        pass

    stream_out.stop_stream()
    stream_out.close()
    p.terminate()

receive_audio()