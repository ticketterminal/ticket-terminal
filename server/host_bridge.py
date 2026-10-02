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
Unix socket instead of implicit in a bind mount.

Protocol (server/host_bridge_protocol.py has the exact framing):
  resolve {provider}         -> {ok, path}            one-shot
  launch  {cmd, cwd}         -> {ok}                   one-shot, fire-and-forget
  spawn   {cmd, cwd}         -> {ok, pid} + a passed fd (the PTY master), then the
                                 SAME connection stays open as that session's
                                 control channel for:
  poll    {}                 -> {ok, exited}
  signal  {sig: TERM|KILL}   -> {ok}
  wait    {timeout}          -> {ok, exited}

A session's child process is intentionally left running if this bridge exits or
the connection drops — exactly like a local spawn today is left running if the
Ticket Terminal server process itself dies. Nothing here auto-kills on disconnect.
"""
import os
import pty
import socket
import subprocess
import sys
import threading
import time

import agent_launch
import host_bridge_protocol as proto


def _resolve(msg):
    path = agent_launch.agent_executable(msg["provider"])
    return {"ok": bool(path), "path": path}


def _launch(msg):
    try:
        subprocess.Popen(msg["cmd"], cwd=msg.get("cwd") or None, env=agent_launch.build_child_env())
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _spawn(conn, msg):
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
        return None
    os.close(slave_fd)  # the child (and only the child) keeps the slave end open
    print(f"[host-bridge] spawned pid {proc.pid}: {' '.join(cmd)} (cwd={cwd or os.getcwd()})", file=sys.stderr)
    proto.send_frame_with_fd(conn, {"ok": True, "pid": proc.pid}, master_fd)
    os.close(master_fd)  # our copy; the client's received copy keeps the PTY alive
    return proc


def _poll(proc):
    return {"ok": True, "exited": proc.poll() is not None}


def _signal(proc, msg):
    sig = msg.get("sig", "TERM")
    try:
        if sig == "KILL":
            proc.kill()
        else:
            proc.terminate()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _wait(proc, msg):
    timeout = msg.get("timeout")
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
    return {"ok": True, "exited": proc.poll() is not None}


def _handle_connection(conn):
    proc = None
    try:
        while True:
            msg = proto.recv_frame(conn)
            if msg is None:
                return
            op = msg.get("op")
            if op == "resolve":
                proto.send_frame(conn, _resolve(msg))
            elif op == "launch":
                proto.send_frame(conn, _launch(msg))
            elif op == "spawn" and proc is None:
                proc = _spawn(conn, msg)
                if proc is None:
                    return  # spawn failed, already reported; nothing left to do on this connection
            elif op == "poll" and proc is not None:
                proto.send_frame(conn, _poll(proc))
            elif op == "signal" and proc is not None:
                proto.send_frame(conn, _signal(proc, msg))
            elif op == "wait" and proc is not None:
                proto.send_frame(conn, _wait(proc, msg))
            else:
                proto.send_frame(conn, {"ok": False, "error": "bad request for this connection's state"})
    except (OSError, ValueError) as e:
        print(f"[host-bridge] connection error: {e}", file=sys.stderr)
    finally:
        conn.close()


def serve(socket_path):
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.connect(str(socket_path))
            probe.close()
            raise SystemExit(f"host_bridge.py is already running on {socket_path}")
        except ConnectionRefusedError:
            socket_path.unlink()  # stale socket file from a bridge that didn't exit cleanly

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    os.chmod(socket_path, 0o600)
    server.listen(8)
    print(f"[host-bridge] listening on {socket_path} — Ctrl-C to stop", file=sys.stderr)
    try:
        while True:
            conn, _ = server.accept()
            threading.Thread(target=_handle_connection, args=(conn,), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        socket_path.unlink(missing_ok=True)


if __name__ == "__main__":
    serve(proto.default_socket_path())
