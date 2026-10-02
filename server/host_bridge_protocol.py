"""Wire format shared by host_bridge.py (runs on the host) and host_bridge_client.py
(runs in the container) — pure stdlib, no app-specific knowledge, so neither side
needs the other's dependencies.

TCP to host.docker.internal:<port>, not a Unix socket: a bind-mounted Unix socket
file doesn't actually work across the container boundary on a VM-backed Docker
(Docker Desktop on macOS/Windows) — verified live, connect() fails with ENOTSUP —
because the container's kernel and the host's aren't the same kernel there, which
is exactly what SCM_RIGHTS fd-passing and AF_UNIX both need. TCP via
host.docker.internal works identically on Docker Desktop (built in) and native
Linux Docker (`--add-host=host.docker.internal:host-gateway`, see docker-compose.yml).

Every control message (everything except the raw byte stream `spawn` hands back)
is a 4-byte big-endian length prefix followed by that many bytes of JSON.
"""
import json
import os
import struct

_HEADER = struct.Struct(">I")

HOST = "host.docker.internal"


def default_port() -> int:
    override = os.environ.get("WMP_HOST_BRIDGE_PORT")
    return int(override) if override else 4174


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def send_frame(sock, obj: dict) -> None:
    payload = json.dumps(obj).encode()
    sock.sendall(_HEADER.pack(len(payload)) + payload)


def recv_frame(sock) -> dict | None:
    """None means the peer closed the connection (a clean EOF), not an error."""
    header = _recv_exact(sock, 4)
    if header is None:
        return None
    (length,) = _HEADER.unpack(header)
    body = _recv_exact(sock, length)
    if body is None:
        return None
    return json.loads(body.decode())
