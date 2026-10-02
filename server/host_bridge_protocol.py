"""Wire format shared by host_bridge.py (runs on the host) and host_bridge_client.py
(runs in the container) — pure stdlib, no app-specific knowledge, so neither side
needs the other's dependencies.

Every message is a 4-byte big-endian length prefix followed by that many bytes of
JSON — plain `send`/`recv` is enough for every op except `spawn`'s reply, which also
hands over the new PTY's master file descriptor via SCM_RIGHTS ancillary data on the
same underlying `sendmsg`/`recvmsg` call that carries the JSON. A received fd is a
first-class local file descriptor from then on — ordinary os.read/os.write/ioctl work
on it with no further socket traffic, which is the entire point of this scheme.
"""
import json
import os
import socket
import struct
from pathlib import Path

_HEADER = struct.Struct(">I")


def default_socket_path() -> Path:
    override = os.environ.get("WMP_HOST_BRIDGE_SOCKET")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".ticket-terminal" / "host-bridge.sock"


def _recv_exact(recv_some, n):
    """`recv_some(nbytes)` is either `sock.recv` or a wrapper around `sock.recvmsg`
    that also stashes any ancillary fds it sees — either way it returns b"" on a
    closed connection, same as plain `socket.recv`."""
    buf = b""
    while len(buf) < n:
        chunk = recv_some(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def send_frame(sock, obj: dict) -> None:
    payload = json.dumps(obj).encode()
    sock.sendall(_HEADER.pack(len(payload)) + payload)


def recv_frame(sock) -> dict | None:
    """None means the peer closed the connection (a clean EOF), not an error."""
    header = _recv_exact(sock.recv, 4)
    if header is None:
        return None
    (length,) = _HEADER.unpack(header)
    body = _recv_exact(sock.recv, length)
    if body is None:
        return None
    return json.loads(body.decode())


def send_frame_with_fd(sock, obj: dict, fd: int) -> None:
    payload = json.dumps(obj).encode()
    header = _HEADER.pack(len(payload)) + payload
    ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, struct.pack("i", fd))]
    sock.sendmsg([header], ancillary)


def recv_frame_with_fd(sock) -> tuple[dict | None, int | None]:
    """Like recv_frame, but also returns a passed fd if one arrives (None if the
    reply carried no fd, e.g. a failed spawn). Uses recvmsg for every read so
    ancillary data is never missed regardless of how the bytes happen to be
    chunked across the underlying stream."""
    fds: list[int] = []

    def recv_some(n):
        # Request exactly n, like plain socket.recv(n) — recvmsg() delivers any
        # SCM_RIGHTS ancillary data on whichever call first touches the bytes the
        # sender passed to its one sendmsg() call, even a short partial read, so
        # asking for exactly what _recv_exact wants never risks missing it.
        chunk, ancdata, _flags, _addr = sock.recvmsg(n, socket.CMSG_LEN(4))
        for level, type_, data in ancdata:
            if level == socket.SOL_SOCKET and type_ == socket.SCM_RIGHTS:
                fds.extend(struct.unpack(f"{len(data) // 4}i", data))
        return chunk

    header = _recv_exact(recv_some, 4)
    if header is None:
        return None, None
    (length,) = _HEADER.unpack(header)
    body = _recv_exact(recv_some, length)
    if body is None:
        return None, None
    return json.loads(body.decode()), (fds[0] if fds else None)
