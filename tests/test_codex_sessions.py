from contextlib import closing
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from codex_sessions import find_session

class SessionMatchingTests(unittest.TestCase):
    def test_exact_marker_and_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            with closing(sqlite3.connect(Path(d) / 'state_5.sqlite')) as c:
                c.execute('CREATE TABLE threads (id TEXT, cwd TEXT, first_user_message TEXT)')
                c.executemany('INSERT INTO threads VALUES (?, ?, ?)', [
                    ('other', '/repo', '[other] Work'), ('correct', '/repo', '[unique] Work'),
                    ('wrong-directory', '/elsewhere', '[unique] Work')])
                c.commit()
            self.assertEqual(find_session('[unique]', '/repo', d), 'correct')
            self.assertIsNone(find_session('[missing]', '/repo', d))

    def test_rollout_fallback_and_partial_write(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'sessions'; p.mkdir()
            (p / 'broken.jsonl').write_text('{')
            (p / 'valid.jsonl').write_text('\n'.join(json.dumps(x) for x in [
                {'type':'session_meta', 'payload':{'id':'matched', 'cwd':'/repo'}},
                {'type':'event_msg', 'payload':{'type':'user_message', 'message':'[unique] Work'}}]))
            self.assertEqual(find_session('[unique]', '/repo', d), 'matched')
            self.assertIsNone(find_session('[other]', '/repo', d))

if __name__ == '__main__': unittest.main()
