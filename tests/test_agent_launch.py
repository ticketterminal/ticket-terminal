import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import agent_launch


class AgentExecutableTests(unittest.TestCase):
    """agent_executable resolves against whichever filesystem/PATH the calling
    process lives on — exercised directly here (not through main.py) since it's
    now a plain stdlib function shared by the in-container local spawn path and
    host_bridge.py's host-side resolution."""

    def test_codex_desktop_fallback_without_path(self):
        with patch.dict(agent_launch.os.environ, {}, clear=True), \
             patch.object(agent_launch.shutil, 'which', return_value=None), \
             patch.object(agent_launch.Path, 'is_file', return_value=True), \
             patch.object(agent_launch.os, 'access', return_value=True):
            self.assertEqual(agent_launch.agent_executable('codex'), '/Applications/ChatGPT.app/Contents/Resources/codex')

    def test_explicit_binary_override(self):
        with patch.dict(agent_launch.os.environ, {'WMP_CODEX_BIN': '/custom/codex'}), \
             patch.object(agent_launch.shutil, 'which', return_value='/custom/codex') as which:
            self.assertEqual(agent_launch.agent_executable('codex'), '/custom/codex')
            which.assert_called_once_with('/custom/codex')

    def test_nothing_found_returns_none(self):
        with patch.dict(agent_launch.os.environ, {}, clear=True), \
             patch.object(agent_launch.shutil, 'which', return_value=None), \
             patch.object(agent_launch.Path, 'is_file', return_value=False):
            self.assertIsNone(agent_launch.agent_executable('codex'))
            self.assertIsNone(agent_launch.agent_executable('claude'))  # no desktop-app fallback list for claude


class BuildChildEnvTests(unittest.TestCase):
    def test_strips_claude_and_codex_session_vars_but_keeps_everything_else(self):
        with patch.dict(agent_launch.os.environ, {
            'CLAUDE_FOO': 'x', 'AI_AGENT': 'x', 'CODEX_THREAD_ID': 'x',
            'CODEX_SESSION_ID': 'x', 'CODEX_INTERNAL_ORIGINATOR_OVERRIDE': 'x',
            'CODEX_APP_TOOLS_PIPE_PATH': 'x', 'PATH': '/usr/bin', 'HOME': '/home/x',
        }, clear=True):
            env = agent_launch.build_child_env()
        self.assertEqual(env, {'PATH': '/usr/bin', 'HOME': '/home/x', 'TERM': 'xterm-256color'})

    def test_does_not_override_an_already_set_term(self):
        with patch.dict(agent_launch.os.environ, {'TERM': 'screen'}, clear=True):
            self.assertEqual(agent_launch.build_child_env()['TERM'], 'screen')


if __name__ == '__main__':
    unittest.main()
