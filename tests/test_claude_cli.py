import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import auto_categorize
import claude_cli
import content


class Completed:
    def __init__(self, stdout, returncode=0):
        self.stdout, self.returncode, self.stderr = stdout, returncode, ''


class ClaudeCliTests(unittest.TestCase):
    def test_command_has_no_retired_flags(self):
        cmd = claude_cli.command('/usr/bin/claude')
        self.assertNotIn('--restricted', cmd)
        self.assertNotIn('--bare', cmd)
        self.assertEqual(cmd[cmd.index('--tools') + 1], '')
        self.assertIn('--no-session-persistence', cmd)

    def test_env_drops_parent_session_vars(self):
        with patch.dict(claude_cli.os.environ, {'CLAUDECODE': '1', 'CLAUDE_CODE_ENTRYPOINT': 'cli', 'AI_AGENT': 'x', 'HOME': '/h'}):
            env = claude_cli.env()
        self.assertNotIn('CLAUDECODE', env)
        self.assertNotIn('AI_AGENT', env)
        self.assertEqual(env['HOME'], '/h')

    def test_classify_uses_shared_command_and_unwraps_fences(self):
        cats = [{'id': 'security', 'name': 'Security'}, {'id': 'infra', 'name': 'Infra'}]
        with patch.object(content, 'read_categories', return_value=cats), \
             patch.object(claude_cli, 'executable', return_value='/x/claude'), \
             patch.object(auto_categorize.subprocess, 'run', return_value=Completed('{"result": "```json\\n[\\"security\\", \\"bogus\\"]\\n```"}')) as run:
            self.assertEqual(auto_categorize.classify('Rotate certs', ''), ['security'])
        self.assertEqual(run.call_args.args[0], claude_cli.command('/x/claude'))
        with patch.object(content, 'read_categories', return_value=cats), \
             patch.object(claude_cli, 'executable', return_value='/x/claude'), \
             patch.object(auto_categorize.subprocess, 'run', return_value=Completed('{"is_error": true, "result": "Not logged in"}')):
            self.assertEqual(auto_categorize.classify('Rotate certs', ''), [])
        with patch.object(content, 'read_categories', return_value=cats), patch.object(claude_cli, 'executable', return_value=None):
            self.assertEqual(auto_categorize.classify('Rotate certs', ''), [])


if __name__ == '__main__':
    unittest.main()
