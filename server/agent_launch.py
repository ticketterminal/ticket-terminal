"""Pure-stdlib pieces of spawning an agent CLI in a PTY — no FastAPI/uvicorn/etc.

Split out of main.py so `host_bridge.py` (which runs standalone on the host, outside
Docker, with no pip install step of its own) can import exactly this and nothing
else. Both the in-container local-spawn path (server/main.py) and the host bridge
use these same three functions, so there is only one place that knows how to find
or launch an agent CLI.
"""
import fcntl
import os
import shutil
import struct
import termios
from pathlib import Path


def set_winsize(fd, rows, cols):
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


def pty_child_preexec():
    """Set up the child as a proper terminal session before exec.

    `os.setsid()` alone is NOT enough, and this was a real bug for a long time:
    it makes the child a session leader with *no controlling terminal*, because
    the PTY slave was opened here in the parent — the child only inherits the
    fd, it never `open()`s the terminal itself, which is what would implicitly
    claim it. With no controlling terminal there is no foreground process group
    for that terminal, so the kernel has nowhere to deliver SIGWINCH when we
    resize the master. The TUI therefore never learns the window changed and
    never repaints, which is what made a reconnected terminal sit blank
    forever (see the reconnect nudge in terminal_ws).

    TIOCSCTTY on fd 0 claims the slave as this session's controlling terminal.
    fd 0 is the slave: preexec_fn runs after Popen has dup2'd it onto stdin.
    As a bonus this also makes job control work properly — SIGINT/SIGWINCH now
    reach the process group the way they would in a real terminal.
    """
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def build_child_env():
    """The environment an agent CLI child should run with — a copy of whichever
    process calls this (the container's for a local spawn, the host bridge's own
    for a bridged one), minus the vars that would make it think it's already
    inside a session it isn't."""
    child_env = os.environ.copy()
    for k in list(child_env):
        if k.startswith("CLAUDE") or k in {"AI_AGENT", "CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "CODEX_APP_TOOLS_PIPE_PATH"}:
            del child_env[k]
    child_env.setdefault("TERM", "xterm-256color")
    return child_env


def agent_executable(provider):
    """Resolve once for both availability and launch, including desktop installs.

    Runs against whichever filesystem/PATH the caller lives on — the container's
    when called in-container, the host's own when called from host_bridge.py."""
    override = os.environ.get("WMP_" + provider.upper() + "_BIN")
    if override:
        return shutil.which(os.path.expanduser(override))
    found = shutil.which(provider)
    if found:
        return found
    if provider == "codex":
        candidates = [
            Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
            Path("/Applications/Codex.app/Contents/Resources/codex"),
            Path.home() / "Applications/ChatGPT.app/Contents/Resources/codex",
            Path.home() / "Applications/Codex.app/Contents/Resources/codex",
            Path("/opt/homebrew/bin/codex"),
            Path("/usr/local/bin/codex"),
            Path.home() / ".local/bin/codex",
        ]
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None
