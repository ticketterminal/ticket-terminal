import datetime
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import content
import db
import main
import notion_sync as ns
import settings_store
from workspace_fixture import TempWorkspaces


SCHEMA = {
    'object': 'database', 'id': 'db-1', 'title': [{'plain_text': 'Tickets'}],
    'properties': {
        'Name': {'type': 'title', 'title': {}},
        'ID': {'type': 'unique_id', 'unique_id': {'prefix': 'ENG'}},
        'Status': {'type': 'status', 'status': {'options': [{'id': 's1', 'name': 'Backlog'}, {'id': 's2', 'name': 'In progress'}, {'id': 's3', 'name': 'Done'}], 'groups': [{'name': 'To-do', 'option_ids': ['s1']}, {'name': 'In progress', 'option_ids': ['s2']}, {'name': 'Complete', 'option_ids': ['s3']}]}},
        'Priority': {'type': 'select', 'select': {'options': [{'name': 'P0'}, {'name': 'P1'}, {'name': 'P2'}]}},
        'Tags': {'type': 'multi_select', 'multi_select': {'options': []}},
        'Owner': {'type': 'people', 'people': {}},
    },
}


def page(pid, number, title, status='Backlog', priority='P1', edited='2026-09-01T10:00:00.000Z'):
    return {
        'object': 'page', 'id': pid, 'url': 'https://notion.so/' + pid.replace('-', ''),
        'created_time': '2026-08-30T08:00:00.000Z', 'last_edited_time': edited,
        'properties': {
            'Name': {'type': 'title', 'title': [{'plain_text': title}]},
            'ID': {'type': 'unique_id', 'unique_id': {'prefix': 'ENG', 'number': number}},
            'Status': {'type': 'status', 'status': {'name': status}},
            'Priority': {'type': 'select', 'select': {'name': priority} if priority else None},
            'Tags': {'type': 'multi_select', 'multi_select': []},
            'Owner': {'type': 'people', 'people': [{'name': 'Dana'}]},
        },
    }


class NotionFixture(unittest.TestCase):
    def setUp(self):
        # One temp data root laid out like a real install, with the "default"
        # workspace entered — every path (db.json, settings.json, categories)
        # now resolves through workspaces.py rather than a patched constant.
        self.workspaces = TempWorkspaces().start()
        self.root = self.workspaces.root
        self.patches = [patch.dict(ns.os.environ, {}, clear=False)]
        for p in self.patches:
            p.start()
        for var in ('NOTION_CLIENT_ID', 'NOTION_CLIENT_SECRET', 'NOTION_TOKEN', 'NOTION_DATABASE_ID', 'NOTION_REDIRECT_URI'):
            ns.os.environ.pop(var, None)
        ns._schema_cache.clear()
        ns._timebox_cache.clear()
        ns._oauth_states.clear()
        ns.last_oauth_error = None
        content.write_categories([{'id': 'security', 'name': 'Security', 'status': 'gap', 'color': '#000', 'note': '', 'docs': [], 'skills': [], 'memories': []}])

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.workspaces.stop()

    def connect(self, database_id='db-1'):
        settings_store.set_section_fields('notion', {'accessToken': 'tok', 'authMode': 'token', 'databaseId': database_id})


class SettingsStoreTests(NotionFixture):
    def test_blank_secrets_are_kept_and_sections_merge(self):
        settings_store.update({'notion': {'clientId': 'cid', 'clientSecret': 'shh'}, 'jira': {'apiToken': 'jt'}})
        settings_store.update({'notion': {'clientId': 'cid2', 'clientSecret': ''}, 'jira': {'apiToken': '', 'projectKey': 'X'}})
        s = settings_store.read()
        self.assertEqual((s['notion']['clientId'], s['notion']['clientSecret']), ('cid2', 'shh'))
        self.assertEqual((s['jira']['apiToken'], s['jira']['projectKey']), ('jt', 'X'))
        settings_store.set_section_fields('notion', {'clientSecret': ''})
        self.assertEqual(settings_store.read()['notion']['clientSecret'], '')

    def test_env_fallback_and_settings_precedence(self):
        ns.os.environ['NOTION_TOKEN'] = 'env-token'
        ns.os.environ['NOTION_DATABASE_ID'] = 'https://www.notion.so/acme/Tickets-1f2a3b4c5d6e7f8091a2b3c4d5e6f708?v=1'
        c = ns.get_config()
        self.assertEqual(c['access_token'], 'env-token')
        self.assertEqual(c['database_id'], '1f2a3b4c-5d6e-7f80-91a2-b3c4d5e6f708')
        self.assertTrue(ns.configured())
        settings_store.set_section_fields('notion', {'accessToken': 'ui-token'})
        self.assertEqual(ns.get_config()['access_token'], 'ui-token')


class OAuthTests(NotionFixture):
    def test_authorize_url_requires_credentials(self):
        with self.assertRaises(RuntimeError):
            ns.build_authorize_url()
        self.assertEqual(main.notion_oauth_start().headers['location'], '/#/settings')
        self.assertIn('client ID', ns.last_oauth_error)

    def test_authorize_url_and_single_use_state(self):
        settings_store.update({'notion': {'clientId': 'cid', 'clientSecret': 'sec', 'redirectUri': 'http://localhost:9/cb'}})
        url = ns.build_authorize_url()
        parsed = urlparse(url)
        q = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, 'api.notion.com')
        self.assertEqual(q['client_id'], ['cid'])
        self.assertEqual(q['redirect_uri'], ['http://localhost:9/cb'])
        self.assertEqual(q['owner'], ['user'])
        self.assertEqual(q['response_type'], ['code'])
        state = q['state'][0]
        self.assertIsNone(ns.consume_oauth_state('bogus'))
        self.assertEqual(ns.consume_oauth_state(state), 'default')
        self.assertIsNone(ns.consume_oauth_state(state), 'state must be single-use')

    def test_expired_state_rejected(self):
        settings_store.update({'notion': {'clientId': 'cid', 'clientSecret': 'sec'}})
        state = parse_qs(urlparse(ns.build_authorize_url()).query)['state'][0]
        ns._oauth_states[state] = (time.time() - 1, 'default')
        self.assertIsNone(ns.consume_oauth_state(state))

    def test_callback_exchanges_code_and_stores_workspace(self):
        settings_store.update({'notion': {'clientId': 'cid', 'clientSecret': 'sec'}})
        state = parse_qs(urlparse(ns.build_authorize_url()).query)['state'][0]
        response = MagicMock(status_code=200)
        response.json.return_value = {'access_token': 'at-1', 'refresh_token': 'rt-1', 'workspace_name': 'Acme', 'workspace_id': 'ws', 'bot_id': 'bot'}
        with patch.object(ns.requests, 'post', return_value=response) as post:
            redirect = main.notion_oauth_callback(code='the-code', state=state)
        self.assertEqual(redirect.headers['location'], '/#/settings')
        self.assertIsNone(ns.last_oauth_error)
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs['json'], {'grant_type': 'authorization_code', 'code': 'the-code', 'redirect_uri': ns.DEFAULT_REDIRECT_URI})
        self.assertTrue(kwargs['headers']['Authorization'].startswith('Basic '))
        stored = settings_store.read()['notion']
        self.assertEqual((stored['accessToken'], stored['refreshToken'], stored['workspaceName'], stored['authMode']), ('at-1', 'rt-1', 'Acme', 'oauth'))
        self.assertTrue(ns.connected())

    def test_callback_rejects_bad_state_and_reports_notion_error(self):
        main.notion_oauth_callback(code='x', state='forged')
        self.assertIn('state', ns.last_oauth_error)
        self.assertFalse(ns.connected())
        main.notion_oauth_callback(error='access_denied', error_description='User cancelled')
        self.assertEqual(ns.last_oauth_error, 'User cancelled')

    def test_401_triggers_refresh_and_retry(self):
        settings_store.update({'notion': {'clientId': 'cid', 'clientSecret': 'sec'}})
        settings_store.set_section_fields('notion', {'accessToken': 'old', 'refreshToken': 'rt', 'authMode': 'oauth', 'databaseId': 'db-1'})
        unauthorized = MagicMock(status_code=401); unauthorized.json.return_value = {'message': 'expired'}
        ok = MagicMock(status_code=200); ok.json.return_value = {'results': [], 'has_more': False}
        refreshed = MagicMock(status_code=200); refreshed.json.return_value = {'access_token': 'new', 'refresh_token': 'rt2'}
        with patch.object(ns.requests, 'request', side_effect=[unauthorized, ok]) as req, \
             patch.object(ns.requests, 'post', return_value=refreshed):
            ns._request('POST', '/search', json={})
        self.assertEqual(req.call_args_list[1].kwargs['headers']['Authorization'], 'Bearer new')
        self.assertEqual(settings_store.read()['notion']['refreshToken'], 'rt2')

    def test_personal_token_validated_before_storing(self):
        settings_store.set_section_fields('notion', {'accessToken': 'working', 'authMode': 'token', 'workspaceName': 'Acme'})
        rejected = MagicMock(status_code=401); rejected.json.return_value = {'message': 'API token is invalid.'}
        with patch.object(ns.requests, 'get', return_value=rejected):
            result = main.notion_set_token({'token': 'ntn_bad'})
        self.assertFalse(result['ok'])
        self.assertIn('API token is invalid', result['error'])
        stored = settings_store.read()['notion']
        self.assertEqual((stored['accessToken'], stored['workspaceName']), ('working', 'Acme'), 'a bad paste must not clobber the working connection')

        me = MagicMock(status_code=200); me.json.return_value = {'object': 'user', 'id': 'bot-1', 'type': 'bot', 'bot': {'workspace_name': 'Beta Co'}}
        with patch.object(ns.requests, 'get', return_value=me) as get:
            result = main.notion_set_token({'token': ' ntn_good '})
        self.assertTrue(result['ok'])
        self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer ntn_good')
        stored = settings_store.read()['notion']
        self.assertEqual((stored['accessToken'], stored['authMode'], stored['workspaceName'], stored['botId']), ('ntn_good', 'token', 'Beta Co', 'bot-1'))
        self.assertFalse(main.notion_set_token({'token': ''})['ok'])

    def test_disconnect_clears_tokens_only(self):
        settings_store.update({'notion': {'clientId': 'cid', 'clientSecret': 'sec', 'databaseId': 'db-1'}})
        settings_store.set_section_fields('notion', {'accessToken': 'tok', 'refreshToken': 'rt'})
        ns.disconnect()
        stored = settings_store.read()['notion']
        self.assertEqual((stored['accessToken'], stored['refreshToken']), ('', ''))
        self.assertEqual((stored['clientId'], stored['databaseId']), ('cid', 'db-1'))


    def test_oauth_stores_the_token_in_the_workspace_it_started_from(self):
        """Notion calls the redirect URI itself, so the callback carries no
        ?w= and the middleware resolves it to the default workspace. Without
        the slug riding in the state, connecting from a second workspace would
        silently overwrite the default workspace's Notion token."""
        import workspaces
        self.workspaces.register('acme')
        settings_store.update({'notion': {'clientId': 'cid', 'clientSecret': 'sec'}})
        with workspaces.use('acme'):
            settings_store.update({'notion': {'clientId': 'cid', 'clientSecret': 'sec'}})
            state = parse_qs(urlparse(ns.build_authorize_url()).query)['state'][0]

        response = MagicMock(status_code=200)
        response.json.return_value = {'access_token': 'acme-token', 'workspace_name': 'Acme Inc'}
        with patch.object(ns.requests, 'post', return_value=response):
            redirect = main.notion_oauth_callback(code='c', state=state)   # no ?w= — default context

        with workspaces.use('acme'):
            self.assertEqual(settings_store.read()['notion']['accessToken'], 'acme-token')
        self.assertEqual(settings_store.read()['notion']['accessToken'], '',
                         "the default workspace's connection is untouched")
        self.assertEqual(redirect.headers['location'], '/#/w/acme/settings',
                         'and the browser lands back on that workspace’s settings')


class MappingTests(NotionFixture):
    def test_roles_bind_by_type_and_name(self):
        self.connect()
        roles = ns.resolve_roles(SCHEMA)
        self.assertEqual((roles['title']['name'], roles['key']['name'], roles['status']['name'],
                          roles['status']['type'], roles['priority']['name'], roles['assignee']['name']),
                         ('Name', 'ID', 'Status', 'status', 'Priority', 'Owner'))
        self.assertEqual(roles['status']['source'], 'suggested')
        fields = ns.page_to_fields(page('p-1', 7, 'Rotate certs'), roles)
        self.assertEqual(fields['key'], 'ENG-7')
        self.assertEqual((fields['summary'], fields['jiraStatus'], fields['jiraPriority'], fields['reporter']),
                         ('Rotate certs', 'Backlog', 'P1', 'Dana'))
        self.assertEqual(fields['createdAt'], '2026-08-30T08:00:00.000Z')

    def test_every_property_is_captured_even_when_no_role_maps_it(self):
        """The anti-tailoring guarantee: unmapped columns still reach the ticket."""
        p = page('p-1', 7, 'Rotate certs')
        p['properties']['Sprint'] = {'type': 'relation', 'relation': [{'id': 'a'}, {'id': 'b'}]}
        p['properties']['Story Points'] = {'type': 'number', 'number': 5}
        p['properties']['Service'] = {'type': 'multi_select', 'multi_select': [{'name': 'api'}, {'name': 'web'}]}
        p['properties']['Shipped'] = {'type': 'checkbox', 'checkbox': True}
        p['properties']['Due'] = {'type': 'date', 'date': {'start': '2026-09-20'}}
        p['properties']['Empty'] = {'type': 'rich_text', 'rich_text': []}
        captured = ns.page_to_fields(p, ns.resolve_roles(SCHEMA))['notionProperties']
        self.assertEqual(captured['Sprint'], '2 linked pages')
        self.assertEqual(captured['Story Points'], '5')
        self.assertEqual(captured['Service'], 'api, web')
        self.assertEqual(captured['Shipped'], 'yes')
        self.assertEqual(captured['Due'], '2026-09-20')
        self.assertNotIn('Empty', captured, 'empty values are omitted, not stored as blanks')

    def test_configured_property_that_vanished_is_reported_not_re_guessed(self):
        self.connect()
        settings_store.set_section_fields('notion', {'roles': {'status': 'Gone'}})
        roles = ns.resolve_roles(SCHEMA)
        self.assertIsNone(roles['status']['name'], 'must not silently fall back to a guess')
        self.assertIn('Gone', roles['status']['problem'])
        settings_store.set_section_fields('notion', {'roles': {'status': '-'}})
        self.assertEqual(ns.resolve_roles(SCHEMA)['status']['source'], 'disabled')

    def test_legacy_column_settings_seed_the_role_map(self):
        self.connect()
        settings_store.set_section_fields('notion', {'statusProperty': 'Priority'})
        self.assertEqual(ns.resolve_roles(SCHEMA)['status']['name'], 'Priority')

    def test_priority_is_never_a_random_select(self):
        schema = {'properties': {'Name': {'type': 'title'}, 'Status': {'type': 'select'}, 'Area': {'type': 'select'}}}
        roles = ns.resolve_roles(schema)
        self.assertEqual(roles['status']['name'], 'Status')
        self.assertIsNone(roles['priority']['name'], 'an unrelated select is not a priority')
        settings_store.set_section_fields('notion', {'roles': {'priority': 'Area'}})
        self.assertEqual(ns.resolve_roles(schema)['priority']['name'], 'Area')

    def test_fallback_key_without_unique_id(self):
        schema = {'properties': {'Name': {'type': 'title'}}}
        p = page('1f2a3b4c-5d6e-7f80-91a2-b3c4d5e6f708', 1, 'x')
        del p['properties']['ID']
        self.assertEqual(ns.page_to_fields(p, ns.resolve_roles(schema))['key'], 'NOTION-1F2A3B4C')

    def test_unique_key_never_overwrites_a_taken_one(self):
        taken = {'ENG-7', 'NOTION-1F2A3B4C'}
        self.assertEqual(ns._unique_key('ENG-8', '1f2a3b4c-5d6e-7f80-91a2-b3c4d5e6f708', taken), 'ENG-8')
        self.assertEqual(ns._unique_key('ENG-7', '1f2a3b4c-5d6e-7f80-91a2-b3c4d5e6f708', taken), 'NOTION-1F2A3B4C5D6E'[:19])
        key = ns._unique_key('ENG-7', '1f2a3b4c-5d6e-7f80-91a2-b3c4d5e6f708', taken)
        self.assertNotIn(key, taken)

    def test_attachments_and_nested_blocks(self):
        attachments = []
        blocks = [
            {'type': 'paragraph', 'paragraph': {'rich_text': [{'plain_text': 'See design'}]}, 'has_children': True, 'id': 'b1'},
            {'type': 'image', 'image': {'file': {'url': 'https://s3/shot.png'}, 'caption': [{'plain_text': 'the bug'}]}},
            {'type': 'pdf', 'pdf': {'external': {'url': 'https://x/spec.pdf'}}},
            {'type': 'bookmark', 'bookmark': {'url': 'https://github.com/pr/1'}},
        ]
        children = {'b1': [{'type': 'bulleted_list_item', 'bulleted_list_item': {'rich_text': [{'plain_text': 'nested detail'}]}}]}
        text = ns._blocks_to_text(blocks, attachments, lambda bid: children.get(bid, []))
        self.assertIn('nested detail', text, 'child blocks must be descended into')
        self.assertIn('![', text.replace('[image', '!['), )
        self.assertEqual([(a['kind'], a['url']) for a in attachments],
                         [('image', 'https://s3/shot.png'), ('pdf', 'https://x/spec.pdf'), ('bookmark', 'https://github.com/pr/1')])

    def test_files_property_becomes_attachments(self):
        p = page('p-1', 1, 'x')
        p['properties']['Specs'] = {'type': 'files', 'files': [
            {'name': 'spec.pdf', 'file': {'url': 'https://s3/spec.pdf'}},
            {'name': 'ref', 'external': {'url': 'https://x/ref'}}]}
        self.assertEqual([a['url'] for a in ns.property_attachments(p)], ['https://s3/spec.pdf', 'https://x/ref'])

    def test_blocks_to_text(self):
        blocks = [
            {'type': 'heading_2', 'heading_2': {'rich_text': [{'plain_text': 'Context'}]}},
            {'type': 'paragraph', 'paragraph': {'rich_text': [{'plain_text': 'Certs expire '}, {'plain_text': 'Friday'}]}},
            {'type': 'bulleted_list_item', 'bulleted_list_item': {'rich_text': [{'plain_text': 'prod'}]}},
            {'type': 'numbered_list_item', 'numbered_list_item': {'rich_text': [{'plain_text': 'one'}]}},
            {'type': 'numbered_list_item', 'numbered_list_item': {'rich_text': [{'plain_text': 'two'}]}},
            {'type': 'to_do', 'to_do': {'rich_text': [{'plain_text': 'rotate'}], 'checked': True}},
            {'type': 'image', 'image': {}},
        ]
        self.assertEqual(ns._blocks_to_text(blocks), 'Context\n\nCerts expire Friday\n- prod\n1. one\n2. two\n[x] rotate')

    def test_done_statuses_from_complete_group_or_names(self):
        grouped = {'properties': {'Status': {'type': 'status', 'status': {
            'options': [{'id': 'a', 'name': 'Backlog'}, {'id': 'b', 'name': 'Shipped'}, {'id': 'c', 'name': 'Archived'}],
            'groups': [{'name': 'To-do', 'option_ids': ['a']}, {'name': 'Complete', 'option_ids': ['b', 'c']}]}}}}
        self.assertEqual(ns.done_statuses(grouped, 'Status'), ['Shipped', 'Archived'])
        plain = {'properties': {'State': {'type': 'select', 'select': {'options': [{'name': 'Open'}, {'name': 'Done'}, {'name': 'Closed'}]}}}}
        self.assertEqual(ns.done_statuses(plain, 'State'), ['Done', 'Closed'])
        self.assertEqual(ns.done_statuses(plain, None), [])

    def test_options_for_board_selects(self):
        self.connect()
        with patch.object(ns, '_request', return_value=SCHEMA):
            opts = ns.get_options()
        self.assertEqual([s['name'] for s in opts['statuses']], ['Backlog', 'In progress', 'Done'])
        self.assertEqual(opts['doneStatuses'], ['Done'])
        self.assertEqual(opts['priorities'], ['P0', 'P1', 'P2'])
        self.assertEqual(opts['databaseTitle'], 'Tickets')


class SyncTests(NotionFixture):
    def fake_request(self, pages, bodies, schema=None):
        def _request(method, path, **kwargs):
            if path == '/databases/db-1':
                return schema or SCHEMA
            if path == '/databases/db-1/query':
                return {'results': pages, 'has_more': False}
            if path.startswith('/blocks/'):
                pid = path.split('/')[2]
                self.body_reads.append(pid)
                return {'results': [{'type': 'paragraph', 'paragraph': {'rich_text': [{'plain_text': bodies.get(pid, '')}]}}]}
            if method == 'PATCH' and path.startswith('/pages/'):
                self.patched.append((path, kwargs['json']))
                return {}
            raise AssertionError(path)
        self.patched = []
        self.body_reads = []
        return _request

    def test_import_then_refresh_and_collision(self):
        self.connect()
        db.write({'jiraTickets': {'ENG-2': {'key': 'ENG-2', 'summary': 'A Jira ticket with the same key'}}, 'people': {}, 'teamOptions': []})
        pages = [page('p-1', 1, 'Rotate certs'), page('p-2', 2, 'Colliding key')]
        with patch.object(ns, '_request', side_effect=self.fake_request(pages, {'p-1': 'body one'})), \
             patch.object(ns.auto_categorize, 'classify_many', return_value={'ENG-1': ['security']}), \
             patch.object(ns.content_tags, 'generate', return_value={'ENG-1': ['certificates']}) as gen:
            result = ns.sync_all_tickets(db)
        self.assertEqual(sorted(result['added']), ['ENG-1', 'NOTION-P2'])
        self.assertFalse(result['truncated'])
        tickets = db.read()['jiraTickets']
        t = tickets['ENG-1']
        self.assertEqual((t['source'], t['notionPageId'], t['description'], t['categories'], t['reviewed']),
                         ('notion', 'p-1', 'body one', ['security'], False))
        self.assertEqual(t['contentTags'], ['certificates'])
        self.assertEqual(tickets['ENG-2']['summary'], 'A Jira ticket with the same key', 'Jira ticket untouched by a colliding Notion key')
        self.assertEqual(tickets['NOTION-P2']['notionPageId'], 'p-2')
        self.assertEqual({c['key'] for c in gen.call_args.args[0]}, {'ENG-1', 'NOTION-P2'})

        # Second sync: status moved, body unchanged (same last_edited) -> no body refetch, no tag regen.
        db.update_ticket('ENG-1', {'categories': ['security'], 'team': 'platform', 'notes': [{'text': 'keep me'}]})
        pages[0] = page('p-1', 1, 'Rotate certs', status='In progress')
        with patch.object(ns, '_request', side_effect=self.fake_request(pages, {'p-1': 'SHOULD NOT BE READ'})), \
             patch.object(ns.auto_categorize, 'classify_many', return_value={}), \
             patch.object(ns.content_tags, 'generate', return_value={'NOTION-P2': ['misc']}) as gen:
            result = ns.sync_all_tickets(db)
        self.assertEqual(result['changed'], ['ENG-1'])
        self.assertEqual(result['added'], [])
        self.assertNotIn('p-1', self.body_reads, 'an unedited page body is not refetched')
        t = db.read()['jiraTickets']['ENG-1']
        self.assertEqual((t['jiraStatus'], t['description'], t['team'], t['notes'][0]['text']),
                         ('In progress', 'body one', 'platform', 'keep me'))
        self.assertEqual({c['key'] for c in gen.call_args.args[0]}, {'NOTION-P2'}, 'only the still-untagged ticket goes back to the model')

        # Third sync: page edited -> body refetched.
        pages[0] = page('p-1', 1, 'Rotate certs', status='In progress', edited='2026-09-02T00:00:00.000Z')
        with patch.object(ns, '_request', side_effect=self.fake_request(pages, {'p-1': 'body two'})), \
             patch.object(ns.auto_categorize, 'classify_many', return_value={}), \
             patch.object(ns.content_tags, 'generate', return_value={}):
            ns.sync_all_tickets(db)
        self.assertEqual(db.read()['jiraTickets']['ENG-1']['description'], 'body two')

    def test_description_combines_a_summary_property_with_the_page_body(self):
        self.connect()
        settings_store.set_section_fields('notion', {'roles': {'description': 'Summary'}})
        db.write({'jiraTickets': {}, 'people': {}, 'teamOptions': []})
        p = page('p-1', 1, 'Rotate certs')
        p['properties']['Summary'] = {'type': 'rich_text', 'rich_text': [{'plain_text': 'certs expire Friday'}]}
        schema = {**SCHEMA, 'properties': {**SCHEMA['properties'], 'Summary': {'type': 'rich_text'}}}
        with patch.object(ns, '_request', side_effect=self.fake_request([p], {'p-1': 'body detail'}, schema)), \
             patch.object(ns.auto_categorize, 'classify_many', return_value={}), \
             patch.object(ns.content_tags, 'generate', return_value={}):
            ns.sync_all_tickets(db)
        self.assertEqual(db.read()['jiraTickets']['ENG-1']['description'], 'certs expire Friday\n\nbody detail')

    def test_finished_tickets_cost_no_body_read_and_no_classification(self):
        """A database with thousands of archived rows must not spend a page
        read and a model call on each of them."""
        self.connect()
        db.write({'jiraTickets': {}, 'people': {}, 'teamOptions': []})
        pages = [page('p-1', 1, 'open one'), page('p-2', 2, 'archived one', status='Done')]
        with patch.object(ns, '_request', side_effect=self.fake_request(pages, {'p-1': 'body'})), \
             patch.object(ns.auto_categorize, 'classify_many', return_value={'ENG-1': ['security']}) as classify, \
             patch.object(ns.content_tags, 'generate', return_value={}):
            ns.sync_all_tickets(db)
        self.assertEqual(self.body_reads, ['p-1'], 'only the open page body is fetched')
        self.assertEqual([c['key'] for c in classify.call_args.args[0]], ['ENG-1'])
        self.assertEqual(db.read()['jiraTickets']['ENG-2']['jiraStatus'], 'Done', 'the finished ticket is still imported')

    def test_stranded_open_tickets_get_one_category_retry(self):
        self.connect()
        db.write({'jiraTickets': {
            'ENG-1': {'key': 'ENG-1', 'source': 'notion', 'notionPageId': 'p-1', 'categories': [], 'reviewed': False, 'description': 'd', 'notionBodyFetched': True, 'notionLastEdited': '2026-09-01T10:00:00.000Z', 'contentTags': ['x'], 'contentTagSourceHash': 'stale'},
            'ENG-2': {'key': 'ENG-2', 'source': 'notion', 'notionPageId': 'p-2', 'categories': [], 'reviewed': False, 'description': 'd', 'notionBodyFetched': True, 'notionLastEdited': '2026-09-01T10:00:00.000Z'},
            'ENG-3': {'key': 'ENG-3', 'source': 'notion', 'notionPageId': 'p-3', 'categories': [], 'reviewed': True, 'description': 'd', 'notionBodyFetched': True, 'notionLastEdited': '2026-09-01T10:00:00.000Z'},
            'ENG-4': {'key': 'ENG-4', 'source': 'notion', 'notionPageId': 'p-4', 'categories': [], 'reviewed': False, 'description': 'd', 'notionBodyFetched': True, 'notionLastEdited': '2026-09-01T10:00:00.000Z', 'categoryGuessAt': '2026-09-14T00:00:00+00:00'},
        }, 'people': {}, 'teamOptions': []})
        pages = [page('p-1', 1, 'open'), page('p-2', 2, 'finished', status='Done'), page('p-3', 3, 'human reviewed'), page('p-4', 4, 'already asked')]
        with patch.object(ns, '_request', side_effect=self.fake_request(pages, {})), \
             patch.object(ns.auto_categorize, 'classify_many', return_value={'ENG-1': ['security']}) as classify, \
             patch.object(ns.content_tags, 'generate', return_value={}):
            result = ns.sync_all_tickets(db)
        self.assertEqual([c['key'] for c in classify.call_args.args[0]], ['ENG-1'],
                         'only the open, unreviewed, never-guessed ticket is asked')
        self.assertEqual(result['categorized'], ['ENG-1'])
        t = db.read()['jiraTickets']
        self.assertEqual((t['ENG-1']['categories'], t['ENG-1']['suggestedCategories']), (['security'], ['security']))
        self.assertTrue(t['ENG-1']['categoryGuessAt'])
        self.assertFalse(t['ENG-1']['reviewed'], 'a guess is not a review')
        for key in ('ENG-2', 'ENG-3', 'ENG-4'):
            self.assertEqual(t[key]['categories'], [], key)

    def test_a_ticket_imported_while_the_classifier_is_down_is_retried_later(self):
        """The regression that made the retry unreachable: stamping
        categoryGuessAt at import meant a failed classification was
        indistinguishable from an honest "nothing fits", forever."""
        self.connect()
        db.write({'jiraTickets': {}, 'people': {}, 'teamOptions': []})
        pages = [page('p-1', 1, 'open one')]
        with patch.object(ns, '_request', side_effect=self.fake_request(pages, {})), \
             patch.object(ns.auto_categorize, 'classify_many', side_effect=RuntimeError('claude signed out')), \
             patch.object(ns.content_tags, 'generate', return_value={}):
            result = ns.sync_all_tickets(db)
        self.assertIn('signed out', result['categoryError'])
        self.assertNotIn('categoryGuessAt', db.read()['jiraTickets']['ENG-1'], 'a failed call must leave no stamp')

        with patch.object(ns, '_request', side_effect=self.fake_request(pages, {})), \
             patch.object(ns.auto_categorize, 'classify_many', return_value={'ENG-1': ['security']}) as classify, \
             patch.object(ns.content_tags, 'generate', return_value={}):
            ns.sync_all_tickets(db)
        self.assertEqual([c['key'] for c in classify.call_args.args[0]], ['ENG-1'], 'retried on the next sync')
        self.assertEqual(db.read()['jiraTickets']['ENG-1']['categories'], ['security'])

        # An honest "nothing fits" IS stamped, so it is not re-asked forever.
        db.update_ticket('ENG-1', {'categories': [], 'categoryGuessAt': None})
        db.update_ticket('ENG-1', {'categoryGuessAt': ''})
        with patch.object(ns, '_request', side_effect=self.fake_request(pages, {})), \
             patch.object(ns.auto_categorize, 'classify_many', return_value={'ENG-1': []}), \
             patch.object(ns.content_tags, 'generate', return_value={}):
            ns.sync_all_tickets(db)
        self.assertTrue(db.read()['jiraTickets']['ENG-1']['categoryGuessAt'])
        with patch.object(ns, '_request', side_effect=self.fake_request(pages, {})), \
             patch.object(ns.auto_categorize, 'classify_many', return_value={}) as classify, \
             patch.object(ns.content_tags, 'generate', return_value={}):
            ns.sync_all_tickets(db)
        classify.assert_not_called()

    def test_pagination_reports_truncation_and_takes_newest_first(self):
        self.connect()
        db.write({'jiraTickets': {}, 'people': {}, 'teamOptions': []})
        sent = []
        def _request(method, path, **kwargs):
            if path == '/databases/db-1':
                return SCHEMA
            if path == '/databases/db-1/query':
                sent.append(kwargs['json'])
                return {'results': [], 'has_more': True, 'next_cursor': 'c'}
            return {'results': []}
        with patch.object(ns, '_request', side_effect=_request), \
             patch.object(ns, 'MAX_QUERY_PAGES', 3), \
             patch.object(ns.content_tags, 'generate', return_value={}):
            result = ns.sync_all_tickets(db)
        self.assertTrue(result['truncated'], 'hitting the ceiling is reported, not silent')
        self.assertEqual(len(sent), 3)
        self.assertEqual(sent[0]['sorts'], [{'timestamp': 'created_time', 'direction': 'descending'}],
                         'newest first, so an interrupted sync keeps current work')

    def test_tag_failure_does_not_block_field_refresh(self):
        self.connect()
        db.write({'jiraTickets': {}, 'people': {}, 'teamOptions': []})
        with patch.object(ns, '_request', side_effect=self.fake_request([page('p-1', 1, 'x')], {})), \
             patch.object(ns.auto_categorize, 'classify', return_value=[]), \
             patch.object(ns.content_tags, 'generate', side_effect=RuntimeError('claude down')):
            result = ns.sync_all_tickets(db)
        self.assertEqual(result['added'], ['ENG-1'])
        self.assertIn('claude down', result['tagError'])

    def test_source_aware_status_and_priority_pushes(self):
        self.connect()
        db.write({'jiraTickets': {
            'ENG-1': {'key': 'ENG-1', 'source': 'notion', 'notionPageId': 'p-1', 'jiraStatus': 'Backlog', 'jiraPriority': 'P1'},
            'JIRA-1': {'key': 'JIRA-1', 'jiraStatus': 'Backlog'},
        }, 'people': {}, 'teamOptions': []})
        with patch.object(ns, '_request', side_effect=self.fake_request([], {})):
            res = main.post_jira_transition('ENG-1', {'transitionId': '', 'statusName': 'Done'})
            self.assertTrue(res['ok'], res)
            res = main.patch_jira_priority('ENG-1', {'priority': 'P0'})
            self.assertTrue(res['ok'], res)
        self.assertEqual(self.patched, [
            ('/pages/p-1', {'properties': {'Status': {'status': {'name': 'Done'}}}}),
            ('/pages/p-1', {'properties': {'Priority': {'select': {'name': 'P0'}}}}),
        ])
        t = db.read()['jiraTickets']['ENG-1']
        self.assertEqual((t['jiraStatus'], t['jiraPriority']), ('Done', 'P0'))
        # A Jira ticket still goes down the Jira path (unconfigured here -> its own error, no Notion call).
        with patch.object(main.jira_sync, 'configured', return_value=False):
            res = main.post_jira_transition('JIRA-1', {'transitionId': '1', 'statusName': 'Done'})
        self.assertFalse(res['ok'])
        self.assertEqual(len(self.patched), 2)

    def test_sync_all_merges_trackers_and_isolates_failures(self):
        self.connect()
        with patch.object(main.jira_sync, 'configured', return_value=True), \
             patch.object(main.jira_sync, 'sync_all_tickets', side_effect=RuntimeError('jira 401')), \
             patch.object(ns, 'sync_all_tickets', return_value={'checked': 3, 'updated': 1, 'changed': ['ENG-1'], 'added': [], 'tagged': [], 'tagError': None}):
            result = main.sync_all()
        self.assertTrue(result['ok'])
        self.assertEqual(result['synced'], ['notion'])
        self.assertEqual(result['errors'], {'jira': 'jira 401'})
        self.assertEqual(result['checked'], 3)
        ns.disconnect()
        with patch.object(main.jira_sync, 'configured', return_value=False):
            self.assertFalse(main.sync_all()['ok'])

    def test_concurrent_sync_is_refused(self):
        self.connect()
        with main.sync_lock_for():
            self.assertIn('already running', main.sync_all()['error'])
            self.assertIn('already running', main.sync_notion()['error'])
        with patch.object(ns, 'sync_all_tickets', return_value={'checked': 0, 'updated': 0, 'changed': [], 'added': [], 'tagged': [], 'tagError': None}):
            self.assertTrue(main.sync_notion()['ok'], 'lock released afterwards')


# A sprints database whose status GROUPS are deliberately repurposed — the
# group called "Current" holds the option "Past" — because the reference
# workspace renamed and reused them. Nothing may key off a group name.
SPRINT_DB = {'title': [{'plain_text': 'Sprints'}], 'properties': {
    'Sprint name': {'type': 'title'},
    'Sprint status': {'type': 'status', 'status': {
        'options': [{'id': 'o1', 'name': 'Current'}, {'id': 'o2', 'name': 'Past'}, {'id': 'o3', 'name': 'Future'}],
        'groups': [{'name': 'Current', 'option_ids': ['o2']}, {'name': 'Future', 'option_ids': ['o1']},
                   {'name': 'Complete', 'option_ids': ['o3']}]}},
    'Dates': {'type': 'date'},
}}


def sprint_page(pid, name, status, start='', end=''):
    return {'id': pid, 'url': 'https://notion.so/' + pid, 'properties': {
        'Sprint name': {'type': 'title', 'title': [{'plain_text': name}]},
        'Sprint status': {'type': 'status', 'status': ({'name': status} if status else None)},
        'Dates': {'type': 'date', 'date': ({'start': start, 'end': end} if start else None)},
    }}


def frozen(day):
    """Pin today. Every sprint state is relative to it, so a test that let the
    real clock through would pass or fail depending on the date it ran."""
    class _Date(datetime.date):
        @classmethod
        def today(cls):
            return datetime.date.fromisoformat(day)
    return patch.object(ns.datetime, 'date', _Date)


class SprintTests(NotionFixture):
    """Sprints are modelled differently by every team, so nothing here may key
    off a particular property name, option name or status group."""

    def schema_with_sprint(self, kind='relation', extra=None):
        prop = ({'type': 'relation', 'relation': {'database_id': 'sprint-db'}} if kind == 'relation'
                else {'type': 'select', 'select': {'options': [{'name': 'Sprint 36'}]}})
        return {**SCHEMA, 'properties': {**SCHEMA['properties'], 'Sprint': prop, **(extra or {})}}

    def reader(self, sprint_rows, ticket_pages=(), schema=None):
        def _request(method, path, **kwargs):
            if path == '/databases/db-1':
                return schema if schema is not None else self.schema_with_sprint()
            if path == '/databases/db-1/query':
                return {'results': list(ticket_pages), 'has_more': False}
            if path == '/databases/sprint-db':
                return SPRINT_DB
            if path == '/databases/sprint-db/query':
                return {'results': sprint_rows, 'has_more': False}
            raise AssertionError('unexpected request: ' + path)
        return _request

    def sprint_roles(self, schema, name='Sprint'):
        """Roles with the sprint role bound explicitly. The sprint role is never
        name-suggested any more (discovery is the only unconfigured path), so
        tests that are about state, markers or tickets — not about discovery —
        configure it the way a user would."""
        settings_store.set_section_fields('notion', {'roles': {'sprint': name}})
        return ns.resolve_roles(schema)

    def read(self, rows):
        schema = self.schema_with_sprint()
        with patch.object(ns, '_request', side_effect=self.reader(rows)):
            return ns.read_sprint_context(schema, self.sprint_roles(schema))

    # ---- state ----

    def test_dates_decide_the_state_whatever_the_status_is_called(self):
        """No marker known: a range covering today is running, in any
        workspace and any language — and the option name and its (repurposed)
        group are both ignored."""
        self.connect()
        rows = [sprint_page('s35', 'Sprint 35', 'Current', '2026-08-18', '2026-08-31'),
                sprint_page('s36', 'Sprint 36', 'Past', '2026-09-01', '2026-09-20'),
                sprint_page('s37', 'Sprint 37', 'Current', '2026-09-21', '2026-10-04')]
        with frozen('2026-09-15'):
            sprints = self.read(rows)['sprints']
        self.assertEqual(sprints['s36']['state'], 'active', 'the range covering today wins over the word “Past”')
        self.assertEqual(sprints['s35']['state'], 'closed', 'ended, though its option sits in a group named “Current”')
        self.assertEqual(sprints['s37']['state'], 'future')
        self.assertEqual(sprints['s36']['rawStatus'], 'Past', 'the tracker’s own word is kept for display')
        self.assertEqual((sprints['s36']['start'], sprints['s36']['end']), ('2026-09-01', '2026-09-20'))

    def test_a_stored_marker_survives_the_gap_between_two_sprints(self):
        """The day after one sprint ends and before the next begins, dates
        say nothing — only the marker keeps a sprint running."""
        self.connect()
        settings_store.set_section_fields('notion', {'sprintActiveMarker': 'Current',
                                                     'sprintActiveMarkerSource': 'confirmed'})
        rows = [sprint_page('s36', 'Sprint 36', 'Current', '2026-09-01', '2026-09-14'),
                sprint_page('s37', 'Sprint 37', 'Future', '2026-09-16', '2026-09-29')]
        with frozen('2026-09-15'):
            sprints = self.read(rows)['sprints']
        self.assertEqual(sprints['s36']['state'], 'active', 'the marker outranks an end date of yesterday')
        self.assertEqual(sprints['s37']['state'], 'future')

    def test_undated_sprints_fall_back_to_past_words_only(self):
        self.connect()
        rows = [sprint_page('s1', 'Cycle A', 'Finished'), sprint_page('s2', 'Cycle B', 'Planned'),
                sprint_page('s3', 'Cycle C', '')]
        with frozen('2026-09-15'):
            sprints = self.read(rows)['sprints']
        self.assertEqual(sprints['s1']['state'], 'closed')
        self.assertEqual(sprints['s2']['state'], 'future', 'an undated sprint is assumed to be ahead')
        self.assertEqual(sprints['s3']['state'], 'future')
        self.assertEqual((sprints['s3']['start'], sprints['s3']['end']), ('', ''), 'undated stays undated')

    def test_derive_state_matrix(self):
        cases = [
            ('Current', '', '', 'Current', 'active'),          # marker hit, no dates at all
            ('current', '2026-01-01', '2026-01-31', 'Current', 'active'),  # marker hit beats stale dates
            ('Past', '2026-09-10', '2026-09-20', 'Current', 'active'),     # covers today
            ('Whatever', '2026-09-16', '2026-09-30', 'Current', 'future'),
            ('Whatever', '2026-08-01', '2026-09-14', 'Current', 'closed'),
            ('Done', '', '', '', 'closed'),
            ('Anything else', '', '', '', 'future'),
        ]
        for raw, start, end, marker, expected in cases:
            self.assertEqual(ns.derive_state(raw, start, end, marker, today='2026-09-15'), expected,
                             f'{raw!r} {start}..{end} marker={marker!r}')

    # ---- the active marker ----

    def test_marker_is_inferred_only_from_agreement(self):
        def rows(*triples):
            return [{'name': n, 'rawStatus': s, 'start': a, 'end': b} for n, s, a, b in triples]
        one = rows(('36', 'Current', '2026-09-10', '2026-09-20'), ('35', 'Past', '2026-08-01', '2026-08-31'))
        self.assertEqual(ns.infer_active_marker(one, today='2026-09-15'), 'Current')
        agree = rows(('36a', 'Live', '2026-09-10', '2026-09-20'), ('36b', 'Live', '2026-09-14', '2026-09-16'))
        self.assertEqual(ns.infer_active_marker(agree, today='2026-09-15'), 'Live')
        disagree = rows(('36a', 'Live', '2026-09-10', '2026-09-20'), ('36b', 'Planned', '2026-09-14', '2026-09-16'))
        self.assertEqual(ns.infer_active_marker(disagree, today='2026-09-15'), '',
                         'a guess that could be wrong is worse than none')
        none = rows(('35', 'Past', '2026-08-01', '2026-08-31'), ('37', 'Future', '2026-09-20', '2026-09-30'))
        self.assertEqual(ns.infer_active_marker(none, today='2026-09-15'), '')
        self.assertEqual(ns.infer_active_marker(rows(('36', '', '2026-09-10', '2026-09-20')), today='2026-09-15'), '')

    def test_inferred_marker_is_stored_and_re_inferred_but_never_over_a_confirmed_one(self):
        self.connect()
        rows = [sprint_page('s36', 'Sprint 36', 'Current', '2026-09-10', '2026-09-20')]
        with frozen('2026-09-15'):
            marker = self.read(rows)['marker']
        self.assertEqual((marker['value'], marker['source'], marker['inferredFrom']),
                         ('Current', 'inferred', 'Sprint 36'))
        stored = settings_store.read()['notion']
        self.assertEqual((stored['sprintActiveMarker'], stored['sprintActiveMarkerSource']), ('Current', 'inferred'))

        # The workspace renames the option: an inferred marker follows.
        ns.invalidate_cache()
        with frozen('2026-09-15'):
            marker = self.read([sprint_page('s36', 'Sprint 36', 'Live', '2026-09-10', '2026-09-20')])['marker']
        self.assertEqual((marker['value'], marker['source']), ('Live', 'inferred'))

        # A confirmed one does not.
        settings_store.set_section_fields('notion', {'sprintActiveMarker': 'Current',
                                                     'sprintActiveMarkerSource': 'confirmed'})
        ns.invalidate_cache()
        with frozen('2026-09-15'):
            marker = self.read([sprint_page('s36', 'Sprint 36', 'Live', '2026-09-10', '2026-09-20')])['marker']
        self.assertEqual((marker['value'], marker['source']), ('Current', 'confirmed'))
        self.assertEqual(settings_store.read()['notion']['sprintActiveMarker'], 'Current')

    def test_a_marker_that_cannot_be_inferred_today_leaves_the_stored_one_alone(self):
        self.connect()
        settings_store.set_section_fields('notion', {'sprintActiveMarker': 'Current',
                                                     'sprintActiveMarkerSource': 'inferred'})
        with frozen('2026-09-15'):  # gap day: nothing covers today, so nothing to infer from
            marker = self.read([sprint_page('s36', 'Sprint 36', 'Current', '2026-09-01', '2026-09-14')])['marker']
        self.assertEqual((marker['value'], marker['source'], marker['inferredFrom']), ('Current', 'inferred', ''))

    def test_put_settings_confirms_and_clears_the_marker(self):
        self.connect()
        main.put_settings({'notion': {'sprintActiveMarker': 'Current'}})
        stored = settings_store.read()['notion']
        self.assertEqual((stored['sprintActiveMarker'], stored['sprintActiveMarkerSource']), ('Current', 'confirmed'))
        main.put_settings({'notion': {'sprintActiveMarker': ''}})
        stored = settings_store.read()['notion']
        self.assertEqual((stored['sprintActiveMarker'], stored['sprintActiveMarkerSource']), ('', ''),
                         'blank hands the question back to inference')
        main.put_settings({'notion': {'databaseId': 'db-1'}})
        self.assertEqual(settings_store.read()['notion']['sprintActiveMarkerSource'], '',
                         'an unrelated save says nothing about the marker')

    # ---- discovery ----

    def test_fill_rate_separates_the_live_sprint_relation_from_an_empty_one(self):
        """Two relations onto the same sprints database score identically on
        shape, and neither is called anything recognizable; only the tickets
        say which one the team actually uses."""
        self.connect()
        relation = {'type': 'relation', 'relation': {'database_id': 'sprint-db'}}
        schema = {**SCHEMA, 'properties': {**SCHEMA['properties'],
                                           'Timebox': relation, 'Previous timeboxes': relation}}
        rows = [sprint_page('s36', 'Sprint 36', 'Current', '2026-09-10', '2026-09-20')]
        pages = []
        for i in range(10):
            page_i = page(f'p-{i}', i, 'x')
            page_i['properties']['Timebox'] = {'type': 'relation', 'relation': [{'id': 's36'}] if i < 3 else []}
            page_i['properties']['Previous timeboxes'] = {'type': 'relation', 'relation': []}
            pages.append(page_i)
        with patch.object(ns, '_request', side_effect=self.reader(rows, pages, schema)):
            blind = ns.discover_sprint_candidates(schema)
            informed = ns.discover_sprint_candidates(schema, sample_pages=pages)
            roles = ns.resolve_roles_with_discovery(schema, sample_pages=pages)
        self.assertEqual(blind[0]['property'], 'Previous timeboxes', 'on shape alone the wrong one wins the tie')
        self.assertEqual(informed[0]['property'], 'Timebox')
        by_name = {c['property']: c for c in informed}
        self.assertEqual(by_name['Timebox']['fillRate'], 0.3)
        self.assertEqual(by_name['Previous timeboxes']['fillRate'], 0.0)
        self.assertEqual(by_name['Timebox']['score'] - by_name['Previous timeboxes']['score'], 4,
                         '30% filled is the lowest fill band (+1) against an empty relation (-3)')
        self.assertEqual(by_name['Timebox']['target'], 'Sprints')
        self.assertEqual((roles['sprint']['name'], roles['sprint']['source']), ('Timebox', 'discovered'))
        self.assertTrue(roles['sprint']['why'], 'Settings explains the guess instead of asserting it')

    # ---- tickets ----

    def test_ticket_takes_the_active_sprint_then_the_latest(self):
        self.connect()
        rows = [sprint_page('s36', 'Sprint 36', 'Current', '2026-09-10', '2026-09-20'),
                sprint_page('s35', 'Sprint 35', 'Past', '2026-08-18', '2026-08-31'),
                sprint_page('s34', 'Sprint 34', 'Past', '2026-08-01', '2026-08-14')]
        schema = self.schema_with_sprint()
        roles = self.sprint_roles(schema)
        with frozen('2026-09-15'):
            with patch.object(ns, '_request', side_effect=self.reader(rows)):
                sprints = ns.read_sprints(schema, roles)
        p = page('p-1', 1, 'carry-over')
        p['properties']['Sprint'] = {'type': 'relation', 'relation': [{'id': 's36'}, {'id': 's35'}]}  # Notion's order
        got = ns.ticket_sprint(p, roles, sprints)
        self.assertEqual((got['sprint'], got['sprintState']), ('Sprint 36', 'active'))
        self.assertEqual(got['sprintIds'], ['s35', 's36'], 'every linked sprint is kept, in a stable order')
        self.assertEqual(got['sprintNames'], ['Sprint 35', 'Sprint 36'])
        self.assertNotIn('sprintIsCurrent', got)

        p['properties']['Sprint'] = {'type': 'relation', 'relation': [{'id': 's34'}, {'id': 's35'}]}
        got = ns.ticket_sprint(p, roles, sprints)
        self.assertEqual((got['sprint'], got['sprintState']), ('Sprint 35', 'closed'), 'no active one: the latest')

        p['properties']['Sprint'] = {'type': 'relation', 'relation': []}
        self.assertEqual(ns.ticket_sprint(p, roles, sprints),
                         {'sprint': '', 'sprintIds': [], 'sprintNames': [], 'sprintState': ''})

    def test_a_non_relation_sprint_column_yields_the_empty_shape(self):
        """Select- and date-valued sprint columns are a shape this iteration
        does not model; a half-answer would be worse than none."""
        self.connect()
        schema = self.schema_with_sprint('select')
        roles = self.sprint_roles(schema)  # a user explicitly mapping a select column
        self.assertEqual(ns.read_sprints(schema, roles), {}, 'no relation, no sprints database to read')
        self.assertEqual(ns.discover_sprint_candidates(schema), [], 'and discovery never proposes one either')
        p = page('p-1', 1, 'x')
        p['properties']['Sprint'] = {'type': 'select', 'select': {'name': 'Sprint 36'}}
        self.assertEqual(ns.ticket_sprint(p, roles, {}),
                         {'sprint': '', 'sprintIds': [], 'sprintNames': [], 'sprintState': ''})

    def test_no_sprint_role_costs_nothing(self):
        self.connect()
        roles = ns.resolve_roles(SCHEMA)
        self.assertIsNone(roles['sprint']['name'])
        self.assertEqual(ns.read_sprints(SCHEMA, roles), {})
        self.assertEqual(ns.ticket_sprint(page('p-1', 1, 'x'), roles, {})['sprint'], '')


    # ---- discovery is by shape and data, never by name ----

    def multi_reader(self, schema, ticket_pages, databases):
        """`databases`: {db_id: (db_schema, rows)}."""
        def _request(method, path, **kwargs):
            if path == '/databases/db-1':
                return schema
            if path == '/databases/db-1/query':
                return {'results': list(ticket_pages), 'has_more': False}
            for db_id, (db_schema, rows) in databases.items():
                if path == f'/databases/{db_id}':
                    return db_schema
                if path == f'/databases/{db_id}/query':
                    return {'results': rows, 'has_more': False}
            raise AssertionError('unexpected request: ' + path)
        return _request

    def test_the_real_world_naming_is_resolved_by_data_not_by_name(self):
        """The reference workspace: a populated "Sprint" and an empty "Previous
        Sprints", both pointing at the same database. Neither name decides."""
        self.connect()
        relation = {'type': 'relation', 'relation': {'database_id': 'sprint-db'}}
        schema = {**SCHEMA, 'properties': {**SCHEMA['properties'], 'Previous Sprints': relation, 'Sprint': relation}}
        rows = [sprint_page('s36', 'Sprint 36', 'Current', '2026-09-10', '2026-09-20'),
                sprint_page('s35', 'Sprint 35', 'Past', '2026-08-25', '2026-09-08'),
                sprint_page('s34', 'Sprint 34', 'Past', '2026-08-11', '2026-08-24')]
        pages = []
        for i in range(10):
            pg = page(f'p-{i}', i, 'x')
            pg['properties']['Sprint'] = {'type': 'relation', 'relation': [{'id': 's36'}]}
            pg['properties']['Previous Sprints'] = {'type': 'relation', 'relation': []}
            pages.append(pg)
        with patch.object(ns, '_request', side_effect=self.reader(rows, pages, schema)):
            roles = ns.resolve_roles_with_discovery(schema, sample_pages=pages)
            cheap = ns.resolve_roles(schema)
        self.assertIsNone(cheap['sprint']['name'], 'no name-based suggestion exists for the sprint role')
        self.assertEqual((roles['sprint']['name'], roles['sprint']['source']), ('Sprint', 'discovered'))
        self.assertTrue(any('100%' in r for r in roles['sprint']['why']))

    def test_a_named_select_never_preempts_a_dated_relation(self):
        """A select called "Milestone" used to win on its name alone, leaving a
        "Ciclo" relation to real dated cycles unmapped and the board sprintless."""
        self.connect()
        schema = {**SCHEMA, 'properties': {**SCHEMA['properties'],
            'Milestone': {'type': 'select', 'select': {'options': [{'name': 'v1'}, {'name': 'v2'}]}},
            'Ciclo': {'type': 'relation', 'relation': {'database_id': 'sprint-db'}}}}
        rows = [sprint_page('c1', 'Ciclo 1', 'Activo', '2026-09-10', '2026-09-23'),
                sprint_page('c2', 'Ciclo 0', 'Cerrado', '2026-08-27', '2026-09-09'),
                sprint_page('c3', 'Ciclo -1', 'Cerrado', '2026-08-13', '2026-08-26')]
        pages = []
        for i in range(6):
            pg = page(f'p-{i}', i, 'x'); pg['properties']['Ciclo'] = {'type': 'relation', 'relation': [{'id': 'c1'}]}
            pages.append(pg)
        with patch.object(ns, '_request', side_effect=self.reader(rows, pages, schema)):
            roles = ns.resolve_roles_with_discovery(schema, sample_pages=pages)
            candidates = ns.discover_sprint_candidates(schema, sample_pages=pages)
        self.assertEqual((roles['sprint']['name'], roles['sprint']['type']), ('Ciclo', 'relation'))
        self.assertEqual([c['property'] for c in candidates], ['Ciclo'], 'a select is never a candidate this iteration')

    def test_short_tiled_ranges_beat_long_epic_ranges_and_a_bound_role_is_excluded(self):
        """Both databases are dated, both have a status, both are linked from
        tickets. Iterations are short and tile time; epics run for months and
        overlap. And a property already serving the epic role is never also
        offered as the sprint."""
        self.connect()
        schema = {**SCHEMA, 'properties': {**SCHEMA['properties'],
            'Ciclo': {'type': 'relation', 'relation': {'database_id': 'cycle-db'}},
            'Epic': {'type': 'relation', 'relation': {'database_id': 'epic-db'}}}}
        cycles = [sprint_page('c1', 'C1', 'Live', '2026-09-10', '2026-09-23'), sprint_page('c2', 'C0', 'Done', '2026-08-27', '2026-09-09'),
                  sprint_page('c3', 'C-1', 'Done', '2026-08-13', '2026-08-26'), sprint_page('c4', 'C-2', 'Done', '2026-07-30', '2026-08-12')]
        epics = [sprint_page('e1', 'Platform', 'Live', '2026-06-01', '2026-10-31'), sprint_page('e2', 'Billing', 'Live', '2026-07-01', '2026-12-15'),
                 sprint_page('e3', 'Onboarding', 'Done', '2026-03-01', '2026-07-30'), sprint_page('e4', 'Mobile', 'Planned', '2026-09-01', '2027-02-28')]
        pages = []
        for i in range(10):
            pg = page(f'p-{i}', i, 'x')
            pg['properties']['Ciclo'] = {'type': 'relation', 'relation': [{'id': 'c1'}]}
            pg['properties']['Epic'] = {'type': 'relation', 'relation': [{'id': 'e1'}] if i < 6 else []}
            pages.append(pg)
        dbs = {'cycle-db': ({**SPRINT_DB, 'title': [{'plain_text': 'Cycles'}]}, cycles),
               'epic-db': ({**SPRINT_DB, 'title': [{'plain_text': 'Epics'}]}, epics)}
        with patch.object(ns, '_request', side_effect=self.multi_reader(schema, pages, dbs)):
            open_field = ns.discover_sprint_candidates(schema, sample_pages=pages)
            roles = ns.resolve_roles_with_discovery(schema, sample_pages=pages)
        by = {c['property']: c for c in open_field}
        self.assertGreater(by['Ciclo']['score'], by['Epic']['score'] + 2, (by['Ciclo']['score'], by['Epic']['score']))
        self.assertTrue(any('like iterations' in r for r in by['Ciclo']['reasons']))
        self.assertTrue(any('more like epics' in r for r in by['Epic']['reasons']))
        self.assertEqual(roles['epic']['name'], 'Epic', 'the epic role binds by its own hint')
        self.assertEqual(roles['sprint']['name'], 'Ciclo')
        with patch.object(ns, '_request', side_effect=self.multi_reader(schema, pages, dbs)):
            excluded = ns.discover_sprint_candidates(schema, sample_pages=pages, exclude={'Epic'})
        self.assertEqual([c['property'] for c in excluded], ['Ciclo'], 'one column never serves two roles')

    def test_a_genuine_tie_is_reported_not_broken_by_name(self):
        self.connect()
        schema = {**SCHEMA, 'properties': {**SCHEMA['properties'],
            'Alpha': {'type': 'relation', 'relation': {'database_id': 'a-db'}},
            'Beta': {'type': 'relation', 'relation': {'database_id': 'b-db'}}}}
        rows = [sprint_page('x1', 'One', 'Live', '2026-09-10', '2026-09-23'), sprint_page('x2', 'Two', 'Done', '2026-08-27', '2026-09-09'),
                sprint_page('x3', 'Three', 'Done', '2026-08-13', '2026-08-26')]
        pages = []
        for i in range(4):
            pg = page(f'p-{i}', i, 'x')
            pg['properties']['Alpha'] = {'type': 'relation', 'relation': [{'id': 'x1'}]}
            pg['properties']['Beta'] = {'type': 'relation', 'relation': [{'id': 'x1'}]}
            pages.append(pg)
        dbs = {'a-db': (SPRINT_DB, rows), 'b-db': (SPRINT_DB, rows)}
        with patch.object(ns, '_request', side_effect=self.multi_reader(schema, pages, dbs)):
            roles = ns.resolve_roles_with_discovery(schema, sample_pages=pages)
        self.assertIsNone(roles['sprint']['name'])
        self.assertEqual(roles['sprint']['source'], 'ambiguous')
        self.assertIn('Alpha', roles['sprint']['problem']); self.assertIn('Beta', roles['sprint']['problem'])
        self.assertEqual(sorted(roles['sprint']['candidates']), ['Alpha', 'Beta'])

    def test_transient_errors_are_not_cached_as_unreadable(self):
        self.connect()
        ns.invalidate_cache()
        def rate_limited(method, path, **kwargs):
            err = ns.NotionError('429'); err.status = 429; raise err
        with patch.object(ns, '_request', side_effect=rate_limited):
            self.assertIsNone(ns._database_shape('sprint-db'))
        self.assertNotIn(ns._cache_key('sprint-db'), ns._timebox_cache, 'a 429 must be retried next time, not remembered')
        def not_shared(method, path, **kwargs):
            err = ns.NotionError('404'); err.status = 404; raise err
        with patch.object(ns, '_request', side_effect=not_shared):
            self.assertIsNone(ns._database_shape('sprint-db'))
        self.assertIn(ns._cache_key('sprint-db'), ns._timebox_cache, 'a 404 is definitive and is remembered')
        ns.invalidate_cache()
        with patch.object(ns, '_request', side_effect=ns.requests.ConnectionError('down')):
            self.assertIsNone(ns._database_shape('sprint-db'), 'a network error is swallowed, not raised')

    def test_sprint_rows_are_re_read_on_every_options_read(self):
        self.connect()
        first = [sprint_page('s36', 'Sprint 36', 'Current', '2026-09-10', '2026-09-20')]
        second = first + [sprint_page('s37', 'Sprint 37', 'Future', '2026-09-21', '2026-10-04')]
        pg = page('p-1', 1, 'x'); pg['properties']['Sprint'] = {'type': 'relation', 'relation': [{'id': 's36'}]}
        self.sprint_roles(self.schema_with_sprint())
        with frozen('2026-09-15'):
            with patch.object(ns, '_request', side_effect=self.reader(first, [pg])):
                self.assertEqual(len(ns.get_options()['sprints']), 1)
            with patch.object(ns, '_request', side_effect=self.reader(second, [pg])):
                self.assertEqual(len(ns.get_options()['sprints']), 2, 'a sprint created since the last read appears without a restart')

    def test_a_lone_start_date_is_a_one_day_box(self):
        self.assertEqual(ns.derive_state('', '2020-01-01', '', '', today='2026-09-15'), 'closed',
                         'a start with no end must never be "active forever"')
        self.assertEqual(ns.derive_state('', '2026-09-15', '', '', today='2026-09-15'), 'active')
        self.assertEqual(ns.derive_state('', '2026-09-16', '', '', today='2026-09-15'), 'future')

    def test_put_settings_ignores_a_client_sent_source_flag(self):
        self.connect()
        main.put_settings({'notion': {'sprintActiveMarkerSource': 'confirmed'}})
        self.assertEqual(settings_store.read()['notion']['sprintActiveMarkerSource'], '',
                         'the flag is server-owned; only the marker path sets it')

    def test_sync_summary_carries_the_sprint_list(self):
        self.connect()
        with patch.object(main.jira_sync, 'configured', return_value=False), \
             patch.object(ns, 'sync_all_tickets', return_value={'checked': 1, 'updated': 0, 'changed': [], 'added': [],
                                                                'tagged': [], 'tagError': None,
                                                                'sprints': [{'id': 's36', 'name': 'Sprint 36', 'state': 'active'}]}):
            result = main.sync_all()
        self.assertEqual(result['sprints'][0]['name'], 'Sprint 36', 'Refresh can roll the selector over')

    # ---- the options payload Settings and the board render from ----

    def test_options_payload_carries_sprints_candidates_and_the_marker(self):
        self.connect()
        rows = [sprint_page('s36', 'Sprint 36', 'Current', '2026-09-10', '2026-09-20'),
                sprint_page('s35', 'Sprint 35', 'Past', '2026-08-18', '2026-08-31'),
                sprint_page('s37', 'Sprint 37', 'Future', '2026-09-21', '2026-10-04'),
                sprint_page('s99', 'Someday', 'Future')]
        p = page('p-1', 1, 'x')
        p['properties']['Sprint'] = {'type': 'relation', 'relation': [{'id': 's36'}]}
        with frozen('2026-09-15'):
            with patch.object(ns, '_request', side_effect=self.reader(rows, [p])):
                opts = ns.get_options()
        self.assertEqual([(s['name'], s['state']) for s in opts['sprints']],
                         [('Sprint 36', 'active'), ('Sprint 37', 'future'), ('Sprint 35', 'closed'),
                          ('Someday', 'future')],
                         'active first, then newest first, undated last')
        self.assertEqual(set(opts['sprints'][0]), {'id', 'name', 'state', 'start', 'end', 'url', 'rawStatus'})
        self.assertEqual(opts['sprintMarker'], {'value': 'Current', 'source': 'inferred',
                                                'inferredFrom': 'Sprint 36',
                                                'options': ['Current', 'Past', 'Future'],
                                                'hasStatusProperty': True})
        candidate = next(c for c in opts['sprintCandidates'] if c['property'] == 'Sprint')
        self.assertEqual((candidate['type'], candidate['target'], candidate['fillRate']), ('relation', 'Sprints', 1.0))
        self.assertTrue(candidate['reasons'] and candidate['score'] >= ns.SPRINT_SCORE_THRESHOLD)

    def test_options_payload_when_nothing_sprint_like_exists(self):
        self.connect()
        with patch.object(ns, '_request', return_value=SCHEMA):
            opts = ns.get_options()
        self.assertEqual(opts['sprints'], [])
        self.assertEqual(opts['sprintCandidates'], [])
        self.assertEqual(opts['sprintMarker'], {'value': '', 'source': '', 'inferredFrom': '',
                                                'options': [], 'hasStatusProperty': False})


if __name__ == '__main__':
    unittest.main()
