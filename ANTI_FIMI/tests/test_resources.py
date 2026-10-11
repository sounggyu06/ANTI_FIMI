from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from engine import parse_time, stamp
from resources import group_resources
from server import RawOnlyEmbedder, Runtime

BASE = parse_time('2026-10-01T12:00:00Z')


def post(pid, text='A sufficiently long observed report.', urls=None, relations=None, seconds=0):
    return {'id': pid, 'account_id': 'account:' + pid,
            'created_at': stamp(BASE + timedelta(seconds=seconds)), 'text': text,
            'urls': urls or [], 'relations': relations or []}


def groups(posts):
    rows = [{**p, 'raw_json': json.dumps(p)} for p in posts]
    return group_resources(rows, [{'post_id': p['id'], 'url': url} for p in posts for url in p['urls']])


class ResourceGroupingTests(unittest.TestCase):
    def test_url_normalization_preserves_article_query_and_negative_stance(self):
        items = [post('1', 'Claim', ['https://EXAMPLE.invalid/read?id=1&utm_source=x']),
                 post('2', 'That claim is false', ['https://example.invalid/read?id=1']),
                 post('3', 'Other article', ['https://example.invalid/read?id=2'])]
        result = groups(items)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['kind'], 'SHARED_URL')
        self.assertEqual(result[0]['evidence_post_ids'], ['1', '2'])
        self.assertNotIn('stance', result[0])

    def test_exact_text_preserves_negation_and_does_not_translate(self):
        result = groups([post('a', 'The joint relief exercise is cancelled.'),
                         post('b', 'The joint relief exercise is not cancelled.'),
                         post('c', '공동 재난구호훈련은 취소되었습니다.'),
                         post('d', 'The  joint relief exercise is cancelled.\n')])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['evidence_post_ids'], ['a', 'd'])
        self.assertEqual(groups([post('x', 'hello'), post('y', 'hello')]), [])

    def test_no_transitive_merge_and_deterministic_restart_order(self):
        items = [post('a', 'a', ['https://a.invalid/1']),
                 post('bridge', 'b', ['https://a.invalid/1', 'https://b.invalid/2']),
                 post('c', 'c', ['https://b.invalid/2'])]
        result = groups(items)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(len(g['evidence_post_ids']) == 2 for g in result))
        self.assertEqual(result, groups(list(reversed(items))))

    def test_utc_midnight_does_not_split_observed_resource(self):
        a = post('a', 'a', ['https://example.invalid/1'])
        a['created_at'] = '2026-10-01T23:59:59Z'
        b = post('b', 'b', ['https://example.invalid/1'])
        b['created_at'] = '2026-10-02T00:00:01Z'
        result = groups([a, b])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['evidence_post_ids'], ['a', 'b'])
        self.assertEqual(result[0]['utc_day'], '2026-10-01')

    def test_references_unknown_and_future_originals(self):
        relations = [{'type': 'quotes', 'target_post_id': 'origin'}]
        a, b = post('a', 'a', relations=relations), post('b', 'b', relations=relations)
        self.assertEqual(groups([a, b])[0]['evidence_post_ids'], ['a', 'b'])
        self.assertEqual(groups([a, post('origin', 'o', seconds=10)]), [])
        self.assertEqual(groups([a, post('origin', 'o', seconds=-10)])[0]['evidence_post_ids'], ['a', 'origin'])

    def test_reference_chain_is_one_flow_with_original_children_preserved(self):
        items = [post('origin', 'The complete original claim is available here.', seconds=0),
                 post('quote', 'Comment about the claim', seconds=1,
                      relations=[{'type': 'quotes', 'target_post_id': 'origin'}]),
                 post('quote-quote', 'Another comment on the same chain', seconds=2,
                      relations=[{'type': 'quotes', 'target_post_id': 'quote'}]),
                 post('reply', 'Comment about the claim', seconds=3,
                      relations=[{'type': 'replies_to', 'target_post_id': 'quote-quote'}])]
        result = groups(items)
        self.assertEqual(len(result), 1)
        flow = result[0]
        self.assertEqual(flow['kind'], 'REFERENCE_FLOW')
        self.assertEqual(flow['root_post_ids'], ['origin'])
        self.assertEqual(flow['evidence_post_ids'], ['origin', 'quote', 'quote-quote', 'reply'])
        self.assertEqual(sum(c['kind'] == 'SHARED_REFERENCE' for c in flow['child_groups']), 3)
        self.assertTrue(any(c['kind'] == 'EXACT_TEXT' for c in flow['child_groups']))
        self.assertEqual(result, groups(list(reversed(items))))
        extra = post('late-child', 'Delayed ingestion', seconds=2.5,
                     relations=[{'type': 'quotes', 'target_post_id': 'quote'}])
        self.assertEqual(flow['id'], groups(items + [extra])[0]['id'])

    def test_same_root_full_text_merges_flows_but_comment_bridge_does_not(self):
        original = 'A complete sufficiently long statement about the observed exercise.'
        a, b = post('a', original), post('b', original, seconds=10)
        ra = post('ra', 'a sufficiently long different comment a', seconds=1,
                  relations=[{'type': 'quotes', 'target_post_id': 'a'}])
        rb = post('rb', 'different comment b', seconds=11,
                  relations=[{'type': 'quotes', 'target_post_id': 'b'}])
        result = groups([a, b, ra, rb])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['root_post_ids'], ['a', 'b'])
        self.assertTrue(any(c['kind'] == 'EXACT_TEXT' for c in result[0]['child_groups']))
        unrelated = post('c', 'An entirely different sufficiently long original statement.')
        bridge = post('rc', ra['text'], seconds=2, relations=[{'type': 'quotes', 'target_post_id': 'c'}])
        separated = groups([a, ra, unrelated, bridge])
        self.assertEqual(len(separated), 2)
        self.assertEqual({tuple(c['root_post_ids']) for c in separated}, {('a',), ('c',)})
        self.assertTrue(all(any(child.get('related_post_ids') for child in c['child_groups']) for c in separated))

    def test_mixed_root_bridge_does_not_transitively_join_another_root_copy(self):
        text_a = 'First independent complete original statement with enough detail.'
        text_b = 'Second independent complete original statement with different detail.'
        items = [post('a', text_a), post('b', text_b), post('copy-a', text_a),
                 post('multi', 'one actor quotes two origins', seconds=1, relations=[
                     {'type': 'quotes', 'target_post_id': 'a'}, {'type': 'quotes', 'target_post_id': 'b'}]),
                 post('quote-copy', 'a third comment', seconds=2,
                      relations=[{'type': 'quotes', 'target_post_id': 'copy-a'}])]
        result = groups(items)
        self.assertEqual(len(result), 2)
        self.assertEqual(sorted(len(c['evidence_post_ids']) for c in result), [2, 3])

    def test_reference_time_bounds_and_late_original_resolution(self):
        quote = lambda pid, target, seconds: post(pid, pid, seconds=seconds,
            relations=[{'type': 'quotes', 'target_post_id': target}])
        a, b = quote('a', 'origin', 0), quote('b', 'origin', 1)
        before = groups([a, b])
        self.assertEqual(before[0]['unresolved_target_post_ids'], ['origin'])
        original = post('origin', 'An observed original with enough contextual information.', seconds=-1)
        after = groups([a, b, original])
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]['root_post_ids'], ['origin'])
        self.assertEqual(after[0]['unresolved_target_post_ids'], [])
        self.assertEqual(after, groups([original, b, a]))
        self.assertEqual(groups([quote('old', 'origin', 86400), post('origin', 'origin', seconds=-1)]), [])
        self.assertEqual(len(groups([quote('boundary', 'origin', 86400), post('origin', 'origin')])), 1)
        self.assertEqual(groups([quote('early', 'origin', -1), post('origin', 'origin')]), [])

    def test_text_and_unknown_reference_windows_do_not_chain_indefinitely(self):
        same = 'A complete repeated statement with exactly the same meaning and wording.'
        self.assertEqual(len(groups([post('a', same), post('b', same, seconds=86400),
                                     post('c', same, seconds=86401)])), 1)
        items = [post(str(i), str(i), seconds=i * 50000,
                      relations=[{'type': 'quotes', 'target_post_id': 'missing'}]) for i in range(4)]
        result = groups(items)
        self.assertEqual(len(result), 2)
        self.assertEqual({tuple(c['evidence_post_ids']) for c in result}, {('0', '1'), ('2', '3')})

    def test_explicit_chain_can_span_days_when_each_observed_reference_is_within_24h(self):
        items = [post('origin', 'An original complete statement without semantic inference.'),
                 post('middle', 'middle', seconds=85000, relations=[{'type': 'quotes', 'target_post_id': 'origin'}]),
                 post('last', 'last', seconds=170000, relations=[{'type': 'quotes', 'target_post_id': 'middle'}])]
        result = groups(items)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['root_post_ids'], ['origin'])
        self.assertEqual(result[0]['reference_span_hours'], 24)

    def test_complete_root_sentence_match_retains_related_evidence_without_parent_merge(self):
        sentence = 'The observed relief exercise cancellation has been reported publicly.'
        items = [post('origin-a', sentence + ' I support this statement.'),
                 post('origin-b', sentence + ' I disagree with this statement.', seconds=2),
                 post('reply-a', 'reply a', seconds=1, relations=[{'type': 'quotes', 'target_post_id': 'origin-a'}]),
                 post('reply-b', 'reply b', seconds=3, relations=[{'type': 'quotes', 'target_post_id': 'origin-b'}])]
        result = groups(items)
        self.assertEqual(len(result), 2)
        self.assertEqual({tuple(c['root_post_ids']) for c in result}, {('origin-a',), ('origin-b',)})
        for flow in result:
            evidence = next(c for c in flow['child_groups'] if c['kind'] == 'ROOT_SENTENCE_MATCH')
            self.assertEqual(len(evidence['evidence_post_ids']), 1)
            self.assertEqual(set(evidence['evidence_post_ids'] + evidence['related_post_ids']), {'origin-a', 'origin-b'})
        self.assertNotIn('stance', result[0])
        self.assertEqual(result, groups(list(reversed(items))))
        for root in items[:2]:
            root['urls'] = ['https://news.invalid/' + root['id']]
        self.assertEqual(len(groups(items)), 2)

    def test_generic_opening_cannot_merge_different_events_or_rebuttals(self):
        opening = 'Here is the latest official information about the ongoing regional situation.'
        roots = [post('origin-a', opening + ' The harbor exercise was cancelled.'),
                 post('origin-b', opening + ' The airport drill will proceed as planned.'),
                 post('origin-c', opening + ' The harbor cancellation claim is false.')]
        replies = [post('reply-' + str(i), 'Response ' + str(i), seconds=i + 1,
                   relations=[{'type': 'quotes', 'target_post_id': p['id']}]) for i, p in enumerate(roots)]
        result = groups(roots + replies)
        self.assertEqual(len(result), 3)
        self.assertTrue(all(len(c['evidence_post_ids']) == 2 for c in result))
        self.assertEqual({tuple(c['root_post_ids']) for c in result}, {('origin-a',), ('origin-b',), ('origin-c',)})

    def test_root_sentence_requires_complete_long_text_and_preserves_question_and_negation(self):
        claim = 'The observed relief exercise cancellation has been reported publicly.'
        variants = (claim[:-1] + '?', claim.replace('has been', 'has not been'),
                    claim.replace('relief exercise', 'different exercise'))
        for variant in variants:
            items = [post('a', claim), post('b', variant, seconds=2),
                     post('ra', 'ra', seconds=1, relations=[{'type': 'quotes', 'target_post_id': 'a'}]),
                     post('rb', 'rb', seconds=3, relations=[{'type': 'quotes', 'target_post_id': 'b'}])]
            self.assertEqual(len(groups(items)), 2)
        items = [post('a', 'Short shared report. Tail a'), post('b', 'Short shared report. Tail b'),
                 post('ra', 'ra', seconds=1, relations=[{'type': 'quotes', 'target_post_id': 'a'}]),
                 post('rb', 'rb', seconds=1, relations=[{'type': 'quotes', 'target_post_id': 'b'}])]
        self.assertEqual(len(groups(items)), 2)

    def test_unknown_parent_comments_are_not_eligible_for_root_text_merging(self):
        text = 'A sufficiently long generic copied reaction about the current situation.'
        items = [post('a', text, relations=[{'type': 'quotes', 'target_post_id': 'missing-a'}]),
                 post('b', text, relations=[{'type': 'quotes', 'target_post_id': 'missing-b'}]),
                 post('ra', 'ra', seconds=1, relations=[{'type': 'quotes', 'target_post_id': 'a'}]),
                 post('rb', 'rb', seconds=1, relations=[{'type': 'quotes', 'target_post_id': 'b'}])]
        result = groups(items)
        self.assertEqual(len(result), 2)
        self.assertEqual({tuple(c['evidence_post_ids']) for c in result}, {('a', 'ra'), ('b', 'rb')})

    def test_one_unlinked_copy_retains_complete_original_copy_evidence(self):
        text = 'A short copied comment with enough characters.'
        items = [post('origin', 'Unrelated original'), post('inside', text, seconds=1,
                 relations=[{'type': 'quotes', 'target_post_id': 'origin'}]), post('outside', text, seconds=2)]
        result = groups(items)
        self.assertEqual({pid for group in result for pid in group['evidence_post_ids']}, {'origin', 'inside', 'outside'})
        self.assertEqual(len(result), 2)
        copy = next(g for g in result if g['kind'] == 'EXACT_TEXT')
        self.assertEqual(copy['evidence_post_ids'], ['inside', 'outside'])


class NoAIRuntimeTests(unittest.TestCase):
    def test_no_model_no_pending_no_spurious_coordination_and_replay_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'test.db'
            runtime = Runtime(db, RawOnlyEmbedder(db), no_ai=True, clock=lambda: BASE + timedelta(hours=1))
            runtime.ingest([post('a'), post('b')], stamp(BASE + timedelta(hours=1)))
            data = runtime.dashboard()
            self.assertEqual(data['pipeline']['mode'], 'no-ai')
            self.assertEqual(data['pipeline']['ai_pending_count'], 0)
            self.assertEqual(data['pipeline']['ai_status'], 'disabled')
            self.assertEqual(len(data['cases']), 1)
            self.assertEqual(data['cases'][0]['source'], 'resource')
            self.assertEqual(data['investigations'], [])
            self.assertEqual(data['cases'][0]['alerts'], [])
            self.assertEqual(runtime.ai_pending()['items'], [])
            with self.assertRaisesRegex(ValueError, 'disabled'):
                runtime.receive_ai([])
            restarted = Runtime(db, RawOnlyEmbedder(db), no_ai=True, clock=lambda: BASE + timedelta(days=1))
            self.assertEqual(restarted.dashboard()['cases'], data['cases'])
            self.assertEqual(restarted.ingest([post('a'), post('b')], stamp(BASE))['inserted'], 0)

    def test_switch_preserves_ai_rows_but_removes_active_enrichment(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'test.db'
            runtime = Runtime(db, RawOnlyEmbedder(db), clock=lambda: BASE + timedelta(hours=1))
            runtime.ingest([post('a'), post('b')], stamp(BASE + timedelta(hours=1)))
            item = runtime.ai_pending()['items'][0]
            runtime.receive_ai([{'post_id': item['post_id'], 'raw_sha256': item['raw_sha256'],
                'model_version': 'fixture', 'scope_id': 'fixture', 'revision': 1, 'cluster_id': 'topic'}])
            no_ai = Runtime(db, RawOnlyEmbedder(db), no_ai=True, clock=lambda: BASE + timedelta(hours=1))
            data = no_ai.dashboard()
            self.assertTrue(all(not p['ai_clusters'] and p['ai_status'] == 'disabled' for c in data['cases'] for p in c['posts']))
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM ai_results').fetchone()[0], 1)
            restored = Runtime(db, RawOnlyEmbedder(db), clock=lambda: BASE + timedelta(hours=1))
            self.assertEqual(restored.dashboard()['pipeline']['ai_received_count'], 1)

    def test_raw_workbook_candidates_remain_visible_in_resource_group(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'test.db'
            runtime = Runtime(db, RawOnlyEmbedder(db), no_ai=True, clock=lambda: BASE + timedelta(hours=1))
            runtime.ingest([post('a', '공동훈련 취소 주장은 사실인지 확인해야 합니다.'),
                            post('b', '공동훈련 취소 주장은 사실인지 확인해야 합니다.')], stamp(BASE + timedelta(hours=1)))
            case = runtime.dashboard()['cases'][0]
            self.assertTrue(any(p['scenario_id'] == '30' for p in case['response_plans']))
            self.assertFalse(any(p['scenario_id'] == '22' for p in case['response_plans']))


if __name__ == '__main__':
    unittest.main()
