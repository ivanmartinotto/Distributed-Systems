"""
Shared constants and helpers between discovery, broker and clients.
"""
import json
import socket
import time

# ----- Discovery -----
DISCOVERY_PORT = 5570

# Discovery REQ/REP commands
CMD_REGISTER   = "REGISTER"    # broker -> discovery
CMD_HEARTBEAT  = "HEARTBEAT"   # broker -> discovery
CMD_LIST       = "LIST"        # client/broker -> discovery
CMD_UNREGISTER = "UNREGISTER"  # broker -> discovery

# Broker control commands (REP socket on base_port + 8)
CMD_HISTORY = "HISTORY"   # client -> broker: text history of a room
CMD_INFO    = "INFO"      # generic broker status (load, room counts)

# Time (seconds) without heartbeat until considering broker dead
BROKER_TIMEOUT = 5.0
# Interval between broker heartbeats
HEARTBEAT_INTERVAL = 1.5
# Presence reannouncement interval (seconds)
PRESENCE_INTERVAL = 3.0

# ----- Broker channel ports (relative to base_port) -----
# video    : base+0 / base+1   (XSUB-in / XPUB-out)   -- clients
# audio    : base+2 / base+3
# text     : base+4 / base+5
# presence : base+6 / base+7
# mesh     : base+8            (PUB out: peer brokers SUB here. Carries ONLY
#                               messages originated locally — prevents loops)
# control  : base+9            (REP socket: history, info)
# Each broker uses 10 ports. Use increments of >=10 between brokers.
NUM_PORTS_PER_BROKER = 10

def channel_ports(base_port):
    return {
        "video":    (base_port + 0, base_port + 1),
        "audio":    (base_port + 2, base_port + 3),
        "text":     (base_port + 4, base_port + 5),
        "presence": (base_port + 6, base_port + 7),
        "mesh":      base_port + 8,
        "control":   base_port + 9,
    }

# Available rooms
ROOMS = list("ABCDEFGHIJK")

# ----- Mesh-Aware topic format -----
# Topic: "{channel}:{broker_origin}:{room}:{user_id}"
# Example: "video:B1:A:user1"
def make_topic(channel, broker_id, room, user_id):
    return f"{channel}:{broker_id}:{room}:{user_id}"

def parse_topic(topic_str):
    """Returns (channel, broker_origin, room, user_id) or None if invalid."""
    parts = topic_str.split(":", 3)
    if len(parts) != 4:
        return None
    return parts[0], parts[1], parts[2], parts[3]

# ----- Text payload format (JSON) -----
# Required for: msg_id-based dedup, retry, history sync.
# Frame 1 (topic):   "text:{broker}:{room}:{sender}"
# Frame 2 (payload): {"msg_id":"sender-42","sender":"...","text":"...","ts":...}
def make_text_payload(msg_id, sender, text, ts=None):
    return json.dumps({
        "msg_id": msg_id,
        "sender": sender,
        "text": text,
        "ts": ts if ts is not None else time.time(),
    }).encode("utf-8")

def parse_text_payload(payload_bytes):
    try:
        return json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return None

# ----- Auto IP detection (RADMIN VPN compatible) -----
# RADMIN VPN typically assigns 26.x.x.x addresses.
# Use detect_radmin_ip() to advertise the right interface to peers.
def detect_local_ip(prefix=None):
    """
    Returns local IPv4 address. If prefix given (e.g. '26.'), prefer
    interfaces matching it. Falls back to the first non-loopback IP,
    then to gethostbyname, then to 127.0.0.1.
    """
    candidates = []
    try:
        hostname = socket.gethostname()
        candidates = list(socket.gethostbyname_ex(hostname)[2])
    except Exception:
        pass
    # Also probe via UDP trick (gives the IP of the default route iface)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        try:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            if ip not in candidates:
                candidates.append(ip)
        finally:
            s.close()
    except Exception:
        pass

    if prefix:
        for ip in candidates:
            if ip.startswith(prefix):
                return ip
    non_loopback = [ip for ip in candidates if not ip.startswith("127.")]
    if non_loopback:
        return non_loopback[0]
    if candidates:
        return candidates[0]
    return "127.0.0.1"

def detect_radmin_ip():
    """RADMIN VPN typically uses 26.x.x.x range."""
    return detect_local_ip(prefix="26.")
