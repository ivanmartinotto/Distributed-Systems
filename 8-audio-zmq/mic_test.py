import pyaudio

# Audio stream parameters
FORMAT = pyaudio.paInt16

CHANNELS = 1
RATE = 16000
CHUNK = 1024

audio = pyaudio.PyAudio()

# Open audio stream for recording
stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
print("Recording audio...")

while True:
    data = stream.read(CHUNK)
    loopback = data
    print(f"Audio chunk captured: {len(data)} bytes")