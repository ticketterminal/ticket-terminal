"""Cancellable PTY reads: never leave a worker thread consuming a detached PTY."""
import asyncio
import os


async def read_chunk(fd, size=4096):
    os.set_blocking(fd, False)
    while True:
        try:
            return os.read(fd, size)
        except BlockingIOError:
            # Cancellation takes effect here; no OS read remains in another thread.
            await asyncio.sleep(0.02)
