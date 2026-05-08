"""
Host-side launcher. Spawns discovery + N brokers (+ optional local members).
Auto-detects RADMIN VPN IP and prints the address remote PCs should use.

Usage:
  python launch.py                    # 2 brokers + 3 local members (default)
  python launch.py --brokers 3        # custom broker count
  python launch.py --brokers 2 --members 0   # host runs only infra; remote PCs run members

Remote PC:
  python member.py --id Alice --discovery tcp://<HOST_RADMIN_IP>:5570
"""
import argparse
import socket
import subprocess
import sys
import time

from common import DISCOVERY_PORT, NUM_PORTS_PER_BROKER, detect_radmin_ip

processes = []


def start(name, cmd):
    print(f"[launcher] starting {name}...")
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NEW_CONSOLE
    p = subprocess.Popen(["python"] + cmd, creationflags=creation_flags)
    processes.append((name, p))
    return p


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--brokers", type=int, default=2,
                        help="number of brokers to launch")
    parser.add_argument("--members", type=int, default=3,
                        help="number of local test members (set 0 if remote PCs run them)")
    parser.add_argument("--room", default="A", choices=list("ABCDEFGHIJK"),
                        help="room for local test members")
    parser.add_argument("--base-port", type=int, default=5555,
                        help="first broker base port (each broker uses NUM_PORTS_PER_BROKER ports)")
    parser.add_argument("--port-step", type=int, default=10,
                        help="step between brokers' base ports (must be >= NUM_PORTS_PER_BROKER)")
    parser.add_argument("--names", default="",
                        help="comma-separated member names (optional). Default: M1, M2, ...")
    args = parser.parse_args()

    if args.port_step < NUM_PORTS_PER_BROKER:
        print(f"[launcher] WARNING: port-step={args.port_step} < {NUM_PORTS_PER_BROKER}; "
              f"broker port ranges will overlap")

    host_ip = detect_radmin_ip()
    discovery_addr = f"tcp://{host_ip}:{DISCOVERY_PORT}"

    print("=" * 70)
    print(f"[launcher] host RADMIN IP detected: {host_ip}")
    print(f"[launcher] discovery will be at:    {discovery_addr}")
    print(f"[launcher] remote PC command:")
    print(f"           python member.py --id <name> --discovery {discovery_addr}")
    print("=" * 70)

    try:
        start("discovery", ["discovery.py"])
        time.sleep(0.8)

        for i in range(args.brokers):
            bid = f"B{i+1}"
            base = args.base_port + i * args.port_step
            start(bid, ["broker.py", "--id", bid, "--base-port", str(base),
                        "--discovery", discovery_addr, "--host", host_ip])
            time.sleep(0.5)

        if args.members > 0:
            if args.names:
                names = [n.strip() for n in args.names.split(",") if n.strip()]
            else:
                names = [f"M{i+1}" for i in range(args.members)]
            for name in names[:args.members]:
                start(name, ["member.py", "--id", name, "--room", args.room,
                             "--discovery", discovery_addr])

        print("\n[launcher] Press ENTER to kill B1 (failover demo, optional)...")
        input()
        for name, p in processes:
            if name == "B1":
                p.terminate()
                print("[launcher] B1 killed. Watch clients migrate.")
                break

        print("\n[launcher] Press ENTER to shut everything down...")
        input()
    finally:
        for name, p in processes:
            try: p.terminate()
            except Exception: pass
        print("[launcher] all processes terminated.")


if __name__ == "__main__":
    main()
