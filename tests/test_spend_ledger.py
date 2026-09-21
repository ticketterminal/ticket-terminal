import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import db
import spend_ledger
import workspaces
from workspace_fixture import TempWorkspaces


def cost_row(session_id, cost=0.42, **extra):
    row = {
        'sessionId': session_id, 'models': ['Sonnet 5'], 'cost': cost, 'calls': 3, 'turns': 1,
        'inputTokens': 100, 'outputTokens': 200, 'cacheReadTokens': 50, 'cacheWriteTokens': 10,
        'startedAt': '2026-09-01T00:00:00Z', 'endedAt': '2026-09-01T00:05:00Z', 'durationMs': 300000,
    }
    row.update(extra)
    return row


class SpendLedgerTests(unittest.TestCase):
    def setUp(self):
        self.workspaces = TempWorkspaces().start()
        db.write({'jiraTickets': {
            'T-1': {'key': 'T-1', 'categories': ['bugs'], 'jiraPriority': 'High', 'claudeSessionId': 'sess-1'},
        }, 'people': {}, 'teamOptions': []})

    def tearDown(self):
        self.workspaces.stop()

    def ticket(self, key='T-1'):
        return db.read()['jiraTickets'][key]

    def test_append_entry_records_cost_and_ticket_context(self):
        with patch.object(spend_ledger.cost_analysis, 'get_session_costs', return_value={'sess-1': cost_row('sess-1')}):
            spend_ledger.append_entry('T-1', 'claude', 'sess-1', self.ticket(), 'stopped')
        entries = spend_ledger.read_entries()
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e['ticketKey'], 'T-1')
        self.assertEqual(e['provider'], 'claude')
        self.assertEqual(e['sessionId'], 'sess-1')
        self.assertEqual(e['cost'], 0.42)
        self.assertEqual(e['categories'], ['bugs'])
        self.assertEqual(e['priority'], 'High')
        self.assertEqual(e['closeReason'], 'stopped')

    def test_append_entry_is_idempotent_on_session_id(self):
        with patch.object(spend_ledger.cost_analysis, 'get_session_costs', return_value={'sess-1': cost_row('sess-1')}):
            spend_ledger.append_entry('T-1', 'claude', 'sess-1', self.ticket(), 'stopped')
            # Both main.py hook points could fire for the same session — must not double-record.
            spend_ledger.append_entry('T-1', 'claude', 'sess-1', self.ticket(), 'process-exited')
        self.assertEqual(len(spend_ledger.read_entries()), 1)

    def test_append_entry_no_op_when_costs_dont_have_this_session(self):
        with patch.object(spend_ledger.cost_analysis, 'get_session_costs', return_value={}):
            spend_ledger.append_entry('T-1', 'claude', 'sess-1', self.ticket(), 'stopped')
        self.assertEqual(spend_ledger.read_entries(), [])

    def test_append_entry_no_op_without_session_id(self):
        spend_ledger.append_entry('T-1', 'claude', None, self.ticket(), 'stopped')
        self.assertEqual(spend_ledger.read_entries(), [])

    def test_append_entry_never_raises_when_codeburn_fails(self):
        with patch.object(spend_ledger.cost_analysis, 'get_session_costs', side_effect=RuntimeError('codeburn exploded')):
            spend_ledger.append_entry('T-1', 'claude', 'sess-1', self.ticket(), 'stopped')
        self.assertEqual(spend_ledger.read_entries(), [])

    def test_survives_a_session_id_swap_on_the_ticket(self):
        with patch.object(spend_ledger.cost_analysis, 'get_session_costs', return_value={'sess-1': cost_row('sess-1')}):
            spend_ledger.append_entry('T-1', 'claude', 'sess-1', self.ticket(), 'stopped')
        # main.py mints a fresh session id once it decides the old one is dead/unresumable.
        db.update_ticket('T-1', {'claudeSessionId': 'sess-2'})
        with patch.object(spend_ledger.cost_analysis, 'get_session_costs', return_value={'sess-2': cost_row('sess-2', cost=0.10)}):
            spend_ledger.append_entry('T-1', 'claude', 'sess-2', self.ticket(), 'stopped')
        entries = spend_ledger.read_entries()
        self.assertEqual(sorted(e['sessionId'] for e in entries), ['sess-1', 'sess-2'])

    def test_workspace_scoped(self):
        self.workspaces.register('other')
        with patch.object(spend_ledger.cost_analysis, 'get_session_costs', return_value={'sess-1': cost_row('sess-1')}):
            spend_ledger.append_entry('T-1', 'claude', 'sess-1', self.ticket(), 'stopped')
        self.assertEqual(len(spend_ledger.read_entries()), 1)
        with workspaces.use('other'):
            self.assertEqual(spend_ledger.read_entries(), [])


if __name__ == '__main__':
    unittest.main()
