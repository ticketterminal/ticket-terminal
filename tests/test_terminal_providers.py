import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import main
from workspace_fixture import TempWorkspaces

class Socket:
    def __init__(self): self.closed = False
    async def accept(self): pass
    async def close(self, **kwargs): self.closed = True
    async def send_text(self, text): pass
    async def send_bytes(self, text): pass
    async def receive(self): return {'type': 'websocket.disconnect'}

class ProviderTests(unittest.TestCase):
    # A temp data root so nothing here can reach the real data/ tree, and so
    # the workspace half of a process key is a known value.
    def setUp(self): self.workspaces = TempWorkspaces().start()

    def tearDown(self):
        main.running_processes.clear()
        self.workspaces.stop()

    def process_key(self, key, provider): return main.process_key_for(key, provider)

    def launch(self, ticket, provider):
        proc = MagicMock(); proc.poll.return_value = None
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'TEST-1': ticket}}), \
             patch.object(main.db, 'update_ticket') as update, \
             patch.object(main, 'agent_executable', side_effect=lambda provider: provider), \
             patch.object(main.pty, 'openpty', return_value=(100, 101)), \
             patch.object(main, '_set_winsize'), patch.object(main.os, 'close'), \
             patch.object(main.subprocess, 'Popen', return_value=proc) as launch:
            asyncio.run(main.terminal_ws(Socket(), 'TEST-1', provider))
            return launch.call_args.args[0], update.call_args_list

    def test_codex_new_and_resume(self):
        command, updates = self.launch({'summary': 'Example'}, 'codex')
        self.assertEqual(command, ['codex'])
        self.assertIn('Work on TEST-1: Example', main.running_processes[self.process_key('TEST-1', 'codex')]['draft'])
        self.assertIn(self.process_key('TEST-1', 'codex'), main.running_processes)
        self.assertTrue(updates)
        main.running_processes.clear()
        command, _ = self.launch({'codexSessionId': 'saved-id'}, 'codex')
        self.assertEqual(command, ['codex', 'resume', 'saved-id'])

    def test_reopen_attaches_to_existing_codex_process(self):
        self.launch({'codexSessionId': 'saved-id'}, 'codex')
        existing = main.running_processes[self.process_key('TEST-1', 'codex')]['proc']
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'TEST-1': {'codexSessionId': 'saved-id'}}}), \
             patch.object(main, 'agent_executable', return_value='codex'), \
             patch.object(main, '_set_winsize'), \
             patch.object(main.subprocess, 'Popen') as launch:
            asyncio.run(main.terminal_ws(Socket(), 'TEST-1', 'codex'))
            launch.assert_not_called()
            self.assertIs(main.running_processes[self.process_key('TEST-1', 'codex')]['proc'], existing)

    def test_claude_preserved(self):
        with patch.object(main, '_claude_session_exists', return_value=True):
            command, _ = self.launch({'claudeSessionId':'claude-id'}, 'claude')
        self.assertEqual(command, ['claude', '--resume', 'claude-id'])
        self.assertIn(self.process_key('TEST-1', 'claude'), main.running_processes)

    def test_codex_desktop_fallback_without_path(self):
        with patch.dict(main.os.environ, {}, clear=True), \
             patch.object(main.shutil, 'which', return_value=None), \
             patch.object(main.Path, 'is_file', return_value=True), \
             patch.object(main.os, 'access', return_value=True):
            self.assertEqual(main.agent_executable('codex'), '/Applications/ChatGPT.app/Contents/Resources/codex')

    def test_explicit_binary_override(self):
        with patch.dict(main.os.environ, {'WMP_CODEX_BIN':'/custom/codex'}), \
             patch.object(main.shutil, 'which', return_value='/custom/codex') as which:
            self.assertEqual(main.agent_executable('codex'), '/custom/codex')
            which.assert_called_once_with('/custom/codex')

    def test_invalid_provider_does_not_spawn(self):
        with patch.object(main.subprocess, 'Popen') as launch:
            ws = Socket()
            asyncio.run(main.terminal_ws(ws, 'TEST-1', 'shell'))
            launch.assert_not_called()
            self.assertTrue(ws.closed)

    def test_costs_keep_both_providers(self):
        with patch.object(main.db, 'read', return_value={'jiraTickets':{'TEST-1':{'claudeSessionId':'a','codexSessionId':'b'}}}), \
             patch.object(main.cost_analysis, 'get_session_costs', return_value={'a':{'cost':1}, 'b':{'cost':2}}):
            result = main.get_ticket_costs()['costs']
            self.assertEqual(result['claude:TEST-1']['cost'], 1)
            self.assertEqual(result['codex:TEST-1']['cost'], 2)

if __name__ == '__main__': unittest.main()
