#!/usr/bin/env python3
"""Run this directly on your host, outside Docker: `python3 server/host_bridge.py`.

Stdlib only, no pip install — so there's nothing to set up beyond having Python 3
and claude/codex themselves installed and signed in, same as a native (non-Docker)
Ticket Terminal install already needs.

Lets a containerized Ticket Terminal server spawn claude/codex as genuine host
processes — same filesystem, same uid, same installed CLI versions and
credentials a native invocation would use — instead of running them inside the
container, which buys nothing here: the Docker option already bind-mounts your
whole $HOME in (see README's "Docker" section, "a packaging convenience, not a
sandbox"), so this doesn't open any trust boundary that didn't already exist, it
just makes "the container can make me run a command" explicit over one local
TCP port instead of implicit in a bind mount.

Binds 127.0.0.1 only — same "localhost is the boundary" posture as the rest of
this app — reached from inside the container via Docker's host.docker.internal.

Protocol (server/host_bridge_protocol.py has the exact framing). Every connection
does exactly one thing, then closes, except `spawn`, which replies once and then
IS the raw PTY byte stream for the rest of the session:
  resolve {provider}                  -> {ok, path}
  launch  {cmd, cwd}                   -> {ok}
  spawn   {cmd, cwd}                   -> {ok, pid, session}, then raw bytes both
                                          ways until the session ends
  poll    {session}                    -> {ok, exited}
  signal  {session, sig: TERM|KILL}    -> {ok}
  wait    {session, timeout}           -> {ok, exited}
  resize  {session, rows, cols}        -> {ok}

A session's child process is intentionally left running if this bridge exits or
a connection drops — exactly like a local spawn today is left running if the
Ticket Terminal server process itself dies. `sessions` (pid + the real host PTY
master fd, by session id) is never pruned except by this process exiting: poll/
signal/wait/resize on an id this process no longer knows about (because it was
never ours, not because of pruning) are treated as "already gone", not an error.
"""
import os
import pty
import select
import socket
import subprocess
import sys
import threading
import uuid

import agent_launch
import host_bridge_protocol as proto

sessions = {}
sessions_lock = threading.Lock()


def _resolve(msg):
    path = agent_launch.agent_executable(msg["provider"])
    return {"ok": bool(path), "path": path}


def _launch(msg):
    try:
        subprocess.Popen(msg["cmd"], cwd=msg.get("cwd") or None, env=agent_launch.build_child_env())
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _session_op(op, msg):
    with sessions_lock:
        entry = sessions.get(msg.get("session"))
    if entry is None:
        # Not ours (anymore, or ever) — a poll/wait on a session we have no
        # record of is indistinguishable from one that's already exited.
        return {"ok": True, "exited": True} if op in ("poll", "wait") else {"ok": True}
    proc = entry["proc"]
    if op == "poll":
        return {"ok": True, "exited": proc.poll() is not None}
    if op == "signal":
        try:
            proc.kill() if msg.get("sig") == "KILL" else proc.terminate()
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}
    if op == "wait":
        try:
            proc.wait(timeout=msg.get("timeout"))
        except subprocess.TimeoutExpired:
            pass
        return {"ok": True, "exited": proc.poll() is not None}
    if op == "resize":
        agent_launch.set_winsize(entry["master_fd"], msg.get("rows", 30), msg.get("cols", 100))
        return {"ok": True}
    return {"ok": False, "error": "unknown op"}


def _relay(conn, master_fd):
    """Shovel bytes both ways between the TCP connection and the real host PTY
    until either side is done — the child exiting shows up here as the real
    pty's master read failing (EIO, the classic Linux PTY-no-more-slave-refs
    behavior) or returning empty, same two signals the container's own
    read_pty() already treats as EOF."""
    conn.setblocking(True)
    sock_fd = conn.fileno()
    try:
        while True:
            readable, _, _ = select.select([sock_fd, master_fd], [], [])
            if sock_fd in readable:
                try:
                    data = conn.recv(4096)
                except OSError:
                    break
                if not data:
                    break
                try:
                    os.write(master_fd, data)
                except OSError:
                    break
            if master_fd in readable:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    data = b""
                if not data:
                    break
                try:
                    conn.sendall(data)
                except OSError:
                    break
    finally:
        try:
            conn.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _spawn_and_relay(conn, msg):
    cmd, cwd = msg["cmd"], msg.get("cwd") or None
    master_fd, slave_fd = pty.openpty()
    try:
        proc = subprocess.Popen(
            cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            cwd=cwd, preexec_fn=agent_launch.pty_child_preexec, env=agent_launch.build_child_env(),
        )
    except Exception as e:
        os.close(master_fd)
        os.close(slave_fd)
        proto.send_frame(conn, {"ok": False, "error": str(e)})
        return
    os.close(slave_fd)  # the child (and only the child) keeps the slave end open
    agent_launch.set_winsize(master_fd, 30, 100)
    session_id = str(uuid.uuid4())
    with sessions_lock:
        sessions[session_id] = {"proc": proc, "master_fd": master_fd}
    print(f"[host-bridge] spawned pid {proc.pid} session {session_id}: {' '.join(cmd)} (cwd={cwd or os.getcwd()})", file=sys.stderr)
    proto.send_frame(conn, {"ok": True, "pid": proc.pid, "session": session_id})
    _relay(conn, master_fd)
    # Deliberately not popping `sessions` or closing master_fd here: the
    # connection ending doesn't mean the session is over (see the module
    # docstring) — poll/signal/wait must keep working after this returns.


def _handle_connection(conn):
    try:
        msg = proto.recv_frame(conn)
        if msg is None:
            return
        op = msg.get("op")
        if op == "resolve":
            proto.send_frame(conn, _resolve(msg))
        elif op == "launch":
            proto.send_frame(conn, _launch(msg))
        elif op == "spawn":
            _spawn_and_relay(conn, msg)
        elif op in ("poll", "signal", "wait", "resize"):
            proto.send_frame(conn, _session_op(op, msg))
        else:
            proto.send_frame(conn, {"ok": False, "error": "unknown op"})
    except (OSError, ValueError) as e:
        print(f"[host-bridge] connection error: {e}", file=sys.stderr)
    finally:
        try:
            conn.close()
        except OSError:
            pass


def serve(port):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen(8)
    print(f"[host-bridge] listening on 127.0.0.1:{port} (reachable from a container via host.docker.internal) — Ctrl-C to stop", file=sys.stderr)
    try:
        while True:
            conn, _ = server.accept()
            threading.Thread(target=_handle_connection, args=(conn,), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()


if __name__ == "__main__":
    serve(proto.default_port())
