import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

import db
import jira_sync
import main
import notion_sync
import settings_store
from workspace_fixture import TempWorkspaces


class TicketCommentTests(unittest.TestCase):
    def setUp(self):
        self.workspaces = TempWorkspaces().start()
        settings_store.set_section_fields("jira", {
            "baseUrl": "https://example.atlassian.net", "email": "dev@example.com",
            "apiToken": "jira-token", "projectKey": "ENG",
        })
        settings_store.set_section_fields("notion", {
            "accessToken": "notion-token", "databaseId": "db-1", "botId": "bot-1",
        })

    def tearDown(self):
        self.workspaces.stop()

    def test_jira_reads_adf_comments_and_writes_adf(self):
        payload = {
            "comments": [{
                "id": "11", "author": {"displayName": "Dana"},
                "created": "2026-10-01T10:00:00Z", "updated": "2026-10-01T11:00:00Z",
                "body": {"type": "doc", "version": 1, "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "First"}]},
                    {"type": "paragraph", "content": [{"type": "text", "text": "Second"}]},
                ]},
            }],
            "total": 1,
        }
        response = MagicMock(); response.json.return_value = payload
        response.raise_for_status.return_value = None
        with patch.object(jira_sync.requests, "get", return_value=response) as get:
            comments = jira_sync.get_comments("ENG-1")
        self.assertEqual(comments[0]["body"], "First\n\nSecond")
        self.assertEqual(get.call_args.kwargs["params"]["maxResults"], 100)

        written = dict(payload["comments"][0], body=jira_sync._text_to_adf("one\ntwo"))
        response.json.return_value = written
        with patch.object(jira_sync.requests, "post", return_value=response) as post:
            jira_sync.add_comment("ENG-1", "one\ntwo")
        self.assertEqual(
            post.call_args.kwargs["json"]["body"]["content"][1]["content"][0]["text"],
            "two",
        )

    def test_notion_lists_adds_and_updates_comments_with_current_api_version(self):
        comment = {
            "id": "c-1", "created_by": {"id": "bot-1"},
            "created_time": "2026-10-01T10:00:00Z", "last_edited_time": "2026-10-01T10:00:00Z",
            "rich_text": [{"plain_text": "Hello"}],
        }
        page = MagicMock(status_code=200); page.json.return_value = {"results": [comment], "has_more": False}
        with patch.object(notion_sync.requests, "request", return_value=page) as request:
            comments = notion_sync.get_comments({"notionPageId": "page-1"})
        self.assertTrue(comments[0]["editable"])
        self.assertEqual(request.call_args.kwargs["params"]["block_id"], "page-1")
        self.assertEqual(request.call_args.kwargs["headers"]["Notion-Version"], notion_sync.NOTION_COMMENTS_VERSION)

        page.json.return_value = comment
        with patch.object(notion_sync.requests, "request", return_value=page) as request:
            notion_sync.add_comment({"notionPageId": "page-1"}, "Hello")
            self.assertEqual(request.call_args.kwargs["json"]["parent"], {"page_id": "page-1"})
        with patch.object(notion_sync.requests, "request", return_value=page) as request:
            notion_sync.update_comment({"notionPageId": "page-1"}, "c-1", "Changed")
            self.assertTrue(request.call_args.args[1].endswith("/comments/c-1"))
            self.assertEqual(request.call_args.kwargs["json"]["rich_text"][0]["text"]["content"], "Changed")

    def test_http_dispatches_by_ticket_source_and_rejects_empty_comments(self):
        db.write({
            "jiraTickets": {
                "ENG-1": {"key": "ENG-1"},
                "NOTION-1": {"key": "NOTION-1", "source": "notion", "notionPageId": "page-1"},
            },
            "people": {}, "teamOptions": [],
        })
        with patch.object(main.jira_sync, "get_comments", return_value=[]) as jira_get:
            result = main.get_ticket_comments("ENG-1")
        self.assertTrue(result["ok"]); jira_get.assert_called_once_with("ENG-1")

        with patch.object(main.notion_sync, "add_comment", return_value={"id": "c-1"}) as notion_add:
            result = main.add_ticket_comment("NOTION-1", {"text": " ship it "})
        self.assertTrue(result["ok"])
        notion_add.assert_called_once_with(db.read()["jiraTickets"]["NOTION-1"], "ship it")
        self.assertFalse(main.add_ticket_comment("ENG-1", {"text": "   "})["ok"])
        self.assertFalse(main.get_ticket_comments("MISSING")["ok"])


if __name__ == "__main__":
    unittest.main()
