"""Container-side client for host_bridge.py — used by server/main.py whenever
WMP_HOST_BRIDGE_PORT is set, so claude/codex run as real host processes instead
of inside this container. Every function here fails soft (returns a falsy/None
result) on any connection problem, so callers can treat "not configured" and
"configured but unreachable" the same way: fall back to spawning locally.
"""
import os
import socket
import threading

import host_bridge_protocol as proto


def _connect():
    if not os.environ.get("WMP_HOST_BRIDGE_PORT"):
        return None
    try:
        return socket.create_connection((proto.HOST, proto.default_port()), timeout=5)
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
        return False, "host bridge not reachable at " + proto.HOST + ":" + str(proto.default_port())
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
    each a short one-shot control connection naming this session's id, since the
    real pid lives in the host's own PID namespace and can't be signaled
    directly from inside the container. `.resize` is additional — main.py calls
    it instead of an ioctl, since the only real PTY device is on the host now."""

    def __init__(self, session_id, data_conn, pipe_end):
        self._session = session_id
        self._data_conn = data_conn
        self._pipe_end = pipe_end

    def _pump(self, src, dst):
        try:
            while True:
                data = src.recv(4096)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    def start_relay(self):
        threading.Thread(target=self._pump, args=(self._data_conn, self._pipe_end), daemon=True).start()
        threading.Thread(target=self._pump, args=(self._pipe_end, self._data_conn), daemon=True).start()

    def _control(self, op, extra=None, default_ok=False):
        sock = _connect()
        if sock is None:
            return {"ok": default_ok}
        try:
            msg = {"op": op, "session": self._session}
            if extra:
                msg.update(extra)
            proto.send_frame(sock, msg)
            reply = proto.recv_frame(sock)
            return reply if reply is not None else {"ok": default_ok}
        except OSError:
            return {"ok": default_ok}
        finally:
            sock.close()

    def poll(self):
        return 0 if self._control("poll").get("exited") else None

    def terminate(self):
        self._control("signal", {"sig": "TERM"})

    def kill(self):
        self._control("signal", {"sig": "KILL"})

    def wait(self, timeout=None):
        self._control("wait", {"timeout": timeout}, default_ok=True)

    def resize(self, rows, cols):
        self._control("resize", {"rows": rows, "cols": cols})

    def close(self):
        """Not part of subprocess.Popen's interface — main.py calls this, when
        present (a plain Popen from the local-spawn path has no such method),
        once a session is fully torn down, to release this session's data
        connection and local socketpair end."""
        for sock in (self._data_conn, self._pipe_end):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass


def spawn(cmd: list[str], cwd: str | None):
    """(master_fd, HostProcessHandle) for a new host-side session, or (None, None)
    if the bridge is unconfigured/unreachable/refused — callers fall back to a
    local pty.openpty()+Popen spawn in that case, same as today.

    master_fd is one end of a local socketpair (entirely within this container,
    no VM boundary involved) — main.py treats it exactly like a real PTY master
    fd for os.read/os.write (a socketpair end supports both), which is all it
    ever does with it directly; resizing goes through HostProcessHandle.resize
    instead of an ioctl, since the real PTY device only exists on the host now.
    A background thread pair relays bytes between the other end and the TCP
    connection to the bridge for the rest of the session's life."""
    conn = _connect()
    if conn is None:
        return None, None
    try:
        proto.send_frame(conn, {"op": "spawn", "cmd": cmd, "cwd": cwd})
        reply = proto.recv_frame(conn)
    except OSError:
        conn.close()
        return None, None
    if not reply or not reply.get("ok"):
        conn.close()
        return None, None
    local_end, remote_end = socket.socketpair()
    master_fd = local_end.detach()  # a bare fd now; local_end no longer owns/closes it
    handle = HostProcessHandle(reply["session"], conn, remote_end)
    handle.start_relay()
    return master_fd, handle
