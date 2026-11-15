import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

import cost_analysis
import memory_analysis


class CostCacheTests(unittest.TestCase):
    def tearDown(self):
        cost_analysis.clear_cache()

    def test_codeburn_runs_only_when_transcript_signature_changes(self):
        with patch.object(cost_analysis, "get_session_costs", return_value={"s": {"cost": 1}}) as scan:
            first, first_scanned = cost_analysis.get_session_costs_cached((("s", 1),))
            second, second_scanned = cost_analysis.get_session_costs_cached((("s", 1),))
            third, third_scanned = cost_analysis.get_session_costs_cached((("s", 2),))
        self.assertEqual(first, second)
        self.assertEqual(third["s"]["cost"], 1)
        self.assertEqual((first_scanned, second_scanned, third_scanned), (True, False, True))
        self.assertEqual(scan.call_count, 2)


class MemoryUsageCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.memory = self.root / "memory"
        self.project.mkdir(); self.memory.mkdir()
        (self.memory / "guide.md").write_text("guide")
        self.log = self.project / "sid.jsonl"
        memory_analysis.clear_usage_cache()

    def tearDown(self):
        memory_analysis.clear_usage_cache()
        self.temp.cleanup()

    def row(self):
        return json.dumps({"message": {"content": [{
            "type": "tool_use", "name": "Read",
            "input": {"file_path": str(self.memory / "guide.md")},
        }]}}) + "\n"

    def test_unchanged_claude_transcript_reuses_parsed_usage(self):
        self.log.write_text(self.row())
        with patch.object(memory_analysis, "claude_project_dir", return_value=self.project), \
             patch.object(memory_analysis, "_memory_dir", return_value=self.memory):
            self.assertEqual(memory_analysis.session_memory_usage("/repo", "sid"), {"guide": 1})
            with patch.object(memory_analysis.json, "loads", side_effect=AssertionError("must use cache")):
                self.assertEqual(memory_analysis.session_memory_usage("/repo", "sid"), {"guide": 1})
            self.log.write_text(self.row() + self.row())
            self.assertEqual(memory_analysis.session_memory_usage("/repo", "sid"), {"guide": 2})


if __name__ == "__main__":
    unittest.main()
