import asyncio
import os
import pty
import sys
import tty
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from pty_io import read_chunk

class ReconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_detached_reader_cannot_steal_reconnect_output(self):
        master, slave = pty.openpty()
        tty.setraw(slave)
        try:
            for _ in range(3):
                old_reader = asyncio.create_task(read_chunk(master))
                await asyncio.sleep(0.04)
                old_reader.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await old_reader
            new_reader = asyncio.create_task(read_chunk(master))
            os.write(slave, b'resumed session screen')
            self.assertEqual(await asyncio.wait_for(new_reader, 1), b'resumed session screen')
        finally:
            os.close(master)
            os.close(slave)
