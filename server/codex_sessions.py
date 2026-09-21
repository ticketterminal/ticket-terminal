"""Associate a CLI-created session with a ticket by its unique opening prompt.

Codex chooses its own UUID. Never guess using the latest session in a cwd:
other tickets and desktop sessions can use that same directory concurrently.
The local index is read-only; rollout scanning supports older CLI installs.
"""
from contextlib import closing
import json
import os
import sqlite3
from pathlib import Path


def find_session(marker, cwd, home=None):
    home = Path(home or os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    for path in sorted(home.glob('state_*.sqlite'), reverse=True):
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)) as conn:
                rows = conn.execute(
                    'SELECT id FROM threads WHERE cwd = ? AND instr(first_user_message, ?) = 1',
                    (cwd, marker),
                ).fetchall()
            if len(rows) == 1:
                return rows[0][0]
        except sqlite3.Error:
            continue
    for path in (home / 'sessions').glob('**/*.jsonl'):
        try:
            with path.open() as f:
                meta = json.loads(next(f)).get('payload', {})
                if meta.get('cwd') != cwd:
                    continue
                for line in f:
                    event = json.loads(line)
                    payload = event.get('payload', {})
                    if event.get('type') == 'event_msg' and payload.get('type') == 'user_message':
                        if payload.get('message', '').startswith(marker):
                            return meta.get('id') or meta.get('session_id')
                        break
        except (OSError, ValueError, StopIteration):
            continue
    return None
