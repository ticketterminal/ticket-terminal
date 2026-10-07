import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

import agent_activity
import main
from workspace_fixture import TempWorkspaces


class AgentActivityParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.memory = self.root / "memory"
        self.memory.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_jsonl(self, name, rows):
        path = self.root / name
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    def test_claude_tools_become_commands_memories_and_skills(self):
        memory_path = self.memory / "login-to-aws.md"
        skill_path = self.root / "skills" / "aws" / "SKILL.md"
        path = self.write_jsonl("claude.jsonl", [{
            "timestamp": "2026-10-07T08:00:00Z",
            "message": {"content": [
                {"type": "tool_use", "id": "a", "name": "Bash", "input": {"command": "aws sso login --profile dev"}},
                {"type": "tool_use", "id": "b", "name": "Read", "input": {"file_path": str(memory_path)}},
                {"type": "tool_use", "id": "c", "name": "Read", "input": {"file_path": str(skill_path)}},
            ]},
        }])
        events = agent_activity.read_activity(path, "claude", self.memory)
        self.assertEqual([event["kind"] for event in events], ["command", "memory", "skill"])
        self.assertEqual(events[0]["title"], "Sign in to AWS")
        self.assertEqual(events[1]["resource"]["id"], "login-to-aws")
        self.assertEqual(events[2]["resource"]["id"], "aws")

    def test_codex_function_and_custom_calls_are_normalized_and_deduped(self):
        rows = [
            {"timestamp": "2026-10-07T08:00:00Z", "type": "response_item", "payload": {
                "type": "function_call", "call_id": "call-1", "name": "exec_command",
                "arguments": json.dumps({"cmd": "git status --short"}),
            }},
            {"timestamp": "2026-10-07T08:00:01Z", "type": "response_item", "payload": {
                "type": "custom_tool_call", "call_id": "call-2", "name": "exec_command",
                "input": "await tools.exec_command({cmd: \"aws sso login\"})",
            }},
            {"timestamp": "2026-10-07T08:00:02Z", "type": "response_item", "payload": {
                "type": "function_call", "call_id": "call-1", "name": "exec_command",
                "arguments": json.dumps({"cmd": "git status --short"}),
            }},
        ]
        events = agent_activity.read_activity(self.write_jsonl("codex.jsonl", rows), "codex", self.memory)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["title"], "Run Git command")
        self.assertEqual(events[1]["title"], "Sign in to AWS")

    def test_command_details_redact_common_secret_forms(self):
        path = self.write_jsonl("secret.jsonl", [{"message": {"content": [{
            "type": "tool_use", "id": "secret", "name": "Bash",
            "input": {"command": "API_TOKEN=abc deploy --password hunter2"},
        }]}}])
        detail = agent_activity.read_activity(path, "claude", self.memory)[0]["detail"]
        self.assertNotIn("abc", detail)
        self.assertNotIn("hunter2", detail)
        self.assertIn("API_TOKEN=•••", detail)

    def test_shell_read_inside_memory_directory_gets_a_clickable_resource(self):
        command = f"cd {self.memory}; cat login-to-aws.md"
        path = self.write_jsonl("shell-memory.jsonl", [{"message": {"content": [{
            "type": "tool_use", "id": "shell-memory", "name": "Bash", "input": {"command": command},
        }]}}])
        event = agent_activity.read_activity(path, "claude", self.memory)[0]
        self.assertEqual(event["kind"], "command")
        self.assertEqual(event["resource"]["id"], "login-to-aws")

    def test_reader_bounds_work_to_the_transcript_tail_and_caches_it(self):
        old = {"message": {"content": [{"type": "tool_use", "id": "old", "name": "Bash", "input": {"command": "old command"}}]}}
        recent = {"message": {"content": [{"type": "tool_use", "id": "new", "name": "Bash", "input": {"command": "new command"}}]}}
        path = self.root / "large.jsonl"
        path.write_text(json.dumps(old) + "\n" + (json.dumps({"noise": "x" * 500}) + "\n") * 3 + json.dumps(recent) + "\n")
        agent_activity._CACHE.clear()
        with patch.object(agent_activity, "MAX_TRANSCRIPT_BYTES", 900):
            first = agent_activity.read_activity(path, "claude", self.memory)
            with patch.object(Path, "open", side_effect=AssertionError("cache miss")):
                second = agent_activity.read_activity(path, "claude", self.memory)
        self.assertEqual([event["detail"] for event in first], ["new command"])
        self.assertEqual(second, first)


class AgentActivityEndpointTests(unittest.TestCase):
    def setUp(self):
        self.workspaces = TempWorkspaces().start()

    def tearDown(self):
        self.workspaces.stop()

    def test_endpoint_resolves_the_ticket_session_and_provider_log(self):
        with patch.object(main.db, "read", return_value={"jiraTickets": {"T-1": {"codexSessionId": "sid-1"}}}), \
             patch.object(main.memory_analysis, "codex_transcript_path", return_value=Path("/tmp/sid-1.jsonl")) as transcript, \
             patch.object(main.agent_activity, "read_activity", return_value=[{"kind": "command"}]) as read:
            result = main.get_agent_activity("T-1", "codex", 20)
        self.assertTrue(result["ok"])
        self.assertEqual(result["events"], [{"kind": "command"}])
        transcript.assert_called_once_with("sid-1")
        self.assertEqual(read.call_args.args[1], "codex")
        self.assertEqual(read.call_args.args[3], 20)

    def test_endpoint_returns_an_empty_trail_before_session_id_exists(self):
        with patch.object(main.db, "read", return_value={"jiraTickets": {"T-1": {}}}):
            result = main.get_agent_activity("T-1", "claude")
        self.assertEqual(result, {"ok": True, "events": [], "sessionId": None})

    def test_endpoint_rejects_unknown_provider(self):
        self.assertFalse(main.get_agent_activity("T-1", "shell")["ok"])


if __name__ == "__main__":
    unittest.main()
