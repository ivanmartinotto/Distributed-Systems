import zmq
import pyaudio

# building publisher
context = zmq.Context()

audio = context.socket(zmq.PUB)
audio.connect("tcp://localhost:5555") # Broker XSUB binded address

def audio_capture():
    topic = "audio"
    # using pyaudio for audio capture
    p = pyaudio.PyAudio()

    stream_in = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)

    try:
        while True:
            data = stream_in.read(1024) # read mic chunks
            audio.send_multipart([topic.encode(), data]) # send message to broker
    except KeyboardInterrupt:
        pass

    stream_in.stop_stream()
    stream_in.close()
    p.terminate()
    

audio_capture()


