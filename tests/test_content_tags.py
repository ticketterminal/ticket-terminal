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


class JiraParseIssueLinksTests(unittest.TestCase):
    def test_outward_link_uses_the_outward_label(self):
        fields = {"issuelinks": [{
            "type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
            "outwardIssue": {"key": "OPS-50", "fields": {"summary": "Cut the base image"}},
        }]}
        self.assertEqual(jira_sync._parse_issue_links(fields), [
            {"key": "OPS-50", "label": "blocks", "summary": "Cut the base image"},
        ])

    def test_inward_link_uses_the_inward_label(self):
        fields = {"issuelinks": [{
            "type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
            "inwardIssue": {"key": "OPS-51", "fields": {"summary": "Ship the release"}},
        }]}
        self.assertEqual(jira_sync._parse_issue_links(fields), [
            {"key": "OPS-51", "label": "is blocked by", "summary": "Ship the release"},
        ])

    def test_a_link_with_neither_side_present_is_skipped(self):
        fields = {"issuelinks": [{"type": {"name": "Blocks"}}]}
        self.assertEqual(jira_sync._parse_issue_links(fields), [])

    def test_no_issuelinks_field_at_all_returns_empty(self):
        self.assertEqual(jira_sync._parse_issue_links({}), [])


class JiraContentTagSyncTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB({
            "OPS-1": {
                "key": "OPS-1", "summary": "Old title", "jiraStatus": "Backlog",
                "jiraPriority": "Medium", "categories": ["operations"],
            }
        })
        self.config = {"base_url": "https://jira.example", "email": "me@example.com", "api_token": "secret", "project": "OPS", "sync_limit": 50}

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

    def test_refresh_sets_linked_issues(self):
        with_link = issue()
        with_link["fields"]["issuelinks"] = [{
            "type": {"outward": "blocks"}, "outwardIssue": {"key": "OPS-50", "fields": {"summary": "Cut the base image"}},
        }]
        self.sync(with_link, {})
        self.assertEqual(self.db.data["jiraTickets"]["OPS-1"]["linkedIssues"], [
            {"key": "OPS-50", "label": "blocks", "summary": "Cut the base image"},
        ])

    def test_refresh_clears_linked_issues_once_unlinked(self):
        self.db.data["jiraTickets"]["OPS-1"]["linkedIssues"] = [{"key": "OPS-50", "label": "blocks", "summary": "x"}]
        self.sync(issue(), {})  # no "issuelinks" field on this issue
        self.assertEqual(self.db.data["jiraTickets"]["OPS-1"]["linkedIssues"], [])


class JiraDiscoverParentKeyTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB({})
        self.config = {"base_url": "https://jira.example", "email": "me@example.com", "api_token": "secret", "project": "OPS", "sync_limit": 50}
        self.db.data["jiraTickets"]["OPS-0"] = {"key": "OPS-0", "createdAt": "2026-01-01T00:00:00+00:00"}

    def discover(self, jira_issue):
        with patch.object(jira_sync, "configured", return_value=True), \
             patch.object(jira_sync, "get_config", return_value=self.config), \
             patch.object(jira_sync, "auto_categorize") as auto_categorize, \
             patch.object(jira_sync.requests, "post", return_value=JiraResponse([jira_issue])):
            auto_categorize.classify_many.return_value = {}
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

    def test_a_newly_discovered_issue_gets_its_linked_issues(self):
        new_issue = issue()
        new_issue["key"] = "OPS-4"
        new_issue["fields"]["issuelinks"] = [{
            "type": {"inward": "is blocked by"}, "inwardIssue": {"key": "OPS-1", "fields": {"summary": "Old title"}},
        }]
        self.discover(new_issue)
        self.assertEqual(self.db.data["jiraTickets"]["OPS-4"]["linkedIssues"], [
            {"key": "OPS-1", "label": "is blocked by", "summary": "Old title"},
        ])


class JiraDiscoverBrandNewWorkspaceTests(unittest.TestCase):
    """A workspace with zero tracked tickets (first "Test connection" click on a fresh
    install) must still actually pull tickets in — regression test for a bug where
    _newest_tracked_created_at returning None made discover_new_tickets bail out with
    {"added": []} before ever calling Jira, so a brand-new workspace could never import
    anything no matter how correct its Jira credentials were."""

    def setUp(self):
        self.db = FakeDB({})
        self.config = {"base_url": "https://jira.example", "email": "me@example.com", "api_token": "secret", "project": "OPS", "sync_limit": 50}

    def discover(self, jira_issues):
        with patch.object(jira_sync, "configured", return_value=True), \
             patch.object(jira_sync, "get_config", return_value=self.config), \
             patch.object(jira_sync, "auto_categorize") as auto_categorize, \
             patch.object(jira_sync.requests, "post", return_value=JiraResponse(jira_issues)) as post:
            auto_categorize.classify_many.return_value = {}
            result = jira_sync.discover_new_tickets(self.db)
            return result, post

    def test_zero_tracked_tickets_still_queries_jira_and_imports_the_result(self):
        result, post = self.discover([issue()])
        self.assertEqual(result["added"], ["OPS-1"])
        self.assertIn("OPS-1", self.db.data["jiraTickets"])
        jql = post.call_args.kwargs["json"]["jql"]
        self.assertNotIn("created >", jql, "no cutoff to be incremental from yet — pulls the project's newest page instead")
        self.assertIn("project = OPS", jql)
        self.assertIn("ORDER BY created DESC", jql, "newest tickets first, not a crawl from the start of the project's history")

    def test_initial_import_uses_the_configured_sync_limit(self):
        self.config["sync_limit"] = 10
        _, post = self.discover([issue()])
        self.assertEqual(post.call_args.kwargs["json"]["maxResults"], 10)

    def test_second_call_is_incremental_from_the_first_imported_ticket(self):
        first = issue()
        first["fields"]["created"] = "2026-01-01T00:00:00+00:00"
        self.discover([first])  # OPS-1 now tracked, with a real createdAt
        _, post = self.discover([])
        jql = post.call_args.kwargs["json"]["jql"]
        self.assertIn("created >", jql, "now that something is tracked, the next call goes back to incremental")
        self.assertIn("ORDER BY created ASC", jql, "incremental catch-up still walks forward in time, oldest-missed first")

    def test_classification_is_one_batched_call_not_one_per_ticket(self):
        with patch.object(jira_sync, "configured", return_value=True), \
             patch.object(jira_sync, "get_config", return_value=self.config), \
             patch.object(jira_sync, "auto_categorize") as auto_categorize, \
             patch.object(jira_sync.requests, "post", return_value=JiraResponse([issue(), {**issue(), "key": "OPS-2"}])):
            auto_categorize.classify_many.return_value = {"OPS-1": ["security"], "OPS-2": []}
            jira_sync.discover_new_tickets(self.db)
            auto_categorize.classify_many.assert_called_once()
            auto_categorize.classify.assert_not_called()
        self.assertEqual(self.db.data["jiraTickets"]["OPS-1"]["categories"], ["security"])
        self.assertEqual(self.db.data["jiraTickets"]["OPS-2"]["categories"], [])

    def test_classification_failure_still_imports_every_ticket_uncategorized(self):
        with patch.object(jira_sync, "configured", return_value=True), \
             patch.object(jira_sync, "get_config", return_value=self.config), \
             patch.object(jira_sync, "auto_categorize") as auto_categorize, \
             patch.object(jira_sync.requests, "post", return_value=JiraResponse([issue()])):
            auto_categorize.classify_many.side_effect = RuntimeError("claude not authenticated")
            result = jira_sync.discover_new_tickets(self.db)
        self.assertEqual(result["added"], ["OPS-1"])
        self.assertEqual(self.db.data["jiraTickets"]["OPS-1"]["categories"], [])
        # Regression: every ticket landing uncategorized with zero visible reason is its own
        # bug (found live testing a container whose Claude CLI was never signed in) — the
        # failure must surface, not just get swallowed the way it used to.
        self.assertEqual(result["categoryError"], "claude not authenticated")

    def test_classification_success_reports_no_category_error(self):
        with patch.object(jira_sync, "configured", return_value=True), \
             patch.object(jira_sync, "get_config", return_value=self.config), \
             patch.object(jira_sync, "auto_categorize") as auto_categorize, \
             patch.object(jira_sync.requests, "post", return_value=JiraResponse([issue()])):
            auto_categorize.classify_many.return_value = {"OPS-1": ["security"]}
            result = jira_sync.discover_new_tickets(self.db)
        self.assertIsNone(result["categoryError"])

    def test_category_error_propagates_through_sync_all_tickets(self):
        db = FakeDB({})
        with patch.object(jira_sync, "configured", return_value=True), \
             patch.object(jira_sync, "get_config", return_value=self.config), \
             patch.object(jira_sync, "auto_categorize") as auto_categorize, \
             patch.object(jira_sync.content, "read_categories", return_value=[]), \
             patch.object(jira_sync.content_tags, "generate", return_value={}), \
             patch.object(jira_sync.requests, "post", return_value=JiraResponse([issue()])):
            auto_categorize.classify_many.side_effect = RuntimeError("claude not authenticated")
            result = jira_sync.sync_all_tickets(db)
        self.assertEqual(result["categoryError"], "claude not authenticated")
        self.assertEqual(db.data["jiraTickets"]["OPS-1"]["categories"], [])


if __name__ == "__main__":
    unittest.main()
