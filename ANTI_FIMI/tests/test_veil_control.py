import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from engine import LexicalDemoEmbedder, parse_time
from server import Runtime
from veil_control import VeilControl


class VeilIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.crawler = self.folder / 'crawler'
        self.crawler.mkdir()
        (self.crawler / 'live.py').touch()

    def tearDown(self):
        self.temp.cleanup()

    def control(self):
        with patch.object(VeilControl, 'request', return_value={'app': 'veil-social', 'sessionId': 'site-A'}):
            return VeilControl('http://127.0.0.1:5180', self.crawler,
                               'http://127.0.0.1:8788', self.folder / 'demo.sqlite3', sys.executable)

    def test_changed_site_is_not_reset(self):
        control = self.control()
        with patch.object(control, 'request', return_value={'app': 'veil-social', 'sessionId': 'site-B'}) as request:
            with self.assertRaisesRegex(RuntimeError, 'instance changed'):
                control.prepare_reset()
            self.assertEqual(request.call_count, 1)
            self.assertEqual(control.status()['status'], 'error')

    def test_stale_status_is_not_ready(self):
        control = self.control()
        with patch('veil_control.subprocess.Popen') as process:
            process.return_value.poll.return_value = None
            control.start('initial')
            control.status_file.write_text(json.dumps({'session_id': 'other', 'baseline_ready': True}), encoding='utf-8')
            self.assertFalse(control.status()['baseline_ready'])
            command = process.call_args.args[0]
            self.assertIn('--parent-pid', command)

    def runtime(self):
        return Runtime(self.folder / 'demo.sqlite3', LexicalDemoEmbedder(), no_ai=True,
                       clock=lambda: parse_time('2026-10-11T09:00:00Z'))

    def test_missing_status_heartbeat_is_visible_while_child_is_alive(self):
        control = self.control()
        with patch('veil_control.subprocess.Popen') as process:
            process.return_value.poll.return_value = None
            control.start('initial')
            control.status_file.write_text(json.dumps({'session_id': 'initial', 'status': 'running', 'baseline_ready': True}), encoding='utf-8')
            control.started = time.time() - 60
            old = time.time() - 40
            os.utime(control.status_file, (old, old))
            state = control.status()
            self.assertEqual(state['status'], 'error')
            self.assertFalse(state['baseline_ready'])
            self.assertIn('30초', state['error'])

    def test_reset_stops_collector_outside_data_lock_and_blocks_old_input(self):
        runtime = self.runtime()
        observed = []

        class Collector:
            def prepare_reset(self):
                def acquire():
                    acquired = runtime.lock.acquire(timeout=1)
                    observed.append(acquired)
                    if acquired:
                        runtime.lock.release()
                thread = threading.Thread(target=acquire)
                thread.start(); thread.join(timeout=2)
                with self_test.assertRaises(RuntimeError):
                    runtime.ingest([{'id': 'late', 'account_id': 'a', 'created_at': '2026-10-11T08:00:00Z', 'text': 'x'}])

            def start(self, session_id):
                observed.append(session_id)

            def wait_ready(self):
                return True

            def status(self):
                return {'status': 'running', 'baseline_ready': True}

        self_test = self
        runtime.veil = Collector()
        result = runtime.new_demo('initial')
        self.assertEqual(observed, [True, result['session']['id']])
        self.assertEqual(result['dashboard']['summary']['post_count'], 0)
        self.assertTrue(result['dashboard']['feed']['collector']['baseline_ready'])
        self.assertFalse(runtime.resetting)

    def test_source_reset_failure_preserves_original_engine_session(self):
        runtime = self.runtime()
        runtime.ingest([{'id': 'old', 'account_id': 'a', 'created_at': '2026-10-11T08:00:00Z', 'text': 'x'}])
        original = runtime.db
        class Collector:
            def prepare_reset(self):
                raise RuntimeError('source unavailable')
            def status(self):
                return {'status': 'stopped'}
        runtime.veil = Collector()
        with self.assertRaisesRegex(RuntimeError, 'source unavailable'):
            runtime.new_demo('initial')
        self.assertEqual(runtime.db, original)
        self.assertEqual(runtime.session['id'], 'initial')
        self.assertEqual(runtime.dashboard()['summary']['post_count'], 1)
        self.assertFalse(runtime.resetting)


if __name__ == '__main__':
    unittest.main()
