import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import db
import jira_sync
import main
import settings_store
from workspace_fixture import TempWorkspaces


class JiraSyncFixture(unittest.TestCase):
    def setUp(self):
        self.workspaces = TempWorkspaces().start()
        settings_store.set_section_fields('jira', {
            'baseUrl': 'https://example.atlassian.net', 'email': 'a@b.com',
            'apiToken': 'tok', 'projectKey': 'ENG',
        })
        jira_sync._assignable_users_cache.clear()
        jira_sync._workflow_statuses_cache.clear()

    def tearDown(self):
        self.workspaces.stop()


class AssignableUsersTests(JiraSyncFixture):
    def test_fetches_the_project_roster_and_caches_it_per_workspace(self):
        payload = [{'accountId': 'acc-1', 'displayName': 'Dana'}, {'accountId': 'acc-2', 'displayName': 'Sam'}]
        resp = MagicMock(); resp.json.return_value = payload; resp.raise_for_status.return_value = None
        with patch.object(jira_sync.requests, 'get', return_value=resp) as get:
            users = jira_sync.get_assignable_users()
            jira_sync.get_assignable_users()  # second call must not hit the network again
        get.assert_called_once()
        self.assertEqual(get.call_args.kwargs['params']['project'], 'ENG')
        self.assertEqual(users, payload)

    def test_invalidate_cache_forces_a_fresh_fetch(self):
        resp = MagicMock(); resp.json.return_value = []; resp.raise_for_status.return_value = None
        with patch.object(jira_sync.requests, 'get', return_value=resp) as get:
            jira_sync.get_assignable_users()
            jira_sync.invalidate_cache()
            jira_sync.get_assignable_users()
        self.assertEqual(get.call_count, 2)

    def test_raises_when_not_configured(self):
        settings_store.set_section_fields('jira', {'apiToken': ''})
        with self.assertRaises(RuntimeError):
            jira_sync.get_assignable_users()

    def test_narrows_to_names_already_seen_as_reporter_or_assignee(self):
        # A wide-open permission scheme can make /user/assignable/search return
        # effectively the whole company (service accounts and bots included) —
        # the dropdown should only offer people this board has actually seen.
        db.write({'jiraTickets': {
            'ENG-1': {'key': 'ENG-1', 'reporter': 'Dana'},
            'ENG-2': {'key': 'ENG-2', 'assigneeName': 'Sam'},
        }, 'people': {}, 'teamOptions': []})
        payload = [
            {'accountId': 'acc-1', 'displayName': 'Dana'},
            {'accountId': 'acc-2', 'displayName': 'Sam'},
            {'accountId': 'acc-3', 'displayName': 'Automation Bot'},
        ]
        resp = MagicMock(); resp.json.return_value = payload; resp.raise_for_status.return_value = None
        with patch.object(jira_sync.requests, 'get', return_value=resp):
            users = jira_sync.get_assignable_users()
        self.assertEqual({u['displayName'] for u in users}, {'Dana', 'Sam'})

    def test_falls_back_to_the_unnarrowed_list_with_no_synced_history_yet(self):
        payload = [{'accountId': 'acc-1', 'displayName': 'Dana'}, {'accountId': 'acc-3', 'displayName': 'Automation Bot'}]
        resp = MagicMock(); resp.json.return_value = payload; resp.raise_for_status.return_value = None
        with patch.object(jira_sync.requests, 'get', return_value=resp):
            users = jira_sync.get_assignable_users()
        self.assertEqual({u['displayName'] for u in users}, {'Dana', 'Automation Bot'})


class SetAssigneeTests(JiraSyncFixture):
    def test_assigns_by_account_id(self):
        resp = MagicMock(); resp.raise_for_status.return_value = None
        with patch.object(jira_sync.requests, 'put', return_value=resp) as put:
            jira_sync.set_assignee('ENG-1', 'acc-1')
        self.assertEqual(put.call_args.kwargs['json'], {'fields': {'assignee': {'accountId': 'acc-1'}}})

    def test_empty_account_id_clears_the_assignee(self):
        # Jira Cloud's documented way to unassign is a null assignee field,
        # not a sentinel id — regression guard for that exact shape.
        resp = MagicMock(); resp.raise_for_status.return_value = None
        with patch.object(jira_sync.requests, 'put', return_value=resp) as put:
            jira_sync.set_assignee('ENG-1', '')
        self.assertEqual(put.call_args.kwargs['json'], {'fields': {'assignee': None}})


class HiddenAssigneesTests(JiraSyncFixture):
    """The board's own curation on top of get_assignable_users — hiding
    someone here is local-only (Settings -> "Jira assignees shown") and
    never touches Jira's real assignable-users list."""

    def test_get_and_put_round_trip_through_db(self):
        self.assertEqual(main.get_hidden_assignees(), {'ids': []})
        result = main.put_hidden_assignees({'ids': ['acc-9']})
        self.assertEqual(result, {'ids': ['acc-9']})
        self.assertEqual(main.get_hidden_assignees(), {'ids': ['acc-9']})
        self.assertEqual(db.read()['hiddenAssignees'], ['acc-9'])

    def test_jira_assignable_users_endpoint_annotates_hidden_without_excluding(self):
        main.put_hidden_assignees({'ids': ['acc-2']})
        with patch.object(main.jira_sync, 'get_assignable_users', return_value=[
            {'accountId': 'acc-1', 'displayName': 'Dana'},
            {'accountId': 'acc-2', 'displayName': 'Sam'},
        ]):
            res = main.get_jira_assignable_users()
        self.assertTrue(res['ok'], res)
        # Still present (not filtered out) so the Settings page can show and
        # reverse a hidden entry — only the ticket row's <select> excludes it.
        self.assertEqual(
            {(u['accountId'], u['hidden']) for u in res['users']},
            {('acc-1', False), ('acc-2', True)},
        )


if __name__ == '__main__':
    unittest.main()
