import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

import change_requests
import main
from workspace_fixture import TempWorkspaces


class ChangeRequestParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write_jsonl(self, rows):
        path = self.root / "session.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    def test_claude_prefers_first_class_pr_link_and_deduplicates_repeats(self):
        url = "https://gitlab.com/acme/platform/-/merge_requests/42"
        path = self.write_jsonl([
            {"type": "pr-link", "prUrl": url, "prRepository": "acme/platform", "timestamp": "2026-10-08T10:00:00Z"},
            {"type": "assistant", "timestamp": "2026-10-08T10:00:01Z", "message": {"content": [{"type": "text", "text": url + "#note_12"}]}},
        ])
        found = change_requests.read_change_requests(path, "claude")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["url"], url)
        self.assertEqual(found[0]["source"], "claude-pr-link")
        self.assertEqual(found[0]["number"], 42)

    def test_user_pasted_url_is_ignored_but_tool_result_is_discovered(self):
        pasted = "https://github.com/acme/unrelated/pull/3"
        created = "https://github.com/acme/service/pull/9"
        path = self.write_jsonl([
            {"type": "user", "message": {"content": pasted}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "Created " + created}]}},
        ])
        found = change_requests.read_change_requests(path, "claude")
        self.assertEqual([item["url"] for item in found], [created])

    def test_codex_structured_output_supports_gitlab_and_github(self):
        path = self.write_jsonl([
            {"timestamp": "2026-10-08T10:00:00Z", "payload": {"type": "function_call_output", "output": "https://git.example.com/a/b/-/merge_requests/7"}},
            {"timestamp": "2026-10-08T10:00:01Z", "payload": {"type": "message", "role": "assistant", "content": "Opened https://github.example.com/a/b/pull/8."}},
        ])
        found = change_requests.read_change_requests(path, "codex")
        self.assertEqual([(item["provider"], item["number"]) for item in found], [("gitlab", 7), ("github", 8)])


class ChangeRequestEndpointTests(unittest.TestCase):
    def setUp(self):
        self.workspaces = TempWorkspaces().start()
        main._change_request_scan_cache.clear()
        main._change_request_response_cache.clear()

    def tearDown(self):
        self.workspaces.stop()

    def test_refresh_materializes_discovered_and_legacy_links(self):
        ticket = {"claudeSessionId": "sid", "mrLink": "https://github.com/acme/old/pull/1"}
        discovered = [{"url": "https://gitlab.com/acme/new/-/merge_requests/2", "source": "claude-pr-link"}]
        with patch.object(main.db, "read", return_value={"jiraTickets": {"T-1": ticket}}), \
             patch.object(main, "_ticket_session_log", side_effect=[Path("/tmp/claude.jsonl"), None]), \
             patch.object(main.change_requests, "read_change_requests", side_effect=[discovered, []]), \
             patch.object(main.db, "update_ticket") as update:
            result = main.refresh_ticket_change_requests("T-1")
        self.assertTrue(result["ok"])
        self.assertEqual([item["number"] for item in result["changeRequests"]], [1, 2])
        update.assert_called_once_with("T-1", {"changeRequests": result["changeRequests"]})

    def test_refresh_rejects_unknown_ticket(self):
        with patch.object(main.db, "read", return_value={"jiraTickets": {}}):
            result = main.refresh_ticket_change_requests("missing")
        self.assertFalse(result["ok"])

    def test_unchanged_transcript_is_not_rescanned(self):
        transcript = self.workspaces.root / "session.jsonl"
        transcript.write_text("first")
        ticket = {"claudeSessionId": "sid"}
        discovered = [{"url": "https://github.com/acme/repo/pull/1", "source": "transcript"}]
        with patch.object(main.db, "read", return_value={"jiraTickets": {"T-1": ticket}}), \
             patch.object(main, "_ticket_session_log", side_effect=lambda _ticket, provider: transcript if provider == "claude" else None), \
             patch.object(main.change_requests, "read_change_requests", side_effect=lambda path, _provider: discovered if path else []) as read:
            first = main._refresh_ticket_change_requests("T-1")
            second = main._refresh_ticket_change_requests("T-1")
            transcript.write_text("changed and longer")
            third = main._refresh_ticket_change_requests("T-1")
        self.assertTrue(first["ok"] and second["ok"] and third["ok"])
        self.assertEqual(read.call_count, 3, "Claude scans twice; the absent Codex transcript is scanned only once")

    def test_duplicate_poll_responses_are_coalesced_before_reading_db(self):
        result = {"ok": True, "changeRequests": []}
        with patch.object(main, "_refresh_ticket_change_requests", return_value=result) as refresh:
            self.assertEqual(main.refresh_ticket_change_requests("T-1"), result)
            self.assertEqual(main.refresh_ticket_change_requests("T-1"), result)
        refresh.assert_called_once_with("T-1")


if __name__ == "__main__":
    unittest.main()
