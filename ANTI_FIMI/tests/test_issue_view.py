from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

from engine import parse_time, stamp
from server import Runtime, RawOnlyEmbedder


class IssueViewTests(unittest.TestCase):
    def test_issue_navigation_keeps_cross_issue_full_alert_evidence(self):
        now = parse_time('2026-10-11T00:00:00Z')
        raw = [{'id': str(i), 'account_id': str(i),
                'created_at': stamp(now + timedelta(seconds=i)),
                'text': ('Frontline report ' if i < 6 else 'Economy report ') + str(i),
                'urls': ['https://news.invalid/shared']} for i in range(12)]
        raw.append({'id': 'unknown', 'account_id': 'reader', 'created_at': stamp(now), 'text': 'Could anyone provide the source?'})
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'test.sqlite3'
            clock = lambda: now + timedelta(seconds=30)
            runtime = Runtime(db, RawOnlyEmbedder(db), no_ai=True, clock=clock)
            runtime.ingest(raw)
            data = runtime.dashboard()
            self.assertEqual(len(data['issue_cases']), 2)
            self.assertEqual(data['early_alerts_count'], 1)
            self.assertEqual(data['global_signals_count'], 0)
            self.assertEqual([p['id'] for p in data['issue_unclassified_posts']], ['unknown'])
            alerts = set()
            for case in data['issue_cases']:
                self.assertEqual(case['post_count'], 6)
                self.assertIn('spread', case)
                self.assertEqual(case['spread']['current_post_count'], 6)
                self.assertEqual(case['alert_count'], 1)
                alert = case['alerts'][0]
                alerts.add(alert['id'])
                self.assertTrue(alert['cross_issue'])
                self.assertEqual(len(alert['evidence_post_ids']), 12)
                self.assertEqual({p['id'] for p in alert['evidence_posts']}, set(alert['evidence_post_ids']))
                self.assertTrue(all(p['issue_matches'][0]['matched_terms'] for p in case['posts']))
                self.assertTrue(all(set(n['evidence_post_ids']) <= {p['id'] for p in case['posts']} for n in case['narratives']))
            self.assertEqual(len(alerts), 1)
            again = Runtime(db, RawOnlyEmbedder(db), no_ai=True, clock=clock).dashboard()
            self.assertEqual([c['id'] for c in data['issue_cases']], [c['id'] for c in again['issue_cases']])
            self.assertEqual({a['id'] for c in again['issue_cases'] for a in c['alerts']}, alerts)

    def test_unclassified_material_burst_remains_visible_without_forced_topic(self):
        now = parse_time('2026-10-11T00:00:00Z')
        raw = [{'id': str(i), 'account_id': str(i), 'created_at': stamp(now + timedelta(seconds=i)),
                'text': f'Public bulletin item {i}', 'urls': ['https://news.invalid/article']} for i in range(12)]
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'test.sqlite3'
            runtime = Runtime(db, RawOnlyEmbedder(db), no_ai=True, clock=lambda: now + timedelta(seconds=30))
            runtime.ingest(raw)
            data = runtime.dashboard()
            self.assertEqual(data['issue_cases'], [])
            self.assertEqual(len(data['issue_unclassified_posts']), 12)
            self.assertEqual(data['early_alerts_count'], 1)
            self.assertEqual(len(data['unassigned_alert_cases']), 1)
            self.assertEqual(data['unassigned_alert_cases'][0]['alert_count'], 1)


if __name__ == '__main__':
    unittest.main()
