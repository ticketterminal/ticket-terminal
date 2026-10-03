import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import memory_analysis
import main
import settings_store
from workspace_fixture import TempWorkspaces


class CreateDocTests(unittest.TestCase):
    """create_doc is the only way a memory file gets created at all — write_doc (same module)
    deliberately refuses to touch a path that doesn't already exist. Patches memory_dirs_info
    directly — the one function every path-resolving call in this module now goes through — at
    a fresh temp dir, rather than relying on settings/env precedence, so this can never land on
    a real memory folder regardless of what happens to be configured on this machine."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.memory_dir = Path(self.temp.name) / 'memory'
        self._dirs = [{'path': self.memory_dir, 'categoryId': '', 'source': 'settings'}]
        self._patch = patch.object(memory_analysis, 'memory_dirs_info', return_value=self._dirs)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.temp.cleanup()

    def test_creates_file_and_mkdirs_missing_parent(self):
        self.assertFalse(self.memory_dir.exists())
        content = memory_analysis.create_doc('first-memory', description='a test memory', mem_type='project')
        self.assertTrue((self.memory_dir / 'first-memory.md').exists())
        self.assertEqual(memory_analysis.read_doc('first-memory'), content)

    def test_new_file_shows_up_in_the_graph_with_its_metadata(self):
        memory_analysis.create_doc('first-memory', description='a test memory', mem_type='project')
        node = next(n for n in memory_analysis.read_graph()['nodes'] if n['id'] == 'first-memory')
        self.assertEqual(node['description'], 'a test memory')
        self.assertEqual(node['type'], 'project')
        self.assertEqual(node['sourceCategoryId'], '')

    def test_rejects_duplicate_id_without_overwriting(self):
        memory_analysis.create_doc('dup', description='original')
        with self.assertRaises(FileExistsError):
            memory_analysis.create_doc('dup', description='clobber attempt')
        self.assertIn('original', memory_analysis.read_doc('dup'))

    def test_rejects_invalid_id(self):
        with self.assertRaises(ValueError):
            memory_analysis.create_doc('Not Valid!')
        self.assertFalse(self.memory_dir.exists(), 'never even creates the folder for a rejected id')

    def test_description_with_yaml_special_characters_round_trips(self):
        memory_analysis.create_doc('tricky', description='a: colon and "quotes"')
        node = next(n for n in memory_analysis.read_graph()['nodes'] if n['id'] == 'tricky')
        self.assertEqual(node['description'], 'a: colon and "quotes"')


class MultiDirTests(unittest.TestCase):
    """Two configured directories at once, one assigned to a category, one not — the actual
    use case this feature exists for: pointing at directories that may already contain memory,
    not just ones built through create_doc."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir_a = Path(self.temp.name) / 'a'
        self.dir_b = Path(self.temp.name) / 'b'
        self.dir_a.mkdir()
        self.dir_b.mkdir()
        self._dirs = [
            {'path': self.dir_a, 'categoryId': 'infra', 'source': 'settings'},
            {'path': self.dir_b, 'categoryId': '', 'source': 'settings'},
        ]
        self._patch = patch.object(memory_analysis, 'memory_dirs_info', return_value=self._dirs)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.temp.cleanup()

    def test_graph_unions_both_directories_with_their_category(self):
        memory_analysis.create_doc('a-memory', target_dir=str(self.dir_a))
        memory_analysis.create_doc('b-memory', target_dir=str(self.dir_b))
        nodes = {n['id']: n for n in memory_analysis.read_graph()['nodes']}
        self.assertEqual(nodes['a-memory']['sourceCategoryId'], 'infra')
        self.assertEqual(nodes['b-memory']['sourceCategoryId'], '')

    def test_same_id_in_two_directories_first_configured_wins(self):
        # Pre-existing files, as if Ami pointed TT at two folders that already had memory in
        # them — not files TT itself created.
        (self.dir_a / 'shared.md').write_text('---\nname: shared\ndescription: from a\n---\n')
        (self.dir_b / 'shared.md').write_text('---\nname: shared\ndescription: from b\n---\n')
        nodes = memory_analysis.read_graph()['nodes']
        self.assertEqual(len(nodes), 1, 'one node, not two, for the same id across directories')
        self.assertEqual(nodes[0]['description'], 'from a')
        self.assertEqual(nodes[0]['sourceCategoryId'], 'infra')

    def test_create_targets_the_chosen_directory(self):
        memory_analysis.create_doc('for-b', target_dir=str(self.dir_b))
        self.assertTrue((self.dir_b / 'for-b.md').exists())
        self.assertFalse((self.dir_a / 'for-b.md').exists())

    def test_create_without_target_dir_defaults_to_the_first_configured(self):
        memory_analysis.create_doc('implicit')
        self.assertTrue((self.dir_a / 'implicit.md').exists())

    def test_duplicate_id_rejected_even_across_different_directories(self):
        memory_analysis.create_doc('cross-dir', target_dir=str(self.dir_a))
        with self.assertRaises(FileExistsError):
            memory_analysis.create_doc('cross-dir', target_dir=str(self.dir_b))

    def test_write_doc_finds_the_file_wherever_it_actually_lives(self):
        memory_analysis.create_doc('for-b', target_dir=str(self.dir_b))
        memory_analysis.write_doc('for-b', 'updated content')
        self.assertEqual((self.dir_b / 'for-b.md').read_text(), 'updated content')


class LegacySingleDirFallbackTests(unittest.TestCase):
    """An install configured before multi-directory support (a plain settings.json memoryDir
    string, no memoryDirs list) keeps working with zero migration — see memory_dirs_info's
    precedence rule."""

    def setUp(self):
        self.workspaces = TempWorkspaces().start()
        self.temp = tempfile.TemporaryDirectory()
        self.legacy_dir = Path(self.temp.name) / 'legacy'
        self.legacy_dir.mkdir()

    def tearDown(self):
        self.temp.cleanup()
        self.workspaces.stop()

    def test_legacy_memory_dir_resolves_as_one_unassigned_directory(self):
        settings_store.update({'memoryDir': str(self.legacy_dir)})
        dirs = memory_analysis.memory_dirs_info()
        self.assertEqual(len(dirs), 1)
        self.assertEqual(dirs[0]['path'], self.legacy_dir)
        self.assertEqual(dirs[0]['categoryId'], '')
        self.assertEqual(dirs[0]['source'], 'settings')


class PostMemoryDocRouteTests(unittest.TestCase):
    """Direct calls against main.post_memory_doc, same style as test_terminal_providers.py."""

    def setUp(self):
        self.workspaces = TempWorkspaces().start()
        self.temp = tempfile.TemporaryDirectory()
        self.memory_dir = Path(self.temp.name) / 'memory'
        self._dirs = [{'path': self.memory_dir, 'categoryId': '', 'source': 'settings'}]
        self._patch = patch.object(memory_analysis, 'memory_dirs_info', return_value=self._dirs)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.temp.cleanup()
        self.workspaces.stop()

    def test_create_succeeds(self):
        result = main.post_memory_doc({'id': 'onboarding-notes', 'description': 'how we onboard'})
        self.assertTrue(result['ok'])
        self.assertIn('onboarding-notes', result['content'])
        self.assertTrue((self.memory_dir / 'onboarding-notes.md').exists())

    def test_duplicate_id_reports_error_not_exception(self):
        main.post_memory_doc({'id': 'dup'})
        result = main.post_memory_doc({'id': 'dup'})
        self.assertFalse(result['ok'])
        self.assertIn('already exists', result['error'])

    def test_missing_id_reports_error_not_exception(self):
        result = main.post_memory_doc({})
        self.assertFalse(result['ok'])

    def test_create_with_dir_path_targets_that_directory(self):
        other = Path(self.temp.name) / 'other'
        self._dirs.append({'path': other, 'categoryId': 'docs', 'source': 'settings'})
        result = main.post_memory_doc({'id': 'picked', 'dirPath': str(other)})
        self.assertTrue(result['ok'])
        self.assertTrue((other / 'picked.md').exists())
        self.assertFalse((self.memory_dir / 'picked.md').exists())


if __name__ == '__main__':
    unittest.main()
