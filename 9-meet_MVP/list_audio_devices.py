import sounddevice as sd

print("Dispositivos de áudio disponíveis:")
print(sd.query_devices())
print(f"\nDispositivo padrão atual: {sd.default.device}")
print("\nPara forçar um dispositivo de saída específico, note o índice (número) do dispositivo desejado.")

