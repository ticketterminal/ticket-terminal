import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import workflow_insights as wi
from workspace_fixture import TempWorkspaces


def entry(provider='claude', model='Sonnet 5', cost=1.0, calls=2, turns=1, duration_ms=1000,
          categories=None, input_tokens=100, output_tokens=100, cache_read=0, ticket_key='T-1',
          session_id='s-1'):
    return {
        'ticketKey': ticket_key, 'provider': provider, 'sessionId': session_id,
        'models': [model], 'cost': cost, 'calls': calls, 'turns': turns,
        'inputTokens': input_tokens, 'outputTokens': output_tokens,
        'cacheReadTokens': cache_read, 'cacheWriteTokens': 0, 'durationMs': duration_ms,
        'categories': categories if categories is not None else ['bugs'],
    }


class VendorModelStatsTests(unittest.TestCase):
    def test_groups_by_provider_and_model_with_correct_totals_and_averages(self):
        entries = [
            entry(provider='claude', model='Sonnet 5', cost=1.0, calls=2, duration_ms=1000),
            entry(provider='claude', model='Sonnet 5', cost=3.0, calls=4, duration_ms=3000),
            entry(provider='codex', model='gpt-6-astra', cost=0.5, calls=1, duration_ms=500),
        ]
        result = wi.vendor_model_stats(entries)
        by_vm = {(r['provider'], r['model']): r for r in result['byVendorModel']}
        claude = by_vm[('claude', 'Sonnet 5')]
        self.assertEqual(claude['sessions'], 2)
        self.assertEqual(claude['totalCost'], 4.0)
        self.assertEqual(claude['avgCost'], 2.0)
        self.assertEqual(claude['avgCalls'], 3.0)
        self.assertEqual(claude['avgDurationMs'], 2000)
        codex = by_vm[('codex', 'gpt-6-astra')]
        self.assertEqual(codex['sessions'], 1)
        self.assertEqual(codex['totalCost'], 0.5)

    def test_ignores_synthetic_placeholder_model_when_a_real_one_is_present(self):
        e = entry(provider='claude', model='irrelevant')
        e['models'] = ['<synthetic>', 'Opus 5']
        result = wi.vendor_model_stats([e])
        models = {r['model'] for r in result['byVendorModel']}
        self.assertIn('Opus 5', models)
        self.assertNotIn('<synthetic>', models)

    def test_sorted_by_total_cost_descending(self):
        entries = [entry(cost=1.0, model='cheap'), entry(cost=9.0, model='expensive')]
        result = wi.vendor_model_stats(entries)
        self.assertEqual(result['byVendorModel'][0]['model'], 'expensive')

    def test_by_category_splits_multi_category_tickets_into_each_category(self):
        e = entry(categories=['bugs', 'features'], cost=2.0)
        result = wi.vendor_model_stats([e])
        cats = {r['category'] for r in result['byCategory']}
        self.assertEqual(cats, {'bugs', 'features'})

    def test_uncategorized_bucket_when_ticket_has_no_categories(self):
        e = entry(categories=[])
        result = wi.vendor_model_stats([e])
        self.assertEqual(result['byCategory'][0]['category'], 'uncategorized')


class CachingStatsTests(unittest.TestCase):
    def test_low_ratio_and_high_volume_is_flagged_as_waste(self):
        e = entry(input_tokens=30_000, output_tokens=10_000, cache_read=1_000)  # ratio ~3%
        result = wi.caching_stats([e])
        self.assertEqual(len(result['wasteCandidates']), 1)
        self.assertEqual(result['wasteCandidates'][0]['ticketKey'], 'T-1')

    def test_low_ratio_but_small_volume_is_not_flagged(self):
        e = entry(input_tokens=50, output_tokens=50, cache_read=1)  # tiny session, low ratio
        result = wi.caching_stats([e])
        self.assertEqual(result['wasteCandidates'], [])

    def test_high_ratio_is_not_flagged_even_at_high_volume(self):
        e = entry(input_tokens=1_000, output_tokens=30_000, cache_read=100_000)  # well-cached
        result = wi.caching_stats([e])
        self.assertEqual(result['wasteCandidates'], [])

    def test_provider_efficiency_is_none_when_no_tokens_at_all(self):
        e = entry(input_tokens=0, output_tokens=0, cache_read=0)
        result = wi.caching_stats([e])
        self.assertIsNone(result['byProvider'][0]['cacheEfficiency'])

    def test_provider_efficiency_ratio_is_computed_correctly(self):
        e = entry(input_tokens=100, output_tokens=0, cache_read=300)  # 300/(300+100) = 0.75
        result = wi.caching_stats([e])
        self.assertAlmostEqual(result['byProvider'][0]['cacheEfficiency'], 0.75)


class MemoryStructureStatsTests(unittest.TestCase):
    def test_dedupes_the_sessionid_and_provider_alias_for_the_same_real_session(self):
        # all_ticket_memory_usage aliases one real session under both its raw sessionId AND
        # "<provider>:<ticketKey>" — counting both would double every real read.
        usage = {
            'sess-1': {'mem-a': 3},
            'claude:T-1': {'mem-a': 3},
        }
        with patch.object(wi.memory_analysis, 'all_ticket_memory_usage', return_value=usage), \
             patch.object(wi.memory_analysis, 'memory_file_stats', return_value={'mem-a': {'chars': 500}}):
            rows = wi.memory_structure_stats({}, '/tmp')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['readByTickets'], 1)
        self.assertEqual(rows[0]['chars'], 500)

    def test_sorted_by_read_count_then_size_descending(self):
        usage = {'claude:T-1': {'mem-hot': 1}, 'claude:T-2': {'mem-hot': 1, 'mem-cold': 1}}
        sizes = {'mem-hot': {'chars': 100}, 'mem-cold': {'chars': 9000}}
        with patch.object(wi.memory_analysis, 'all_ticket_memory_usage', return_value=usage), \
             patch.object(wi.memory_analysis, 'memory_file_stats', return_value=sizes):
            rows = wi.memory_structure_stats({}, '/tmp')
        self.assertEqual(rows[0]['id'], 'mem-hot')  # read by 2 tickets beats read by 1
        self.assertEqual(rows[1]['id'], 'mem-cold')

    def test_a_file_with_no_reads_still_appears_by_size(self):
        with patch.object(wi.memory_analysis, 'all_ticket_memory_usage', return_value={}), \
             patch.object(wi.memory_analysis, 'memory_file_stats', return_value={'never-read': {'chars': 42}}):
            rows = wi.memory_structure_stats({}, '/tmp')
        self.assertEqual(rows, [{'id': 'never-read', 'readByTickets': 0, 'chars': 42}])


class OptimizeFindingsTests(unittest.TestCase):
    def test_returns_none_when_codeburn_is_missing(self):
        with patch.object(wi.subprocess, 'run', side_effect=FileNotFoundError()):
            self.assertIsNone(wi.get_optimize_findings())

    def test_returns_none_when_codeburn_exits_with_an_error(self):
        with patch.object(wi.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'codeburn')):
            self.assertIsNone(wi.get_optimize_findings())

    def test_returns_parsed_json_on_success(self):
        fake = type('R', (), {'stdout': '{"summary": {"healthScore": 80}, "findings": []}'})()
        with patch.object(wi.subprocess, 'run', return_value=fake):
            result = wi.get_optimize_findings()
        self.assertEqual(result['summary']['healthScore'], 80)


class ComputeInsightsTests(unittest.TestCase):
    def setUp(self):
        self.workspaces = TempWorkspaces().start()

    def tearDown(self):
        self.workspaces.stop()

    def test_shape_and_no_llm_call_anywhere(self):
        with patch.object(wi.spend_ledger, 'read_entries', return_value=[entry()]), \
             patch.object(wi.memory_analysis, 'all_ticket_memory_usage', return_value={}), \
             patch.object(wi.memory_analysis, 'memory_file_stats', return_value={}), \
             patch.object(wi, 'get_optimize_findings', return_value=None), \
             patch('claude_cli.command', side_effect=AssertionError('must never call an LLM')):
            result = wi.compute_insights({}, '/tmp')
        self.assertEqual(set(result), {'vendorModel', 'caching', 'memory', 'codeburnOptimize', 'ledgerEntryCount'})
        self.assertEqual(result['ledgerEntryCount'], 1)


if __name__ == '__main__':
    unittest.main()
