"""One install, several named workspaces — switched, never merged.

Covers the registry, the ContextVar that decides which workspace a call is
talking about (including across `asyncio.to_thread`, which is how every sync
runs), the one-time migration of a pre-workspaces `data/`, and the per-
workspace process keys, sync locks and tracker caches.

Nothing here touches the real `data/` tree or any live API: every case runs
against a temp data root.
"""
import asyncio
import datetime
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import content
import db
import jira_sync
import main
import notion_sync as ns
import settings_store
import workspaces
from workspace_fixture import TempWorkspaces


def ticket_db(*keys):
    return {'jiraTickets': {k: {'key': k} for k in keys}, 'people': {}, 'teamOptions': []}


class WorkspaceTestCase(unittest.TestCase):
    def setUp(self):
        self.ws = TempWorkspaces().start()

    def tearDown(self):
        self.ws.stop()


# ---------- the registry ----------

class RegistryTests(WorkspaceTestCase):
    def test_a_fresh_install_has_exactly_one_workspace_and_no_file(self):
        registry = workspaces.read_registry()
        self.assertEqual([w['slug'] for w in registry['workspaces']], ['default'])
        self.assertEqual(registry['defaultWorkspace'], 'default')
        self.assertFalse(workspaces.registry_path().exists(),
                         'reading must not write a file onto an install that never asked for one')

    def test_create_records_and_makes_the_directory(self):
        entry = workspaces.create('ticket-terminal', 'Ticket Terminal')
        self.assertEqual(entry['slug'], 'ticket-terminal')
        self.assertEqual(entry['name'], 'Ticket Terminal')
        self.assertTrue(entry['createdAt'])
        self.assertTrue(workspaces.root('ticket-terminal').is_dir())
        stored = json.loads(workspaces.registry_path().read_text())
        self.assertIn('ticket-terminal', [w['slug'] for w in stored['workspaces']],
                      'the synthesized default entry is persisted alongside the new one')
        self.assertIn('default', [w['slug'] for w in stored['workspaces']])

    def test_a_missing_name_falls_back_to_the_slug(self):
        self.assertEqual(workspaces.create('side-project')['name'], 'side-project')

    def test_default_is_a_reserved_slug(self):
        with self.assertRaises(ValueError) as caught:
            workspaces.create('default', 'Nope')
        self.assertIn('reserved', str(caught.exception))

    def test_a_slug_must_be_lowercase_letters_digits_and_hyphens(self):
        for bad in ('', 'Has Capitals', 'with space', 'trailing-', 'under_score', 'sl/ash', '..'):
            with self.assertRaises(ValueError, msg=bad):
                workspaces.create(bad, 'x')

    def test_a_duplicate_slug_is_refused(self):
        workspaces.create('alpha')
        with self.assertRaises(ValueError) as caught:
            workspaces.create('alpha')
        self.assertIn('already exists', str(caught.exception))

    def test_unknown_slug_resolves_to_an_unknown_workspace_error(self):
        with self.assertRaises(workspaces.UnknownWorkspace):
            workspaces.resolve('not-a-workspace')

    def test_default_resolves_through_the_registry(self):
        workspaces.create('dataflint', 'DataFlint')
        workspaces.write_registry({'defaultWorkspace': 'dataflint',
                                   'workspaces': workspaces.read_registry()['workspaces']})
        # `#/w/default/…` is a link that works on any install, whatever the
        # real default slug happens to be called.
        self.assertEqual(workspaces.resolve('default'), 'dataflint')
        self.assertEqual(workspaces.resolve(''), 'dataflint')
        self.assertEqual(workspaces.resolve(None), 'dataflint')
        self.assertEqual(workspaces.resolve('dataflint'), 'dataflint')

    def test_a_default_pointing_at_nothing_falls_back_to_the_first_entry(self):
        workspaces.write_registry({'defaultWorkspace': 'deleted',
                                   'workspaces': [{'slug': 'alpha', 'name': 'Alpha'}]})
        self.assertEqual(workspaces.default_slug(), 'alpha')

    def test_an_unreadable_registry_does_not_take_the_server_down(self):
        workspaces.registry_path().write_text('{ this is not json')
        self.assertEqual(workspaces.default_slug(), 'default')

    def test_last_sync_at_round_trips(self):
        workspaces.create('alpha')
        self.assertEqual(workspaces.get_last_sync_at('alpha'), '')
        stamp = workspaces.set_last_sync_at('alpha')
        self.assertEqual(workspaces.get_last_sync_at('alpha'), stamp)


# ---------- the ContextVar ----------

class ActiveWorkspaceTests(WorkspaceTestCase):
    def test_two_workspaces_read_different_data_in_one_process(self):
        self.ws.register('beta')
        with workspaces.use('default'):
            db.write(ticket_db('A-1'))
            settings_store.write({**settings_store.read(), 'memoryDir': '/tmp/a'})
        with workspaces.use('beta'):
            db.write(ticket_db('B-1'))
            settings_store.write({**settings_store.read(), 'memoryDir': '/tmp/b'})

        with workspaces.use('default'):
            self.assertEqual(sorted(db.read()['jiraTickets']), ['A-1'])
            self.assertEqual(settings_store.read()['memoryDir'], '/tmp/a')
        with workspaces.use('beta'):
            self.assertEqual(sorted(db.read()['jiraTickets']), ['B-1'])
            self.assertEqual(settings_store.read()['memoryDir'], '/tmp/b')

        self.assertTrue((self.ws.data_root / 'workspaces' / 'default' / 'db.json').exists())
        self.assertTrue((self.ws.data_root / 'workspaces' / 'beta' / 'db.json').exists())

    def test_the_active_workspace_survives_asyncio_to_thread(self):
        # This is why it is a ContextVar and not a thread-local: every sync
        # runs through asyncio.to_thread, which copies the context across.
        self.ws.register('beta')
        with workspaces.use('default'):
            db.write(ticket_db('A-1'))
        with workspaces.use('beta'):
            db.write(ticket_db('B-1'))

        async def read_from_a_thread():
            return await asyncio.to_thread(lambda: (workspaces.current(), sorted(db.read()['jiraTickets'])))

        with workspaces.use('beta'):
            self.assertEqual(asyncio.run(read_from_a_thread()), ('beta', ['B-1']))
        with workspaces.use('default'):
            self.assertEqual(asyncio.run(read_from_a_thread()), ('default', ['A-1']))

    def test_nothing_set_means_the_default_workspace(self):
        self.ws.register('beta')
        workspaces.write_registry({'defaultWorkspace': 'beta',
                                   'workspaces': workspaces.read_registry()['workspaces']})
        self.ws.stop_override = None
        with workspaces.use(None):
            self.assertIsNone(workspaces.active_override())
            self.assertEqual(workspaces.current(), 'beta')

    def test_categories_and_category_state_follow_the_workspace(self):
        import category_management as cm
        self.ws.register('beta')
        lane = {'id': 'bugs', 'name': 'Bugs', 'status': 'gap', 'color': '#000',
                'note': '', 'docs': [], 'skills': [], 'memories': []}
        with workspaces.use('default'):
            content.write_categories([lane])
            cm.save_state({'role': 'QA engineer'})
        with workspaces.use('beta'):
            content.write_categories([{**lane, 'id': 'infra', 'name': 'Infra'}])
            cm.save_state({'role': 'DevOps / SRE'})
        with workspaces.use('default'):
            self.assertEqual([c['id'] for c in content.read_categories()], ['bugs'])
            self.assertEqual(cm.read_state()['role'], 'QA engineer')
        with workspaces.use('beta'):
            self.assertEqual([c['id'] for c in content.read_categories()], ['infra'])
            self.assertEqual(cm.read_state()['role'], 'DevOps / SRE')

    def test_a_category_diagram_is_stored_inside_the_workspace(self):
        self.ws.register('beta')
        lane = {'id': 'bugs', 'name': 'Bugs', 'status': 'gap', 'color': '#000',
                'note': '', 'docs': [], 'skills': [], 'memories': []}
        for slug in ('default', 'beta'):
            with workspaces.use(slug):
                content.write_categories([dict(lane)])
        with workspaces.use('default'):
            content.set_category_diagram('bugs', {'mermaid': 'graph TD;a-->b;', 'generatedAt': 'now'})
            self.assertEqual(content.read_categories()[0]['diagram']['mermaid'], 'graph TD;a-->b;')
        with workspaces.use('beta'):
            self.assertIsNone(content.read_categories()[0].get('diagram'),
                              'a diagram belongs to one board, like everything else')

    def test_the_shipped_examples_stay_at_the_data_root(self):
        (self.ws.data_root / 'categories.example.json').write_text(json.dumps([
            {'id': 'example', 'name': 'Example', 'status': 'gap', 'color': '#000',
             'note': '', 'docs': [], 'skills': [], 'memories': []}]))
        self.ws.register('beta')
        with workspaces.use('beta'):
            # A brand-new workspace has no categories.json of its own yet.
            self.assertEqual([c['id'] for c in content.read_categories()], ['example'])
            content.write_categories([{'id': 'own', 'name': 'Own', 'status': 'gap', 'color': '#000',
                                       'note': '', 'docs': [], 'skills': [], 'memories': []}])
            self.assertEqual([c['id'] for c in content.read_categories()], ['own'])
        self.assertTrue((self.ws.data_root / 'categories.example.json').exists(),
                        'the example is install-wide and is never moved or overwritten')


# ---------- migration ----------

class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp.name)
        self.patch = patch.object(workspaces, 'DATA_ROOT', self.data_root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def seed_old_layout(self):
        (self.data_root / 'db.json').write_text(json.dumps(ticket_db('OLD-1')))
        (self.data_root / 'settings.json').write_text('{"memoryDir": "/tmp/memories"}')
        (self.data_root / 'categories.json').write_text('[]')
        (self.data_root / 'docs.json').write_text('{}')
        (self.data_root / 'category-management.json').write_text('{"role": "QA engineer"}')
        (self.data_root / 'sessions').mkdir()
        (self.data_root / 'sessions' / 'OLD-1.log').write_text('transcript')
        (self.data_root / 'categories.example.json').write_text('[]')
        (self.data_root / 'docs.example.json').write_text('{}')
        (self.data_root / 'server.log').write_text('log')

    def test_it_moves_every_file_and_leaves_the_examples_alone(self):
        self.seed_old_layout()
        result = workspaces.migrate_if_needed()
        self.assertTrue(result['migrated'])
        self.assertEqual(sorted(result['moved']),
                         ['categories.json', 'category-management.json', 'db.json',
                          'docs.json', 'sessions', 'settings.json'])
        moved_to = self.data_root / 'workspaces' / 'default'
        for name in ('db.json', 'settings.json', 'categories.json', 'docs.json', 'category-management.json'):
            self.assertTrue((moved_to / name).exists(), name)
            self.assertFalse((self.data_root / name).exists(), name + ' must be MOVED, not copied')
        self.assertEqual((moved_to / 'sessions' / 'OLD-1.log').read_text(), 'transcript')
        for stays in ('categories.example.json', 'docs.example.json', 'server.log'):
            self.assertTrue((self.data_root / stays).exists(), stays)

        registry = json.loads(workspaces.registry_path().read_text())
        self.assertEqual(registry['defaultWorkspace'], 'default')
        self.assertEqual([w['slug'] for w in registry['workspaces']], ['default'])

        with workspaces.use('default'):
            self.assertEqual(sorted(db.read()['jiraTickets']), ['OLD-1'])
            self.assertEqual(settings_store.read()['memoryDir'], '/tmp/memories')

    def test_it_is_idempotent_and_never_runs_twice(self):
        self.seed_old_layout()
        self.assertTrue(workspaces.migrate_if_needed()['migrated'])
        # A second db.json appearing at the root afterwards (a hand-edit, a
        # restored backup) must NOT trigger a second move over the top of a
        # migrated install.
        (self.data_root / 'db.json').write_text(json.dumps(ticket_db('NEW-1')))
        second = workspaces.migrate_if_needed()
        self.assertFalse(second['migrated'])
        self.assertEqual(second['moved'], [])
        with workspaces.use('default'):
            self.assertEqual(sorted(db.read()['jiraTickets']), ['OLD-1'])

    def test_a_fresh_install_is_left_completely_alone(self):
        result = workspaces.migrate_if_needed()
        self.assertFalse(result['migrated'])
        self.assertFalse((self.data_root / 'workspaces').exists())
        self.assertFalse(workspaces.registry_path().exists())


# ---------- per-workspace process keys, locks and caches ----------

class IsolationTests(WorkspaceTestCase):
    def test_process_keys_are_per_workspace(self):
        self.ws.register('beta')
        with workspaces.use('default'):
            here = main.process_key_for('DATAFLINT-7652', 'claude')
        with workspaces.use('beta'):
            there = main.process_key_for('DATAFLINT-7652', 'claude')
        self.assertNotEqual(here, there, 'two workspaces can both hold the same ticket key')
        self.assertEqual(here, 'default|claude|DATAFLINT-7652')

    def test_running_processes_lists_only_this_workspace(self):
        self.ws.register('beta')
        main.running_processes.clear()
        try:
            main.running_processes['default|claude|A-1'] = {}
            main.running_processes['default|codex|A-2'] = {}
            main.running_processes['beta|claude|B-1'] = {}
            with workspaces.use('default'):
                self.assertEqual(sorted(main.get_running_processes()['running']), ['A-1', 'codex:A-2'])
            with workspaces.use('beta'):
                self.assertEqual(main.get_running_processes()['running'], ['B-1'],
                                 'a session elsewhere stays alive but is never shown here')
        finally:
            main.running_processes.clear()

    def test_the_browsers_workspace_relative_key_still_kills_the_right_process(self):
        self.ws.register('beta')
        main.running_processes.clear()
        try:
            with workspaces.use('beta'):
                self.assertEqual(main._process_key_from_wire('codex:B-1'), 'beta|codex|B-1')
                self.assertEqual(main._process_key_from_wire('B-1'), 'beta|claude|B-1')
                self.assertFalse(main.kill_background_process('codex:B-1')['ok'])
        finally:
            main.running_processes.clear()

    def test_sync_locks_are_per_workspace(self):
        self.ws.register('beta')
        here, there = main.sync_lock_for('default'), main.sync_lock_for('beta')
        self.assertIsNot(here, there)
        self.assertIs(main.sync_lock_for('default'), here, 'one lock per slug, reused')
        with here:
            self.assertTrue(there.acquire(blocking=False),
                            'an hour-long sync in one workspace must not block a short one next door')
            there.release()

    def test_a_busy_workspace_refuses_only_its_own_sync(self):
        self.ws.register('beta')
        with main.sync_lock_for('default'):
            with workspaces.use('default'):
                self.assertTrue(main.sync_trackers().get('busy'))
            with workspaces.use('beta'), \
                 patch.object(main.jira_sync, 'configured', return_value=False), \
                 patch.object(main.notion_sync, 'configured', return_value=False):
                self.assertFalse(main.sync_trackers().get('busy'))

    def test_the_notion_schema_cache_is_keyed_by_workspace(self):
        self.ws.register('beta')
        ns._schema_cache.clear()
        calls = []

        def request(method, path, **kwargs):
            calls.append(path)
            return {'id': 'db-1', 'properties': {}}

        with patch.object(ns, '_request', side_effect=request):
            with workspaces.use('default'):
                ns.get_schema('db-1')
                ns.get_schema('db-1')
            self.assertEqual(len(calls), 1, 'cached within one workspace')
            with workspaces.use('beta'):
                ns.get_schema('db-1')
        self.assertEqual(len(calls), 2, 'a different workspace is a different token — never a cache hit')
        ns._schema_cache.clear()

    def test_invalidating_one_workspaces_notion_cache_leaves_the_other_alone(self):
        self.ws.register('beta')
        ns._schema_cache.clear()
        ns._timebox_cache.clear()
        ns._schema_cache[('default', 'db-1')] = {'id': 'a'}
        ns._schema_cache[('beta', 'db-1')] = {'id': 'b'}
        ns._timebox_cache[('beta', 'sprints')] = {'rows': []}
        with workspaces.use('default'):
            ns.invalidate_cache()
        self.assertNotIn(('default', 'db-1'), ns._schema_cache)
        self.assertIn(('beta', 'db-1'), ns._schema_cache)
        self.assertIn(('beta', 'sprints'), ns._timebox_cache)
        ns._schema_cache.clear()
        ns._timebox_cache.clear()

    def test_the_jira_workflow_cache_is_keyed_by_workspace(self):
        self.ws.register('beta')
        jira_sync._workflow_statuses_cache.clear()
        calls = []

        def transitions(sample_key):
            calls.append(sample_key)
            return [{'id': '1', 'name': 'Done'}]

        with patch.object(jira_sync, 'get_transitions', side_effect=transitions):
            with workspaces.use('default'):
                jira_sync.get_workflow_statuses('A-1')
                jira_sync.get_workflow_statuses('A-1')
            with workspaces.use('beta'):
                jira_sync.get_workflow_statuses('B-1')
        self.assertEqual(calls, ['A-1', 'B-1'])
        with workspaces.use('default'):
            jira_sync.invalidate_cache()
        self.assertNotIn('default', jira_sync._workflow_statuses_cache)
        self.assertIn('beta', jira_sync._workflow_statuses_cache)
        jira_sync._workflow_statuses_cache.clear()


# ---------- which workspace syncs, and when ----------

class SyncSchedulingTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.ws.register('beta')
        workspaces.write_registry({'defaultWorkspace': 'default',
                                   'workspaces': workspaces.read_registry()['workspaces']})

    def old_stamp(self):
        when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=main.TRACKER_SYNC_INTERVAL_SECONDS + 60)
        return when.isoformat(timespec='seconds')

    def test_the_background_timer_syncs_only_the_default_workspace(self):
        synced = set()

        def record():
            synced.add(workspaces.current())
            return {'errors': {}}

        async def scenario():
            # The caller's own context is "beta"; the timer must ignore that
            # entirely — the server never knows which workspace a browser shows.
            with workspaces.use('beta'), \
                 patch.object(main, 'TRACKER_SYNC_INTERVAL_SECONDS', 0), \
                 patch.object(main, 'sync_trackers', record):
                await main._start_background_tracker_sync()
                await asyncio.sleep(0.05)
            for task in asyncio.all_tasks() - {asyncio.current_task()}:
                task.cancel()
            await asyncio.sleep(0)

        asyncio.run(scenario())
        self.assertEqual(synced, {'default'})

    def test_sync_if_stale_starts_a_sync_when_the_workspace_is_stale(self):
        workspaces.set_last_sync_at('beta', self.old_stamp())
        started, ran_in = threading.Event(), []

        def record():
            ran_in.append(workspaces.current())
            started.set()
            return {'errors': {}}

        async def scenario():
            with patch.object(main, 'sync_trackers', record):
                response = await main.workspace_sync_if_stale('beta')
                self.assertTrue(response['syncStarted'])
                for _ in range(200):
                    if started.is_set():
                        break
                    await asyncio.sleep(0.01)
                await asyncio.sleep(0.02)
            return response

        response = asyncio.run(scenario())
        self.assertTrue(response['ok'])
        self.assertTrue(started.is_set())
        self.assertEqual(ran_in, ['beta'], 'the background sync runs inside the switched-to workspace')

    def test_sync_if_stale_returns_without_awaiting_the_sync(self):
        workspaces.set_last_sync_at('beta', self.old_stamp())
        release, started = threading.Event(), threading.Event()

        def slow():
            started.set()
            release.wait(5)
            return {'errors': {}}

        async def scenario():
            with patch.object(main, 'sync_trackers', slow):
                response = await main.workspace_sync_if_stale('beta')
                self.assertTrue(response['syncStarted'])
                self.assertFalse(release.is_set(),
                                 'the endpoint returned while the sync is still running')
                for _ in range(200):
                    if started.is_set():
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(started.is_set())
                release.set()
                await asyncio.sleep(0.05)

        asyncio.run(scenario())

    def test_sync_if_stale_does_nothing_when_the_workspace_synced_recently(self):
        stamp = workspaces.set_last_sync_at('beta')
        calls = []

        async def scenario():
            with patch.object(main, 'sync_trackers', lambda: calls.append(1) or {'errors': {}}):
                response = await main.workspace_sync_if_stale('beta')
                await asyncio.sleep(0.02)
            return response

        response = asyncio.run(scenario())
        self.assertFalse(response['syncStarted'])
        self.assertEqual(response['lastSyncAt'], stamp)
        self.assertEqual(calls, [], 'switching back and forth must not restart an hour-long sync')

    def test_sync_if_stale_does_nothing_while_that_workspace_holds_its_own_lock(self):
        workspaces.set_last_sync_at('beta', self.old_stamp())
        calls = []

        async def scenario():
            with main.sync_lock_for('beta'), \
                 patch.object(main, 'sync_trackers', lambda: calls.append(1) or {'errors': {}}):
                response = await main.workspace_sync_if_stale('beta')
                await asyncio.sleep(0.02)
            return response

        response = asyncio.run(scenario())
        self.assertFalse(response['syncStarted'])
        self.assertEqual(calls, [])

    def test_sync_if_stale_404s_an_unknown_workspace(self):
        response = asyncio.run(main.workspace_sync_if_stale('nope'))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(json.loads(response.body), {'ok': False, 'error': 'no such workspace'})

    def test_last_sync_at_is_recorded_even_when_the_sync_fails(self):
        with workspaces.use('beta'), \
             patch.object(main.jira_sync, 'configured', return_value=True), \
             patch.object(main.jira_sync, 'sync_all_tickets', side_effect=RuntimeError('jira 401')), \
             patch.object(main.notion_sync, 'configured', return_value=False):
            result = main.sync_trackers()
        self.assertEqual(result['errors'], {'jira': 'jira 401'})
        self.assertTrue(workspaces.get_last_sync_at('beta'),
                        'a broken tracker must not re-trigger a full sync on every switch')
        self.assertEqual(workspaces.get_last_sync_at('default'), '',
                         'and it is recorded against the workspace that actually synced')


# ---------- the HTTP surface, through the real middleware ----------

class WorkspaceHttpTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.ws.register('beta', 'Beta Board')
        # The install-wide example a real clone ships with, so a workspace with
        # no categories.json of its own still renders (and the startup category
        # scanner has something to read).
        (self.ws.data_root / 'categories.example.json').write_text('[]')
        with workspaces.use('default'):
            db.write(ticket_db('A-1', 'A-2'))
        with workspaces.use('beta'):
            db.write(ticket_db('B-1'))

    def test_every_endpoint_takes_w_and_a_bare_call_means_the_default(self):
        synced = []

        # sync_trackers is stubbed for the whole test: `sync-if-stale` really
        # does start a sync, and the repo's .env makes the trackers look
        # configured — an unstubbed run here would hit the live Jira/Notion.
        def fake_sync():
            synced.append(workspaces.current())
            workspaces.set_last_sync_at(workspaces.current())  # as the real one does
            return {"synced": [], "errors": {}}

        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        base = 'http://127.0.0.1:' + str(sock.getsockname()[1])
        server = uvicorn.Server(uvicorn.Config(main.app, log_level='critical', lifespan='on'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)

        def request(path, body=None, method='GET'):
            data = None if body is None else json.dumps(body).encode()
            req = urllib.request.Request(base + path, data=data, method=method,
                                         headers={'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as error:
                return error.code, json.load(error)

        with patch.object(main, 'sync_trackers', fake_sync), \
             patch.object(main.jira_sync, 'configured', return_value=False), \
             patch.object(main.notion_sync, 'configured', return_value=False):
            thread.start()
            try:
                for _ in range(200):
                    if server.started:
                        break
                    time.sleep(.01)
                self.assertTrue(server.started)

                # A bare route is the default workspace — every pre-workspaces link keeps working.
                self.assertEqual(sorted(request('/api/tickets')[1]), ['A-1', 'A-2'])
                self.assertEqual(sorted(request('/api/tickets?w=default')[1]), ['A-1', 'A-2'])
                self.assertEqual(sorted(request('/api/tickets?w=beta')[1]), ['B-1'])

                status, body = request('/api/tickets?w=nope')
                self.assertEqual(status, 404)
                self.assertEqual(body, {'ok': False, 'error': 'no such workspace'})

                listing = request('/api/workspaces')[1]
                self.assertTrue(listing['ok'])
                self.assertEqual(listing['defaultWorkspace'], 'default')
                self.assertEqual(listing['active'], 'default')
                by_slug = {w['slug']: w for w in listing['workspaces']}
                self.assertEqual(by_slug['default']['ticketCount'], 2)
                self.assertEqual(by_slug['beta']['ticketCount'], 1)
                self.assertEqual(by_slug['beta']['name'], 'Beta Board')
                self.assertFalse(by_slug['beta']['connected'])
                self.assertFalse(by_slug['beta']['syncing'])
                self.assertEqual(request('/api/workspaces?w=beta')[1]['active'], 'beta')

                created = request('/api/workspaces', {'slug': 'gamma', 'name': 'Gamma'}, 'POST')[1]
                self.assertTrue(created['ok'])
                self.assertEqual(created['workspace']['slug'], 'gamma')
                self.assertEqual(created['workspace']['ticketCount'], 0)
                self.assertFalse(request('/api/workspaces', {'slug': 'gamma', 'name': 'x'}, 'POST')[1]['ok'])
                self.assertFalse(request('/api/workspaces', {'slug': 'default', 'name': 'x'}, 'POST')[1]['ok'])

                stale = request('/api/workspaces/beta/sync-if-stale', {}, 'POST')[1]
                self.assertEqual(stale, {'ok': True, 'syncStarted': True, 'lastSyncAt': ''})
                for _ in range(200):
                    if synced:
                        break
                    time.sleep(.01)
                self.assertEqual(synced, ['beta'], 'started in the switched-to workspace, not the caller\'s')
                # Now that it has just synced, switching back does nothing.
                again = request('/api/workspaces/beta/sync-if-stale', {}, 'POST')[1]
                self.assertFalse(again['syncStarted'])
                self.assertTrue(again['lastSyncAt'])

                self.assertEqual(request('/api/workspaces/nope/sync-if-stale', {}, 'POST')[0], 404)
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                sock.close()
                self.assertFalse(thread.is_alive())


    def test_a_request_cannot_name_another_workspaces_process(self):
        """The wire format is a bare ticket key scoped by ?w=. A key that
        carries its own workspace must never be honoured, or a board open on
        one workspace could kill an agent running in another."""
        main.running_processes.clear()
        proc = MagicMock(); proc.poll.return_value = None
        with workspaces.use('beta'):
            beta_key = main.process_key_for('SECRET-1', 'claude')
        main.running_processes[beta_key] = {'proc': proc, 'master_fd': 99}

        with workspaces.use('default'):
            self.assertIsNone(main._process_key_from_wire(beta_key),
                              'a fully-qualified key is refused, not passed through')
            result = main.kill_background_process(beta_key)
        self.assertFalse(result['ok'])
        self.assertIn(beta_key, main.running_processes, "the other workspace's process is untouched")
        proc.terminate.assert_not_called()

        # The browser's own shapes still work, scoped to the caller's workspace.
        with workspaces.use('beta'):
            self.assertEqual(main._process_key_from_wire('SECRET-1'), beta_key)
            self.assertEqual(main._process_key_from_wire('codex:SECRET-1'),
                             main.process_key_for('SECRET-1', 'codex'))
        self.assertIsNone(main._process_key_from_wire('bogus:SECRET-1'))
        main.running_processes.clear()


    def test_a_scan_runs_in_the_workspace_that_asked_for_it(self):
        """threading.Thread does not copy contextvars, so without carrying the
        slug the worker wrote its results into the default workspace."""
        import category_management as cm
        seen = []
        with workspaces.use('beta'):
            with patch.object(cm, 'scan_worker', side_effect=lambda: seen.append(workspaces.current())), \
                 patch.object(cm, 'save_state'), patch.object(cm, 'load', return_value={'scan': {}}):
                try:
                    cm.start_scan()
                    for _ in range(200):
                        if seen: break
                        time.sleep(0.01)
                finally:
                    # scan_worker is mocked here, so the release that the real
                    # worker performs never runs; the lock registry is module
                    # global and would leak into the next test.
                    cm.SCAN_LOCK.release()
        self.assertEqual(seen, ['beta'])

    def test_one_workspaces_scan_does_not_block_anothers(self):
        import category_management as cm
        cm._SCAN_LOCKS.clear()   # module-global, shared across tests
        with workspaces.use('beta'):
            self.assertTrue(cm.SCAN_LOCK.acquire(blocking=False))
            self.assertTrue(cm.SCAN_LOCK.locked())
        with workspaces.use('gamma'):
            self.assertFalse(cm.SCAN_LOCK.locked(), "another workspace's scan is not this one's")
            self.assertTrue(cm.SCAN_LOCK.acquire(blocking=False))
            cm.SCAN_LOCK.release()
        with workspaces.use('beta'):
            cm.SCAN_LOCK.release()

    def test_a_slug_is_bounded_and_never_leaves_a_ghost_entry(self):
        before = len(workspaces.read_registry()['workspaces'])
        with self.assertRaises(ValueError):
            workspaces.create('a' * 300)
        self.assertEqual(len(workspaces.read_registry()['workspaces']), before,
                         'a rejected slug leaves no registry entry behind')
        self.assertFalse(workspaces.valid_slug('a' * 300))
        self.assertFalse(workspaces.valid_slug('../evil'))
        self.assertTrue(workspaces.valid_slug('ticket-terminal'))

    def test_a_hand_edited_registry_cannot_escape_the_data_root(self):
        """The README tells operators to edit workspaces.json to rename the
        default workspace, so a bad slug can reach resolve() without ever
        having passed create()."""
        registry = workspaces.read_registry()
        registry['workspaces'].append({'slug': '../../escape', 'name': 'x',
                                       'createdAt': workspaces.now(), 'lastSyncAt': ''})
        workspaces.write_registry(registry)
        with self.assertRaises(workspaces.UnknownWorkspace):
            workspaces.resolve('../../escape')


if __name__ == '__main__':
    unittest.main()
