import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import memory_analysis
import main
from workspace_fixture import TempWorkspaces


class CreateDocTests(unittest.TestCase):
    """create_doc is the only way a memory file gets created at all — write_doc
    (same module) deliberately refuses to touch a path that doesn't already exist.
    Points _memory_dir at a fresh temp dir directly, rather than relying on
    TempWorkspaces/WMP_MEMORY_DIR resolution, so this can never land on a real
    memory folder regardless of settings/env precedence."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.memory_dir = Path(self.temp.name) / 'memory'
        self._patch = patch.object(memory_analysis, '_memory_dir', return_value=self.memory_dir)
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


class PostMemoryDocRouteTests(unittest.TestCase):
    """Direct calls against main.post_memory_doc, same style as test_terminal_providers.py."""

    def setUp(self):
        self.workspaces = TempWorkspaces().start()
        self.temp = tempfile.TemporaryDirectory()
        self.memory_dir = Path(self.temp.name) / 'memory'
        self._patch = patch.object(memory_analysis, '_memory_dir', return_value=self.memory_dir)
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


if __name__ == '__main__':
    unittest.main()
