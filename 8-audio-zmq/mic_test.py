import pyaudio

# Audio stream parameters
FORMAT = pyaudio.paInt16

CHANNELS = 1
RATE = 16000
CHUNK = 1024

audio = pyaudio.PyAudio()

# Open input audio stream for recording
stream_in = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
print("Recording audio...")

# Open output audio stream for reproduction
stream_out = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True, frames_per_buffer=CHUNK)
print("Loopback rodando...")

try:
    while True:
        data = stream_in.read(CHUNK)
        stream_out.write(data)
except KeyboardInterrupt:
    pass

stream_in.stop_stream()
stream_out.stop_stream()
stream_in.close()
stream_out.close()
audio.terminate()