import unittest
from source_trace import analyze_source_trace


def post(n, minute, account=None, parents=()):
    return {"id": n, "account_id": account or n, "created_at": f"2026-10-10T10:{minute:02d}:00Z",
            "text": "example " + n, "relations": [
                {"type": typ, "target_post_id": dest} for typ, dest in parents]}


class SourceTraceTests(unittest.TestCase):
    def test_chain_and_earliest_differ(self):
        posts = [post('unrelated', 0), post('root', 1), post('mid', 2, parents=[('quotes', 'root')]),
                 post('last', 3, parents=[('reposts', 'mid')])]
        result = analyze_source_trace(posts)
        self.assertEqual(result['earliest_observed']['post_id'], 'unrelated')
        self.assertEqual(result['leading_root']['post_id'], 'root')
        self.assertEqual(result['observed_max_depth'], 2)
        self.assertEqual(result['observed_edge_count'], 2)

    def test_no_reference_means_no_proven_origin(self):
        result = analyze_source_trace([post('a', 0), post('b', 1)])
        self.assertEqual(result['claim'], 'chronological_only')
        self.assertIsNone(result['leading_root'])

    def test_external_and_unavailable(self):
        r = analyze_source_trace([
            post('b', 2, parents=[('quotes', 'outside'), ('reposts', 'not_seen')])], {'b', 'outside'})
        self.assertEqual(r['outside_scope_references'], 1)
        self.assertEqual(r['unavailable_references'], 1)
        self.assertEqual(r['observed_edge_count'], 0)

    def test_invalid_temporal_edge(self):
        r = analyze_source_trace([post('future', 9), post('earlier', 0, parents=[('quotes', 'future')])])
        self.assertEqual(r['time_inconsistent_references'], 1)
        self.assertEqual(r['observed_edge_count'], 0)

    def test_duplicate_relations(self):
        r = analyze_source_trace([post('a', 0), post('b', 1, parents=[('quotes', 'a'), ('quotes', 'a')])])
        self.assertEqual(r['observed_edge_count'], 1)

if __name__ == '__main__':
    unittest.main()
