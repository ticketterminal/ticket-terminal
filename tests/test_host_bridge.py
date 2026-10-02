"""Real (not mocked) end-to-end test of the host<->container bridge: runs
host_bridge.py's actual connection handler against a temp Unix socket in this
same test process, and drives host_bridge_client (the side server/main.py
uses) against it — genuine SCM_RIGHTS fd-passing and genuine subprocess
spawning, no Docker required, since fd-passing works fine between any two
sockets on the same machine, even within one process via a temp socket file.
"""
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


class HostBridgeEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.socket_path = Path(self.tmp.name) / "bridge.sock"
        self.env_patch = patch.dict(os.environ, {"WMP_HOST_BRIDGE_SOCKET": str(self.socket_path)})
        self.env_patch.start()

        self.server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_sock.bind(str(self.socket_path))
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

    def tearDown(self):
        self.stopping = True
        self.accept_thread.join(timeout=2)
        self.server_sock.close()
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_available_is_true_once_the_bridge_is_listening(self):
        self.assertTrue(host_bridge_client.available())

    def test_available_is_false_against_a_dead_socket_path(self):
        with patch.dict(os.environ, {"WMP_HOST_BRIDGE_SOCKET": str(Path(self.tmp.name) / "nothing-here.sock")}):
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

    def test_spawn_hands_over_a_real_usable_pty_fd(self):
        master_fd, handle = host_bridge_client.spawn(
            [sys.executable, "-c", "import sys; sys.stdout.write('hello-from-host\\n'); sys.stdout.flush()"],
            str(self.tmp.name),
        )
        self.assertIsNotNone(master_fd)
        try:
            deadline = time.time() + 5
            data = b""
            while b"hello-from-host" not in data and time.time() < deadline:
                os.set_blocking(master_fd, False)
                try:
                    data += os.read(master_fd, 4096)
                except BlockingIOError:
                    time.sleep(0.05)
            self.assertIn(b"hello-from-host", data)
            handle.wait(timeout=2)
            self.assertEqual(handle.poll(), 0)
        finally:
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

    def test_spawn_unreachable_bridge_reports_none_not_an_exception(self):
        with patch.dict(os.environ, {"WMP_HOST_BRIDGE_SOCKET": str(Path(self.tmp.name) / "nothing-here.sock")}):
            master_fd, handle = host_bridge_client.spawn(["true"], None)
        self.assertIsNone(master_fd)
        self.assertIsNone(handle)


if __name__ == "__main__":
    unittest.main()
