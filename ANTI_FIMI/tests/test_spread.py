from datetime import timedelta
import unittest
import tempfile
from pathlib import Path

from engine import parse_time, stamp
from spread import spread_metrics


NOW = parse_time('2026-10-10T15:00:00Z')
START = NOW - timedelta(minutes=30)


def posts(count, seconds, prefix='p', accounts=3):
    return [{'id': f'{prefix}{i}', 'account_id': f'a{i % accounts}',
             'created_at': stamp(NOW + timedelta(seconds=seconds + i))} for i in range(count)]


class SpreadTests(unittest.TestCase):
    def analyze(self, rows, start=START):
        return spread_metrics(rows, NOW, start)

    def test_windows_are_equal_exclusive_and_future_rows_are_excluded(self):
        rows = [*posts(1, -600, 'excluded'), *posts(1, -300, 'previous'),
                *posts(1, -299, 'current'), *posts(1, 0, 'now'), *posts(1, 1, 'future')]
        data = self.analyze(rows)
        self.assertEqual((data['previous_post_count'], data['current_post_count']), (1, 2))
        self.assertEqual(sum(p['post_count'] for p in data['history']), 4)

    def test_startup_and_unknown_history_do_not_claim_acceleration(self):
        rows = posts(30, -120)
        self.assertEqual(self.analyze(rows, NOW - timedelta(minutes=4))['state'], 'insufficient')
        data = self.analyze(rows, None)
        self.assertEqual(data['state'], 'insufficient')
        self.assertFalse(any(p['within_observed_range'] for p in data['history']))

    def test_zero_to_one_and_single_account_bursts_are_low_volume(self):
        self.assertEqual(self.analyze(posts(1, -60))['state'], 'low_volume')
        self.assertEqual(self.analyze(posts(20, -60, accounts=1))['state'], 'low_volume')

    def test_new_event_after_available_history_can_surge(self):
        self.assertEqual(self.analyze(posts(12, -60))['state'], 'surging')

    def test_states_use_both_activity_and_account_breadth(self):
        self.assertEqual(self.analyze(posts(6, -400, 'old') + posts(6, -60))['state'], 'steady')
        self.assertEqual(self.analyze(posts(6, -400, 'old') + posts(9, -60))['state'], 'accelerating')
        self.assertEqual(self.analyze(posts(6, -400, 'old') + posts(12, -60))['state'], 'surging')
        self.assertEqual(self.analyze(posts(12, -400, 'old') + posts(5, -60))['state'], 'declining')
        self.assertEqual(self.analyze(posts(12, -400, 'old'))['state'], 'declining')

    def test_late_order_and_replay_duplicates_do_not_inflate_spread(self):
        rows = posts(6, -400, 'old') + posts(9, -60)
        self.assertEqual(self.analyze(rows), self.analyze(list(reversed(rows)) + rows))
        self.assertEqual(self.analyze(rows)['current_account_count'], 3)

    def test_all_events_share_cutoff_and_dormant_event_cools(self):
        rows = posts(12, -400)
        data = self.analyze(rows)
        self.assertEqual(data['as_of'], stamp(NOW))
        self.assertEqual(data['current_post_count'], 0)
        self.assertEqual(data['state'], 'declining')
        self.assertLessEqual(len(data['history']), 120)
        self.assertEqual(sum(point['post_count'] for point in data['history']), 12)
        self.assertFalse(data['calibrated'])

    def test_first_post_is_visible_immediately_in_partial_current_bucket(self):
        row = {'id': 'first', 'account_id': 'a', 'created_at': stamp(NOW + timedelta(microseconds=250000))}
        as_of = parse_time(row['created_at'])
        data = spread_metrics([row], as_of, as_of)
        self.assertEqual(data['bucket_seconds'], 1)
        self.assertEqual(len(data['history']), 1)
        point = data['history'][0]
        self.assertEqual(point['post_count'], 1)
        self.assertTrue(point['observed'])
        self.assertTrue(point['partial'])
        self.assertTrue(point['partial_last'])
        self.assertEqual(point['end'], stamp(as_of))

    def test_first_twenty_seconds_show_second_level_activity_and_sparse_zeros(self):
        rows = [{'id': str(i), 'account_id': 'a', 'created_at': stamp(NOW + timedelta(seconds=i))} for i in [0, 2, 20]]
        data = spread_metrics(rows, NOW + timedelta(seconds=20), NOW)
        self.assertEqual(data['bucket_seconds'], 1)
        self.assertEqual(len(data['history']), 21)
        self.assertEqual([i for i, point in enumerate(data['history']) if point['observed']], [0, 2, 20])
        self.assertEqual(data['history'][1]['post_count'], 0)
        self.assertFalse(data['history'][0]['partial'])
        self.assertTrue(data['history'][-1]['partial_last'])

    def test_history_expands_thirty_seconds_five_and_twenty_minutes_without_losing_posts(self):
        previous_span = -1
        previous_step = 0
        for elapsed in [30, 300, 1200, 86400 * 15]:
            with self.subTest(elapsed=elapsed):
                rows = [{'id': str(i), 'account_id': 'a' + str(i % 3),
                         'created_at': stamp(NOW + timedelta(seconds=i))} for i in [0, 3, elapsed]]
                data = spread_metrics(rows, NOW + timedelta(seconds=elapsed), NOW)
                self.assertLessEqual(len(data['history']), 120)
                self.assertEqual(sum(point['post_count'] for point in data['history']), 3)
                self.assertGreater(data['history_span_seconds'], previous_span)
                self.assertGreaterEqual(data['bucket_seconds'], previous_step)
                self.assertLessEqual(parse_time(data['history_start']), NOW)
                self.assertEqual(data['history_end'], stamp(NOW + timedelta(seconds=elapsed)))
                for point in data['history']:
                    self.assertEqual(parse_time(point['time']).timestamp() % data['bucket_seconds'], 0)
                previous_span, previous_step = data['history_span_seconds'], data['bucket_seconds']

    def test_case_history_ignores_earlier_global_collection_start_and_retains_idle_zeros(self):
        rows = [{'id': 'p', 'account_id': 'a', 'created_at': stamp(NOW)}]
        fresh = spread_metrics(rows, NOW + timedelta(seconds=5), NOW - timedelta(days=30))
        self.assertEqual(len(fresh['history']), 6)
        self.assertEqual(fresh['history_start'], stamp(NOW))
        idle = spread_metrics(rows, NOW + timedelta(minutes=20), NOW - timedelta(days=30))
        self.assertLessEqual(len(idle['history']), 120)
        self.assertEqual(idle['history'][0]['post_count'], 1)
        self.assertEqual(idle['history'][-1]['post_count'], 0)
        self.assertFalse(idle['history'][-1]['observed'])
        self.assertTrue(idle['history'][-1]['within_observed_range'])

    def test_empty_future_only_and_duplicate_posts_do_not_make_plot_activity(self):
        empty = self.analyze([])
        future = self.analyze(posts(1, 1))
        self.assertEqual(empty['history'], [])
        self.assertEqual(future['history'], [])
        self.assertEqual(empty['history_span_seconds'], 0)
        rows = posts(1, -1)
        self.assertEqual(self.analyze(rows), self.analyze(rows + rows))

    def test_live_snapshot_cools_without_new_posts_but_replay_keeps_explicit_clock(self):
        from server import Runtime, RawOnlyEmbedder
        for replay in [False, True]:
            with self.subTest(replay=replay), tempfile.TemporaryDirectory() as folder:
                db = Path(folder) / 'test.sqlite3'
                clock = [NOW]
                runtime = Runtime(db, RawOnlyEmbedder(db), clock=lambda: clock[0])
                rows = [{'id': 'older', 'account_id': 'normal', 'text': 'normal', 'created_at': stamp(START)}]
                for episode, offset in enumerate([-290, -200, -110]):
                    for account in range(3):
                        rows.append({'id': f'{episode}-{account}', 'account_id': f'a{account}',
                                     'text': 'test', 'created_at': stamp(NOW + timedelta(seconds=offset + account)),
                                     'urls': [f'https://example.invalid/{episode}']})
                runtime.ingest(rows, stamp(NOW) if replay else None)
                self.assertEqual(runtime.dashboard()['investigations'][0]['spread']['state'], 'surging')
                clock[0] += timedelta(minutes=6)
                after = runtime.dashboard()
                self.assertEqual(after['investigations'][0]['spread']['state'], 'surging' if replay else 'declining')
                self.assertEqual(after['spread_clock']['mode'], 'replay' if replay else 'live')


if __name__ == '__main__':
    unittest.main()
