"""Real (not mocked) end-to-end test of the host<->container bridge: runs
host_bridge.py's actual connection handler against a real TCP listener on
127.0.0.1 in this same test process, and drives host_bridge_client (the side
server/main.py uses) against it — genuine subprocess spawning and a genuine
byte relay over a real socket, no Docker required (the one thing this can't
exercise is the host.docker.internal hop itself, verified separately, live,
against a real container: see PR #42's description)."""
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import host_bridge
import host_bridge_client
import host_bridge_protocol as proto


class HostBridgeEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.bind(("127.0.0.1", 0))
        self.port = self.server_sock.getsockname()[1]
        self.server_sock.settimeout(0.2)
        self.server_sock.listen(8)
        self.stopping = False

        def accept_loop():
            while not self.stopping:
                try:
                    conn, _ = self.server_sock.accept()
                except (socket.timeout, OSError):
                    continue
                threading.Thread(target=host_bridge._handle_connection, args=(conn,), daemon=True).start()

        self.accept_thread = threading.Thread(target=accept_loop, daemon=True)
        self.accept_thread.start()

        # host_bridge_protocol.HOST is "host.docker.internal" for the real
        # container case; here we're one process talking to itself, so patch it
        # to loopback — the Docker hop itself is verified separately, live.
        self.host_patch = patch.object(proto, "HOST", "127.0.0.1")
        self.host_patch.start()
        self.env_patch = patch.dict(os.environ, {"WMP_HOST_BRIDGE_PORT": str(self.port)})
        self.env_patch.start()

    def tearDown(self):
        self.stopping = True
        self.accept_thread.join(timeout=2)
        self.server_sock.close()
        self.env_patch.stop()
        self.host_patch.stop()
        self.tmp.cleanup()
        host_bridge.sessions.clear()

    def test_available_is_true_once_the_bridge_is_listening(self):
        self.assertTrue(host_bridge_client.available())

    def test_available_is_false_against_a_dead_port(self):
        with patch.dict(os.environ, {"WMP_HOST_BRIDGE_PORT": "1"}):  # nothing listens on port 1
            self.assertFalse(host_bridge_client.available())

    def test_resolve_relays_a_real_lookup(self):
        # "ls" rather than "claude"/"codex" so this is deterministic on any
        # machine — agent_launch's own resolution rules are covered in
        # test_agent_launch.py, this just proves the wire protocol relays it.
        path = host_bridge_client.resolve("ls")
        self.assertIsNotNone(path)
        self.assertTrue(path.endswith("/ls"))

    def test_resolve_of_something_nowhere_on_path_is_none(self):
        self.assertIsNone(host_bridge_client.resolve("not-a-real-executable-xyz"))

    def test_launch_actually_starts_a_real_process(self):
        marker = Path(self.tmp.name) / "launched.txt"
        ok, error = host_bridge_client.launch(
            [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('ok')"], str(self.tmp.name),
        )
        self.assertTrue(ok, error)
        deadline = time.time() + 5
        while not marker.exists() and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(marker.read_text(), "ok")

    def _read_until(self, fd, needle, deadline_s=5):
        deadline = time.time() + deadline_s
        data = b""
        while needle not in data and time.time() < deadline:
            os.set_blocking(fd, False)
            try:
                data += os.read(fd, 4096)
            except BlockingIOError:
                time.sleep(0.05)
        return data

    def test_spawn_relays_real_bytes_over_a_local_socketpair_fd(self):
        master_fd, handle = host_bridge_client.spawn(
            [sys.executable, "-c", "import sys; sys.stdout.write('hello-from-host\\n'); sys.stdout.flush()"],
            str(self.tmp.name),
        )
        self.assertIsNotNone(master_fd)
        try:
            data = self._read_until(master_fd, b"hello-from-host")
            self.assertIn(b"hello-from-host", data)
            handle.wait(timeout=2)
            self.assertEqual(handle.poll(), 0)
        finally:
            os.close(master_fd)
            handle.close()

    def test_a_session_idle_past_the_control_connections_timeout_stays_alive(self):
        # Regression: _connect()'s 5s timeout is right for a one-shot control
        # call, but spawn() reuses that connection as the long-lived relay —
        # verified live, without resetting it to blocking, a terminal just
        # sitting idle (completely normal) tore the whole session down once
        # 5s passed with no new output, even though the real process was fine.
        master_fd, handle = host_bridge_client.spawn(
            [sys.executable, "-u", "-c",
             "import sys, time\nsys.stdout.write('first\\n'); sys.stdout.flush()\ntime.sleep(6)\nsys.stdout.write('second\\n'); sys.stdout.flush()\ntime.sleep(2)"],
            str(self.tmp.name),
        )
        self.assertIsNotNone(master_fd)
        try:
            data = self._read_until(master_fd, b"first")
            self.assertIn(b"first", data)
            # Now nothing arrives for 6s (longer than the old 5s timeout) —
            # the connection must still be alive and deliver the next line.
            data += self._read_until(master_fd, b"second", deadline_s=10)
            self.assertIn(b"second", data)
            self.assertIsNone(handle.poll())
        finally:
            handle.terminate()
            handle.wait(timeout=2)
            os.close(master_fd)
            handle.close()

    def test_input_written_to_master_fd_reaches_the_real_child(self):
        # cat echoes stdin to stdout; the pty's own line-discipline echo would
        # double it, so disable that and read raw instead of relying on exact
        # byte-for-byte equality against the pty's cooked-mode framing.
        master_fd, handle = host_bridge_client.spawn([sys.executable, "-u", "-c",
            "import sys\nfor line in sys.stdin:\n    sys.stdout.write('got:' + line)\n    sys.stdout.flush()"],
            str(self.tmp.name))
        self.assertIsNotNone(master_fd)
        try:
            os.write(master_fd, b"marco\n")
            data = self._read_until(master_fd, b"got:marco")
            self.assertIn(b"got:marco", data)
        finally:
            handle.terminate()
            handle.wait(timeout=2)
            os.close(master_fd)
            handle.close()

    def test_terminate_actually_kills_the_real_child(self):
        master_fd, handle = host_bridge_client.spawn(
            [sys.executable, "-c", "import time; time.sleep(30)"], str(self.tmp.name),
        )
        self.assertIsNotNone(master_fd)
        try:
            self.assertIsNone(handle.poll())
            handle.terminate()
            handle.wait(timeout=2)
            self.assertEqual(handle.poll(), 0)
        finally:
            os.close(master_fd)
            handle.close()

    def test_resize_reaches_the_real_host_pty(self):
        import fcntl
        import struct
        import termios
        master_fd, handle = host_bridge_client.spawn(
            [sys.executable, "-c", "import time; time.sleep(5)"], str(self.tmp.name),
        )
        self.assertIsNotNone(master_fd)
        try:
            handle.resize(40, 120)
            # Read it back the same way host_bridge.py set it — on the
            # session's real host-side pty, found via its session id.
            with host_bridge.sessions_lock:
                entry = host_bridge.sessions[handle._session]
            packed = fcntl.ioctl(entry["master_fd"], termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0))
            rows, cols = struct.unpack("HHHH", packed)[:2]
            self.assertEqual((rows, cols), (40, 120))
        finally:
            handle.terminate()
            handle.wait(timeout=2)
            os.close(master_fd)
            handle.close()

    def test_poll_signal_wait_on_an_unknown_session_are_treated_as_already_gone(self):
        handle = host_bridge_client.HostProcessHandle("not-a-real-session", None, None)
        self.assertEqual(handle.poll(), 0)
        handle.terminate()  # must not raise
        handle.wait(timeout=1)  # must not raise

    def test_spawn_unreachable_bridge_reports_none_not_an_exception(self):
        with patch.dict(os.environ, {"WMP_HOST_BRIDGE_PORT": "1"}):
            master_fd, handle = host_bridge_client.spawn(["true"], None)
        self.assertIsNone(master_fd)
        self.assertIsNone(handle)


if __name__ == "__main__":
    unittest.main()
