import subprocess
import sys
import os

def launch(n_members):
    folder = os.path.dirname(os.path.abspath(__file__))

    subprocess.Popen(
        f'start "Broker" cmd /k python meet_broker.py',
        shell=True, cwd=folder
    )

    for i in range(1, n_members + 1):
        subprocess.Popen(
            f'start "Member {i}" cmd /k python member.py {i}',
            shell=True, cwd=folder
        )

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    launch(n)
    print(f"Launched broker + {n} member(s).")