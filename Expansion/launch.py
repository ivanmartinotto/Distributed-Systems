# launcher.py
import subprocess
import time
import sys

processes = []

def start(name, cmd):
    print(f"[launcher] iniciando {name}...")
    p = subprocess.Popen(
        ["python"] + cmd,
        creationflags=subprocess.CREATE_NEW_CONSOLE  # janela separada (Windows)
    )
    processes.append((name, p))
    return p

try:
    discovery = start("discovery", ["discovery.py"])
    time.sleep(2)
    b1 = start("B1", ["broker.py", "--id", "B1", "--base-port", "5555"])
    time.sleep(2)
    b2 = start("B2", ["broker.py", "--id", "B2", "--base-port", "5575"])
    time.sleep(2)
    start("Ivan", ["member.py", "--id", "Ivan", "--room", "A"])
    start("Anna", ["member.py", "--id", "Anna", "--room", "A"])
    start("Fuji", ["member.py", "--id", "Fuji", "--room", "A"])

    input("\nPressione ENTER para matar B1 (failover demo)...")
    b1.terminate()
    print("[launcher] B1 morto. Observe os clientes migrando.")

    input("\nPressione ENTER para encerrar tudo...")
finally:
    for name, p in processes:
        try: p.terminate()
        except: pass
    print("[launcher] tudo encerrado.")