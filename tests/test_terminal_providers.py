import asyncio
import json
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

class ResizeThenDisconnectSocket(Socket):
    """Sends one live "resize" message before disconnecting, to exercise the
    kind == "resize" branch inside terminal_ws's own receive loop — Socket's
    own immediate-disconnect means that branch never runs otherwise."""
    def __init__(self, rows, cols):
        super().__init__()
        self._messages = [{'type': 'websocket.receive', 'text': json.dumps({'type': 'resize', 'rows': rows, 'cols': cols})}]
    async def receive(self):
        if self._messages:
            return self._messages.pop(0)
        return {'type': 'websocket.disconnect'}

class SubmitThenDisconnectSocket(Socket):
    """Submit one prompt so the activity tracker can distinguish a real turn
    from the CLI's startup and resize redraws."""
    def __init__(self):
        super().__init__()
        self._messages = [{'type': 'websocket.receive', 'text': json.dumps({'type': 'input', 'data': '\r'})}]
    async def receive(self):
        if self._messages:
            return self._messages.pop(0)
        return {'type': 'websocket.disconnect'}

class ProviderTests(unittest.TestCase):
    # A temp data root so nothing here can reach the real data/ tree, and so
    # the workspace half of a process key is a known value.
    def setUp(self): self.workspaces = TempWorkspaces().start()

    def tearDown(self):
        main.running_processes.clear()
        self.workspaces.stop()

    def process_key(self, key, provider): return main.process_key_for(key, provider)

    def launch(self, ticket, provider, codex_supports_no_daemon=True):
        proc = MagicMock(); proc.poll.return_value = None
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'TEST-1': ticket}}), \
             patch.object(main.db, 'update_ticket') as update, \
             patch.object(main, '_resolve_agent', side_effect=lambda provider: (provider, False)), \
             patch.object(main, '_codex_supports_no_daemon', return_value=codex_supports_no_daemon), \
             patch.object(main.pty, 'openpty', return_value=(100, 101)), \
             patch.object(main.agent_launch, 'set_winsize'), patch.object(main.os, 'close'), \
             patch.object(main.subprocess, 'Popen', return_value=proc) as launch:
            asyncio.run(main.terminal_ws(Socket(), 'TEST-1', provider))
            return launch.call_args.args[0], update.call_args_list

    def test_codex_new_and_resume(self):
        command, updates = self.launch({'summary': 'Example'}, 'codex')
        self.assertEqual(command, ['codex', '--no-daemon'])
        self.assertIn('Work on TEST-1: Example', main.running_processes[self.process_key('TEST-1', 'codex')]['draft'])
        self.assertIn(self.process_key('TEST-1', 'codex'), main.running_processes)
        self.assertTrue(updates)
        main.running_processes.clear()
        command, _ = self.launch({'codexSessionId': 'saved-id'}, 'codex')
        self.assertEqual(command, ['codex', '--no-daemon', 'resume', 'saved-id'])

    def test_codex_omits_no_daemon_when_local_binary_does_not_support_it(self):
        # The exact bug this guards against: a genuine native/non-Docker install
        # takes this same local (non-bridged) spawn path, and a newer codex
        # release there hard-errors on --no-daemon ("unexpected argument
        # '--no-daemon' found") rather than merely ignoring it.
        command, _ = self.launch({'summary': 'Example'}, 'codex', codex_supports_no_daemon=False)
        self.assertEqual(command, ['codex'])
        main.running_processes.clear()
        command, _ = self.launch({'codexSessionId': 'saved-id'}, 'codex', codex_supports_no_daemon=False)
        self.assertEqual(command, ['codex', 'resume', 'saved-id'])

    def test_reopen_attaches_to_existing_codex_process(self):
        self.launch({'codexSessionId': 'saved-id'}, 'codex')
        existing = main.running_processes[self.process_key('TEST-1', 'codex')]['proc']
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'TEST-1': {'codexSessionId': 'saved-id'}}}), \
             patch.object(main, '_resolve_agent', return_value=('codex', False)), \
             patch.object(main.agent_launch, 'set_winsize'), \
             patch.object(main.subprocess, 'Popen') as launch:
            asyncio.run(main.terminal_ws(Socket(), 'TEST-1', 'codex'))
            launch.assert_not_called()
            self.assertIs(main.running_processes[self.process_key('TEST-1', 'codex')]['proc'], existing)

    def test_claude_preserved(self):
        with patch.object(main, '_claude_session_exists', return_value=True):
            command, _ = self.launch({'claudeSessionId':'claude-id'}, 'claude')
        self.assertEqual(command, ['claude', '--resume', 'claude-id'])
        self.assertIn(self.process_key('TEST-1', 'claude'), main.running_processes)

    def test_bridged_spawn_never_falls_back_to_a_local_popen(self):
        proc = MagicMock(); proc.poll.return_value = None
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'TEST-1': {'summary': 'Example'}}}), \
             patch.object(main.db, 'update_ticket'), \
             patch.object(main, '_resolve_agent', return_value=('/host/codex', True)), \
             patch.object(main.host_bridge_client, 'spawn', return_value=(42, proc)) as spawn, \
             patch.object(main.subprocess, 'Popen') as popen:
            asyncio.run(main.terminal_ws(Socket(), 'TEST-1', 'codex'))
        spawn.assert_called_once()
        # No --no-daemon for a bridged (host-native) codex: that flag only
        # works around the container build's missing `ps`, and newer codex
        # releases installed on a real host don't even recognize it.
        self.assertEqual(spawn.call_args.args[0], ['/host/codex'])
        popen.assert_not_called()
        entry = main.running_processes[self.process_key('TEST-1', 'codex')]
        self.assertEqual(entry['master_fd'], 42)
        self.assertIs(entry['proc'], proc)

    def test_bridged_codex_resume_also_drops_no_daemon(self):
        proc = MagicMock(); proc.poll.return_value = None
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'TEST-1': {'codexSessionId': 'saved-id'}}}), \
             patch.object(main.db, 'update_ticket'), \
             patch.object(main, '_resolve_agent', return_value=('/host/codex', True)), \
             patch.object(main.host_bridge_client, 'spawn', return_value=(42, proc)) as spawn, \
             patch.object(main.subprocess, 'Popen') as popen:
            asyncio.run(main.terminal_ws(Socket(), 'TEST-1', 'codex'))
        self.assertEqual(spawn.call_args.args[0], ['/host/codex', 'resume', 'saved-id'])
        popen.assert_not_called()

    def test_bridged_spawn_failing_mid_session_raises_rather_than_silently_going_local(self):
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'TEST-1': {'summary': 'Example'}}}), \
             patch.object(main.db, 'update_ticket'), \
             patch.object(main, '_resolve_agent', return_value=('/host/codex', True)), \
             patch.object(main.host_bridge_client, 'spawn', return_value=(None, None)), \
             patch.object(main.subprocess, 'Popen') as popen:
            with self.assertRaises(RuntimeError):
                asyncio.run(main.terminal_ws(Socket(), 'TEST-1', 'codex'))
        popen.assert_not_called()

    def test_stopping_a_bridged_session_closes_its_control_connection(self):
        proc = MagicMock(); proc.poll.return_value = None
        key = main.process_key_for('TEST-1', 'codex')
        main.running_processes[key] = {'proc': proc, 'master_fd': 999}
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'TEST-1': {}}}), \
             patch.object(main.os, 'close'):
            main._terminate_process(key, main.running_processes[key], 'stopped')
        proc.close.assert_called_once()

    def test_stopping_a_local_session_does_not_look_for_close(self):
        # A plain subprocess.Popen has no .close() — MagicMock(spec=...) makes
        # this fail loudly if _terminate_process ever assumed one existed.
        import subprocess as subprocess_module
        proc = MagicMock(spec=subprocess_module.Popen)
        proc.poll.return_value = None
        key = main.process_key_for('TEST-1', 'claude')
        main.running_processes[key] = {'proc': proc, 'master_fd': 999}
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'TEST-1': {}}}), \
             patch.object(main.os, 'close'):
            main._terminate_process(key, main.running_processes[key], 'stopped')  # must not raise
        proc.terminate.assert_called_once()

    def test_local_session_resize_goes_through_agent_launch_set_winsize(self):
        proc = MagicMock(); proc.poll.return_value = None
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'TEST-1': {'summary': 'Example'}}}), \
             patch.object(main.db, 'update_ticket'), \
             patch.object(main, '_resolve_agent', return_value=('codex', False)), \
             patch.object(main, '_codex_supports_no_daemon', return_value=True), \
             patch.object(main.pty, 'openpty', return_value=(100, 101)), \
             patch.object(main.os, 'close'), \
             patch.object(main.agent_launch, 'set_winsize') as set_winsize, \
             patch.object(main.subprocess, 'Popen', return_value=proc):
            asyncio.run(main.terminal_ws(ResizeThenDisconnectSocket(40, 120), 'TEST-1', 'codex'))
        # Once for the initial open (30, 100), once for the live resize message.
        set_winsize.assert_called_with(100, 40, 120)

    def test_submitting_a_prompt_arms_activity_but_opening_alone_does_not(self):
        self.launch({'codexSessionId': 'saved-id'}, 'codex')
        self.assertFalse(main.running_processes[self.process_key('TEST-1', 'codex')].get('activity_armed', False))
        main.running_processes.clear()
        proc = MagicMock(); proc.poll.return_value = None
        patches = (
            patch.object(main.db, 'read', return_value={'jiraTickets': {'TEST-1': {'codexSessionId': 'saved-id'}}}),
            patch.object(main, '_resolve_agent', return_value=('codex', False)),
            patch.object(main, '_codex_supports_no_daemon', return_value=False),
            patch.object(main.pty, 'openpty', return_value=(100, 101)),
            patch.object(main.os, 'close'), patch.object(main.os, 'write'),
            patch.object(main.agent_launch, 'set_winsize'),
            patch.object(main.subprocess, 'Popen', return_value=proc),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            asyncio.run(main.terminal_ws(SubmitThenDisconnectSocket(), 'TEST-1', 'codex'))
        self.assertTrue(main.running_processes[self.process_key('TEST-1', 'codex')]['activity_armed'])

    def test_bridged_session_resize_goes_through_the_handles_resize_method(self):
        proc = MagicMock(); proc.poll.return_value = None
        with patch.object(main.db, 'read', return_value={'jiraTickets': {'TEST-1': {'summary': 'Example'}}}), \
             patch.object(main.db, 'update_ticket'), \
             patch.object(main, '_resolve_agent', return_value=('/host/codex', True)), \
             patch.object(main.host_bridge_client, 'spawn', return_value=(42, proc)), \
             patch.object(main.subprocess, 'Popen') as popen:
            asyncio.run(main.terminal_ws(ResizeThenDisconnectSocket(40, 120), 'TEST-1', 'codex'))
        popen.assert_not_called()
        proc.resize.assert_called_once_with(40, 120)

    def test_invalid_provider_does_not_spawn(self):
        with patch.object(main.subprocess, 'Popen') as launch:
            ws = Socket()
            asyncio.run(main.terminal_ws(ws, 'TEST-1', 'shell'))
            launch.assert_not_called()
            self.assertTrue(ws.closed)

    def test_codex_supports_no_daemon_reads_the_real_help_text(self):
        main._codex_supports_no_daemon.cache_clear()
        with patch.object(main.subprocess, 'run', return_value=MagicMock(stdout='Usage: codex [OPTIONS]\n  --no-daemon  ...')):
            self.assertTrue(main._codex_supports_no_daemon('/some/codex'))
        main._codex_supports_no_daemon.cache_clear()
        with patch.object(main.subprocess, 'run', return_value=MagicMock(stdout='Usage: codex [OPTIONS]\n  --no-persist  ...')):
            self.assertFalse(main._codex_supports_no_daemon('/some/other/codex'))

    def test_codex_supports_no_daemon_defaults_false_if_the_binary_cannot_run(self):
        main._codex_supports_no_daemon.cache_clear()
        with patch.object(main.subprocess, 'run', side_effect=FileNotFoundError()):
            self.assertFalse(main._codex_supports_no_daemon('/missing/codex'))
        main._codex_supports_no_daemon.cache_clear()

    def test_costs_keep_both_providers(self):
        with patch.object(main.db, 'read', return_value={'jiraTickets':{'TEST-1':{'claudeSessionId':'a','codexSessionId':'b'}}}), \
             patch.object(main.cost_analysis, 'get_session_costs', return_value={'a':{'cost':1}, 'b':{'cost':2}}):
            result = main.get_ticket_costs()['costs']
            self.assertEqual(result['claude:TEST-1']['cost'], 1)
            self.assertEqual(result['codex:TEST-1']['cost'], 2)

if __name__ == '__main__': unittest.main()
