import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

import content_tags
import jira_sync


class FakeDB:
    def __init__(self, tickets):
        self.data = {"jiraTickets": tickets, "people": {}, "teamOptions": []}

    def read(self):
        return self.data

    def update_ticket(self, key, values):
        self.data["jiraTickets"].setdefault(key, {"key": key}).update(values)


class JiraResponse:
    def __init__(self, issues):
        self.issues = issues

    def raise_for_status(self):
        return None

    def json(self):
        return {"issues": self.issues}


def issue(summary="Rotate the ingress certificate", description="Renew cert-manager issuer"):
    return {
        "key": "OPS-1",
        "fields": {
            "summary": summary,
            "description": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}],
            },
            "status": {"name": "In Progress"},
            "priority": {"name": "High"},
        },
    }


class JiraAdfTextTests(unittest.TestCase):
    def test_preserves_paragraph_lists_and_explicit_breaks(self):
        description = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Summary line."}]},
                {"type": "bulletList", "content": [
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "First item"}]}]},
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Second item"}]}]},
                ]},
                {"type": "paragraph", "content": [
                    {"type": "text", "text": "After"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "line."},
                ]},
            ],
        }
        self.assertEqual(
            jira_sync._adf_to_text(description),
            "Summary line.\n\n- First item\n- Second item\n\nAfter\nline.",
        )


class ContentTagTests(unittest.TestCase):
    def test_clean_tags_normalizes_deduplicates_and_limits(self):
        tags = content_tags._clean_tags([
            " #Kubernetes ", "kubernetes", "Certificate   Rotation", "x", 4,
            "cert-manager", "ignored fourth valid tag",
        ], excluded=["Kubernetes"])
        self.assertEqual(tags, ["certificate rotation", "cert-manager", "ignored fourth valid tag"])

    def test_hash_tracks_title_and_bounded_description(self):
        baseline = content_tags.source_hash("Title", "Body")
        self.assertNotEqual(baseline, content_tags.source_hash("Changed", "Body"))
        self.assertNotEqual(baseline, content_tags.source_hash("Title", "Changed"))
        self.assertNotEqual(baseline, content_tags.source_hash("Title", "Body", ["Operations"]))
        long_body = "a" * content_tags.MAX_DESCRIPTION_CHARS
        self.assertEqual(
            content_tags.source_hash("Title", long_body),
            content_tags.source_hash("Title", long_body + "ignored"),
        )

    @patch.object(content_tags.claude_cli, "executable", return_value="/usr/local/bin/claude")
    @patch.object(content_tags.subprocess, "run")
    def test_cli_response_is_validated(self, run, _which):
        run.return_value = subprocess.CompletedProcess(
            [], 0,
            stdout=json.dumps({"result": json.dumps({"OPS-1": ["Kubernetes", "#TLS", "x"]})}),
            stderr="",
        )
        result = content_tags.generate([{"key": "OPS-1", "summary": "Rotate cert", "description": "Ingress", "excludedTags": ["Kubernetes"]}])
        self.assertEqual(result, {"OPS-1": ["tls"]})
        prompt = run.call_args.kwargs["input"]
        self.assertIn("untrusted ticket data", prompt)
        self.assertIn("Rotate cert", prompt)
        self.assertIn('"avoidTags": ["Kubernetes"]', prompt)
        command = run.call_args.args[0]
        self.assertIn("--no-session-persistence", command)
        self.assertIn("--tools", command)


class JiraContentTagSyncTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB({
            "OPS-1": {
                "key": "OPS-1", "summary": "Old title", "jiraStatus": "Backlog",
                "jiraPriority": "Medium", "categories": ["operations"],
            }
        })
        self.config = {"base_url": "https://jira.example", "email": "me@example.com", "api_token": "secret", "project": "OPS"}

    def sync(self, jira_issue, generated):
        generate_options = {"side_effect": generated} if isinstance(generated, Exception) else {"return_value": generated}
        with patch.object(jira_sync, "configured", return_value=True), \
             patch.object(jira_sync, "get_config", return_value=self.config), \
             patch.object(jira_sync, "discover_new_tickets", return_value={"added": []}), \
             patch.object(jira_sync.content, "read_categories", return_value=[{"id": "operations", "name": "Operations"}]), \
             patch.object(jira_sync.requests, "post", return_value=JiraResponse([jira_issue])) as post, \
             patch.object(jira_sync.content_tags, "generate", **generate_options) as generate:
            result = jira_sync.sync_all_tickets(self.db)
        return result, generate, post

    def test_refresh_generates_content_tags_and_caches_by_source(self):
        current = issue()
        result, generate, post = self.sync(current, {"OPS-1": ["cert-manager", "certificate rotation"]})
        ticket = self.db.data["jiraTickets"]["OPS-1"]
        self.assertEqual(ticket["contentTags"], ["cert-manager", "certificate rotation"])
        self.assertEqual(ticket["summary"], "Rotate the ingress certificate")
        self.assertEqual(ticket["description"], "Renew cert-manager issuer")
        self.assertEqual(result["tagged"], ["OPS-1"])
        self.assertIn("description", post.call_args.kwargs["json"]["fields"])
        self.assertEqual(generate.call_args.args[0][0]["excludedTags"], ["operations", "Operations"])
        generate.assert_called_once()

        result, generate, _post = self.sync(current, AssertionError("unchanged content was tagged again"))
        generate.assert_not_called()
        self.assertEqual(result["tagged"], [])

    def test_tag_failure_keeps_old_tags_and_allows_jira_updates(self):
        old_hash = content_tags.source_hash("Old title", "Old body", ["operations", "Operations"])
        ticket = self.db.data["jiraTickets"]["OPS-1"]
        ticket.update({"contentTags": ["legacy tag"], "contentTagSourceHash": old_hash})
        result, _generate, _post = self.sync(issue(description="Changed body"), RuntimeError("Claude offline"))
        self.assertEqual(ticket["contentTags"], ["legacy tag"])
        self.assertEqual(ticket["contentTagSourceHash"], old_hash)
        self.assertEqual(ticket["jiraStatus"], "In Progress")
        self.assertEqual(ticket["description"], "Changed body")
        self.assertEqual(result["tagError"], "Claude offline")

    def test_refresh_sets_parent_key_from_the_jira_parent_field(self):
        with_parent = issue()
        with_parent["fields"]["parent"] = {"key": "OPS-100"}
        self.sync(with_parent, {})
        self.assertEqual(self.db.data["jiraTickets"]["OPS-1"]["parentKey"], "OPS-100")

    def test_refresh_clears_parent_key_once_a_subtask_is_promoted(self):
        self.db.data["jiraTickets"]["OPS-1"]["parentKey"] = "OPS-100"
        self.sync(issue(), {})  # no "parent" field on this issue
        self.assertEqual(self.db.data["jiraTickets"]["OPS-1"]["parentKey"], "")


class JiraDiscoverParentKeyTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB({})
        self.config = {"base_url": "https://jira.example", "email": "me@example.com", "api_token": "secret", "project": "OPS"}
        self.db.data["jiraTickets"]["OPS-0"] = {"key": "OPS-0", "createdAt": "2026-01-01T00:00:00+00:00"}

    def discover(self, jira_issue):
        with patch.object(jira_sync, "configured", return_value=True), \
             patch.object(jira_sync, "get_config", return_value=self.config), \
             patch.object(jira_sync, "auto_categorize") as auto_categorize, \
             patch.object(jira_sync.requests, "post", return_value=JiraResponse([jira_issue])):
            auto_categorize.classify.return_value = []
            return jira_sync.discover_new_tickets(self.db)

    def test_a_newly_discovered_subtask_gets_its_parent_key(self):
        new_issue = issue()
        new_issue["key"] = "OPS-2"
        new_issue["fields"]["parent"] = {"key": "OPS-1"}
        self.discover(new_issue)
        self.assertEqual(self.db.data["jiraTickets"]["OPS-2"]["parentKey"], "OPS-1")

    def test_a_top_level_issue_gets_an_empty_parent_key_not_a_missing_field(self):
        new_issue = issue()
        new_issue["key"] = "OPS-3"
        self.discover(new_issue)
        self.assertEqual(self.db.data["jiraTickets"]["OPS-3"]["parentKey"], "")


if __name__ == "__main__":
    unittest.main()
