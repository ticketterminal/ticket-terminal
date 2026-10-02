"""Container-side client for host_bridge.py — used by server/main.py whenever
WMP_HOST_BRIDGE_SOCKET is set, so claude/codex run as real host processes instead
of inside this container. Every function here fails soft (returns a falsy/None
result) on any connection problem, so callers can treat "not configured" and
"configured but unreachable" the same way: fall back to spawning locally.
"""
import os
import socket

import host_bridge_protocol as proto


def _connect():
    socket_path = proto.default_socket_path()
    if not os.environ.get("WMP_HOST_BRIDGE_SOCKET"):
        return None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(socket_path))
        return sock
    except OSError:
        return None


def available() -> bool:
    sock = _connect()
    if sock is None:
        return False
    sock.close()
    return True


def resolve(provider: str) -> str | None:
    """The host's own resolved path for `provider`, or None if unconfigured,
    unreachable, or the bridge doesn't have it either."""
    sock = _connect()
    if sock is None:
        return None
    try:
        proto.send_frame(sock, {"op": "resolve", "provider": provider})
        reply = proto.recv_frame(sock)
        return reply.get("path") if reply and reply.get("ok") else None
    except OSError:
        return None
    finally:
        sock.close()


def launch(cmd: list[str], cwd: str | None) -> tuple[bool, str]:
    """Fire-and-forget host-side launch (e.g. opening a desktop app) — mirrors
    plain subprocess.Popen(cmd, cwd=cwd)'s "started, not awaited" semantics."""
    sock = _connect()
    if sock is None:
        return False, "host bridge not reachable at " + str(proto.default_socket_path())
    try:
        proto.send_frame(sock, {"op": "launch", "cmd": cmd, "cwd": cwd})
        reply = proto.recv_frame(sock)
        if reply and reply.get("ok"):
            return True, ""
        return False, (reply or {}).get("error", "host bridge refused to launch it")
    except OSError as e:
        return False, str(e)
    finally:
        sock.close()


class HostProcessHandle:
    """Stands in for subprocess.Popen in running_processes — implements exactly
    the four methods main.py ever calls on it (.poll/.terminate/.kill/.wait),
    each a request to the host bridge over the connection `spawn()` opened,
    since the real pid lives in the host's own PID namespace and can't be
    signaled directly from inside the container."""

    def __init__(self, sock):
        self._sock = sock

    def _request(self, msg, default_ok=False):
        try:
            proto.send_frame(self._sock, msg)
            reply = proto.recv_frame(self._sock)
            return reply if reply is not None else {"ok": default_ok}
        except OSError:
            return {"ok": default_ok}

    def poll(self):
        return 0 if self._request({"op": "poll"}).get("exited") else None

    def terminate(self):
        self._request({"op": "signal", "sig": "TERM"})

    def kill(self):
        self._request({"op": "signal", "sig": "KILL"})

    def wait(self, timeout=None):
        self._request({"op": "wait", "timeout": timeout}, default_ok=True)

    def close(self):
        """Not part of subprocess.Popen's interface — main.py calls this, when
        present (a plain Popen from the local-spawn path has no such method),
        once a session is fully torn down, so this session's control
        connection (and the bridge's thread serving it) doesn't linger forever."""
        try:
            self._sock.close()
        except OSError:
            pass


def spawn(cmd: list[str], cwd: str | None):
    """(master_fd, HostProcessHandle) for a new host-side session, or (None, None)
    if the bridge is unconfigured/unreachable/refused — callers fall back to a
    local pty.openpty()+Popen spawn in that case, same as today."""
    sock = _connect()
    if sock is None:
        return None, None
    try:
        proto.send_frame(sock, {"op": "spawn", "cmd": cmd, "cwd": cwd})
        reply, fd = proto.recv_frame_with_fd(sock)
        if not reply or not reply.get("ok") or fd is None:
            sock.close()
            return None, None
        return fd, HostProcessHandle(sock)
    except OSError:
        sock.close()
        return None, None
