"""_live_spend_entries: the bridge between a still-running background process and
workflow_insights, so Insights reflects real ongoing work instead of only sessions someone
remembered to click Stop on. See main.py's docstring on the function itself for why this
exists at all."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import db
import main
from workspace_fixture import TempWorkspaces


def cost_row(session_id, cost=0.42, **extra):
    row = {
        'sessionId': session_id, 'models': ['Sonnet 5'], 'cost': cost, 'calls': 3, 'turns': 1,
        'inputTokens': 100, 'outputTokens': 200, 'cacheReadTokens': 50, 'cacheWriteTokens': 10,
        'durationMs': 300000,
    }
    row.update(extra)
    return row


class LiveSpendEntriesTests(unittest.TestCase):
    def setUp(self):
        self.workspaces = TempWorkspaces().start()
        db.write({'jiraTickets': {
            'T-1': {'key': 'T-1', 'categories': ['bugs'], 'jiraPriority': 'High', 'claudeSessionId': 'sess-1'},
            'T-2': {'key': 'T-2', 'categories': ['infra'], 'jiraPriority': 'Low', 'codexSessionId': 'sess-2'},
        }, 'people': {}, 'teamOptions': []})

    def tearDown(self):
        main.running_processes.clear()
        self.workspaces.stop()

    def track(self, key, provider):
        main.running_processes[main.process_key_for(key, provider)] = {'proc': None}

    def test_no_running_processes_means_no_live_entries(self):
        self.assertEqual(main._live_spend_entries(), [])

    def test_one_entry_per_running_process_with_ticket_context(self):
        self.track('T-1', 'claude')
        with patch.object(main.cost_analysis, 'get_session_costs', return_value={'sess-1': cost_row('sess-1', cost=1.5)}):
            entries = main._live_spend_entries()
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e['ticketKey'], 'T-1')
        self.assertEqual(e['provider'], 'claude')
        self.assertEqual(e['sessionId'], 'sess-1')
        self.assertEqual(e['cost'], 1.5)
        self.assertEqual(e['categories'], ['bugs'])
        self.assertEqual(e['priority'], 'High')

    def test_covers_both_providers_on_different_tickets(self):
        self.track('T-1', 'claude')
        self.track('T-2', 'codex')
        with patch.object(main.cost_analysis, 'get_session_costs', return_value={
            'sess-1': cost_row('sess-1'), 'sess-2': cost_row('sess-2'),
        }):
            entries = main._live_spend_entries()
        self.assertEqual({e['ticketKey'] for e in entries}, {'T-1', 'T-2'})

    def test_skips_a_process_codeburn_has_no_row_for_yet(self):
        self.track('T-1', 'claude')
        with patch.object(main.cost_analysis, 'get_session_costs', return_value={}):
            self.assertEqual(main._live_spend_entries(), [])

    def test_never_raises_when_codeburn_itself_fails(self):
        self.track('T-1', 'claude')
        with patch.object(main.cost_analysis, 'get_session_costs', side_effect=RuntimeError('boom')):
            self.assertEqual(main._live_spend_entries(), [])

    def test_a_process_in_another_workspace_is_invisible_here(self):
        main.running_processes['someother|claude|T-9'] = {'proc': None}
        with patch.object(main.cost_analysis, 'get_session_costs', return_value={'sess-1': cost_row('sess-1')}):
            entries = main._live_spend_entries()
        self.assertEqual(entries, [])


if __name__ == '__main__':
    unittest.main()
