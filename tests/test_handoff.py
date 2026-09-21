import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import main
from workspace_fixture import TempWorkspaces


class Socket:
    def __init__(self): self.closed = False; self.sent_text = []
    async def accept(self): pass
    async def close(self, **kwargs): self.closed = True
    async def send_text(self, text): self.sent_text.append(text)
    async def send_bytes(self, text): pass
    async def receive(self): return {'type': 'websocket.disconnect'}


class HandoffEndpointTests(unittest.TestCase):
    def setUp(self): self.workspaces = TempWorkspaces().start()

    def tearDown(self):
        main.running_processes.clear()
        self.workspaces.stop()

    def test_unknown_provider_rejected(self):
        result = asyncio.run(main.handoff_session('T-1', 'shell'))
        self.assertEqual(result, {'ok': False, 'error': 'unknown provider'})

    def test_no_such_ticket(self):
        with patch.object(main.db, 'read', return_value={'jiraTickets': {}}):
            result = asyncio.run(main.handoff_session('T-1', 'claude'))
        self.assertFalse(result['ok'])

    def test_claude_requires_a_session_id(self):
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'T-1': {}}}), \
             patch.object(main, 'agent_executable', return_value='claude'):
            result = asyncio.run(main.handoff_session('T-1', 'claude'))
        self.assertFalse(result['ok'])
        self.assertIn('no Claude session', result['error'])

    def test_claude_returns_the_resume_deep_link(self):
        # Verified live (2026-09-18): claude://resume?session=<id> is what
        # actually opens the right conversation in the real Claude app.
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'T-1': {'claudeSessionId': 'sess-1'}}}), \
             patch.object(main, 'agent_executable', return_value='claude'):
            result = asyncio.run(main.handoff_session('T-1', 'claude'))
        self.assertEqual(result, {'ok': True, 'url': 'claude://resume?session=sess-1'})

    def test_claude_kills_a_live_tracked_process_first(self):
        proc = MagicMock(); proc.poll.return_value = None
        key = main.process_key_for('T-1', 'claude')
        main.running_processes[key] = {'proc': proc, 'master_fd': 999}
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'T-1': {'claudeSessionId': 'sess-1'}}}), \
             patch.object(main.db, 'update_ticket'), \
             patch.object(main, 'agent_executable', return_value='claude'), \
             patch.object(main.os, 'close') as close, \
             patch.object(main.spend_ledger, 'append_entry') as append_entry:
            asyncio.run(main.handoff_session('T-1', 'claude'))
        proc.terminate.assert_called_once()
        close.assert_called_once_with(999)
        self.assertNotIn(key, main.running_processes)
        append_entry.assert_called_once()
        self.assertEqual(append_entry.call_args.args[-1], 'handed-off')

    def test_never_raises_when_something_blows_up(self):
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'T-1': {'claudeSessionId': 'sess-1'}}}), \
             patch.object(main, 'agent_executable', side_effect=RuntimeError('boom')):
            result = asyncio.run(main.handoff_session('T-1', 'claude'))
        self.assertFalse(result['ok'])
        self.assertIn('boom', result['error'])

    def test_codex_opens_the_app_at_the_ticket_workdir(self):
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'T-1': {'workDir': '/tmp'}}}), \
             patch.object(main.db, 'update_ticket') as update, \
             patch.object(main, 'agent_executable', return_value='codex'), \
             patch.object(main.os.path, 'isdir', return_value=True), \
             patch.object(main.subprocess, 'Popen') as popen:
            result = asyncio.run(main.handoff_session('T-1', 'codex'))
        self.assertEqual(result, {'ok': True, 'opened': True})
        popen.assert_called_once_with(['codex', 'app', '/tmp'], cwd='/tmp')
        self.assertEqual(update.call_args.args[0], 'T-1')
        self.assertIn('codexHandedOffAt', update.call_args.args[1])

    def test_codex_does_not_require_an_existing_session(self):
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'T-1': {}}}), \
             patch.object(main.db, 'update_ticket'), \
             patch.object(main, 'agent_executable', return_value='codex'), \
             patch.object(main.subprocess, 'Popen') as popen:
            result = asyncio.run(main.handoff_session('T-1', 'codex'))
        self.assertTrue(result['ok'])
        popen.assert_called_once()


class ReconnectAfterHandoffTests(unittest.TestCase):
    """Claude needs no check here at all: /handoff forks a one-time copy and
    never touches the ticket's real session (see handoff_session's
    docstring), so reconnecting is always as safe as any other reconnect.
    Codex is different — its /handoff opens a real, shared-store app session
    Ticket Terminal can't release, so the one thing to verify is the soft
    warning terminal_ws shows instead."""

    def setUp(self): self.workspaces = TempWorkspaces().start()

    def tearDown(self):
        main.running_processes.clear()
        self.workspaces.stop()

    def launch(self, ticket, provider):
        proc = MagicMock(); proc.poll.return_value = None
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'TEST-1': ticket}}), \
             patch.object(main.db, 'update_ticket') as update, \
             patch.object(main, 'agent_executable', side_effect=lambda provider: provider), \
             patch.object(main.pty, 'openpty', return_value=(100, 101)), \
             patch.object(main, '_set_winsize'), patch.object(main.os, 'close'), \
             patch.object(main.subprocess, 'Popen', return_value=proc):
            socket = Socket()
            asyncio.run(main.terminal_ws(socket, 'TEST-1', provider))
            return update.call_args_list, socket

    def test_codex_handoff_warning_is_shown_once_then_cleared(self):
        updates, socket = self.launch(
            {'codexSessionId': 'sess-1', 'codexHandedOffAt': '2026-09-18T00:00:00+00:00'}, 'codex')
        self.assertTrue(any('ChatGPT app' in t for t in socket.sent_text))
        self.assertTrue(any(u.args == ('TEST-1', {'codexHandedOffAt': None}) for u in updates))

    def test_claude_reconnect_is_unaffected_by_a_prior_handoff(self):
        with patch.object(main, '_claude_session_exists', return_value=True):
            _, socket = self.launch({'claudeSessionId': 'sess-1'}, 'claude')
        self.assertEqual(socket.sent_text, [])


if __name__ == '__main__':
    unittest.main()
