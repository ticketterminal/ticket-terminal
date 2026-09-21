import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from terminal_draft import draft_when_ready

class DraftTests(unittest.TestCase):
    def test_waits_for_composer_and_never_submits(self):
        state = {'draft': 'Ticket summary\nURL'}
        self.assertIsNone(draft_when_ready(state, b'\x1b[?2004h Trust this directory?'))
        self.assertIsNone(draft_when_ready(state, b'? for short'))
        result = draft_when_ready(state, b'cuts')
        self.assertEqual(result, b'\x1b[200~Ticket summary\nURL\x1b[201~')
        self.assertIsNone(draft_when_ready(state, b'? for shortcuts'))

    def test_resume_has_no_new_draft(self):
        self.assertIsNone(draft_when_ready({}, b'? for shortcuts'))

    def test_cannot_break_out_of_bracketed_paste(self):
        result = draft_when_ready({'draft':'Text\x1b[201~\r'}, b'? for shortcuts')
        self.assertEqual(result.count(b'\x1b[201~'), 1)
        self.assertNotIn(b'\r', result)
