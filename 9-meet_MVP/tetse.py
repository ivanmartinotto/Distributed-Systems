import sounddevice as sd
import numpy as np

# Tom de 1 segundo, 16kHz
tone = np.sin(2 * np.pi * 440 * np.arange(16000) / 16000) * 0.3
tone = tone.astype(np.float32)

sd.play(tone, samplerate=16000)
sd.wait()  # Aguarda terminar
print("Done")
