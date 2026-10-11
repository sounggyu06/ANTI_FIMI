import hashlib
import json
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from engine import LexicalDemoEmbedder, dumps, parse_time
from server import Runtime, make_handler
from sessions import SessionConflict, active_database


def post(pid):
    return {'id': pid, 'account_id': 'account-' + pid,
            'created_at': '2026-10-01T00:00:00Z', 'text': 'Public evidence ' + pid}


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ANTI_FIMI_sessions_')
        self.folder = Path(self.temp.name)
        self.base = self.folder / 'demo.sqlite3'
        self.watch = self.folder / 'feed.jsonl'
        self.clock = lambda: parse_time('2026-10-01T08:00:00Z')

    def tearDown(self):
        self.temp.cleanup()

    def runtime(self, watch=None, no_ai=True):
        return Runtime(self.base, LexicalDemoEmbedder(), watch=watch, clock=self.clock, no_ai=no_ai)

    def test_empty_new_session_preserves_original_records_and_workbook(self):
        runtime = self.runtime()
        runtime.ingest([post('old')])
        before = runtime.dashboard()
        digest = hashlib.sha256(self.base.read_bytes()).hexdigest()
        reset = runtime.new_demo('initial')
        after = reset['dashboard']
        for field in ('post_count', 'account_count', 'case_count', 'alert_count', 'pending_post_count'):
            self.assertEqual(after['summary'][field], 0, field)
        self.assertEqual(after['cases'], [])
        self.assertEqual(after['investigations'], [])
        self.assertEqual(after['unlinked_posts'], [])
        self.assertEqual(after['playbook']['workbook_hash'], before['playbook']['workbook_hash'])
        self.assertEqual(after['pipeline']['mode'], 'no-ai')
        self.assertEqual(hashlib.sha256(self.base.read_bytes()).hexdigest(), digest)
        self.assertNotEqual(runtime.db, self.base)
        self.assertIsNone(after['feed']['last_ingested_at'])

    def test_restart_follows_active_session_and_token(self):
        runtime = self.runtime()
        runtime.ingest([post('old')])
        reset = runtime.new_demo('initial')
        restarted = self.runtime()
        self.assertEqual(restarted.db, runtime.db)
        self.assertEqual(restarted.session, reset['session'])
        self.assertEqual(restarted.dashboard()['summary']['post_count'], 0)
        restarted.ingest([post('new')], session_id=reset['session']['id'])
        again = self.runtime()
        self.assertEqual(again.dashboard()['summary']['post_count'], 1)
        with closing(sqlite3.connect(self.base)) as old:
            self.assertEqual(old.execute('SELECT id FROM posts').fetchall(), [('old',)])

    def test_watch_skips_baseline_rewrites_and_carries_exclusions_across_reset(self):
        runtime = self.runtime(self.watch)
        self.watch.write_text(dumps(post('old')) + '\n' + dumps(post('not-ingested')) + '\n', encoding='utf-8')
        runtime.ingest([post('old')])
        runtime.new_demo('initial')
        runtime.poll_file()
        self.assertEqual(runtime.dashboard()['summary']['post_count'], 0)
        self.watch.write_text(''.join(dumps(post(pid)) + '\n' for pid in ['old', 'not-ingested', 'new']), encoding='utf-8')
        runtime.poll_file()
        self.assertEqual(runtime.dashboard()['summary']['post_count'], 1)
        runtime.new_demo(runtime.session['id'])
        self.watch.write_text(''.join(dumps(post(pid)) + '\n' for pid in ['new', 'old', 'newer']), encoding='utf-8')
        restarted = self.runtime(self.watch)
        restarted.poll_file()
        with closing(sqlite3.connect(restarted.db)) as connection:
            self.assertEqual(connection.execute('SELECT id FROM posts').fetchall(), [('newer',)])

    def test_partial_old_line_completion_is_not_new_evidence(self):
        runtime = self.runtime(self.watch)
        line = dumps(post('partial')).encode()
        self.watch.write_bytes(line[:20])
        runtime.new_demo('initial')
        with self.watch.open('ab') as feed:
            feed.write(line[20:] + b'\n')
        runtime.poll_file()
        self.assertEqual(runtime.dashboard()['summary']['post_count'], 0)
        with self.watch.open('ab') as feed:
            feed.write(dumps(post('fresh')).encode() + b'\n')
        runtime.poll_file()
        self.assertEqual(runtime.dashboard()['summary']['post_count'], 1)
        self.watch.write_bytes(dumps(post('fresh')).encode() + b'\n' + line + b'\n')
        runtime.poll_file()
        self.assertEqual(runtime.dashboard()['summary']['post_count'], 1)

    def test_pointer_failure_leaves_old_runtime_and_data_active(self):
        runtime = self.runtime()
        runtime.ingest([post('old')])
        with patch('sessions.os.replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                runtime.new_demo('initial')
        self.assertEqual(runtime.session['id'], 'initial')
        self.assertEqual(runtime.db, self.base)
        self.assertEqual(runtime.dashboard()['summary']['post_count'], 1)
        self.assertEqual(active_database(self.base), self.base)

    def test_missing_selected_database_fails_without_silent_fallback(self):
        runtime = self.runtime()
        runtime.new_demo('initial')
        runtime.db.unlink()
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            self.runtime()

    def test_stale_reset_and_ingestion_cannot_mutate_new_session(self):
        runtime = self.runtime()
        runtime.new_demo('initial')
        for token in (None, 'initial', 'other'):
            with self.assertRaises(SessionConflict):
                runtime.ingest([post('old')], session_id=token)
        with self.assertRaises(SessionConflict):
            runtime.new_demo('initial')
        self.assertEqual(runtime.dashboard()['summary']['post_count'], 0)
        token = runtime.session['id']
        runtime.ingest([post('new')], session_id=token)
        self.assertEqual(runtime.ingest([post('new')], session_id=token)['duplicates'], 1)

    def test_ai_results_reject_previous_session(self):
        runtime = self.runtime(no_ai=False)
        runtime.new_demo('initial')
        with self.assertRaises(SessionConflict):
            runtime.receive_ai([], session_id='initial')

    def test_real_http_reset_token_conflicts_and_fresh_ingestion(self):
        runtime = self.runtime()
        runtime.ingest([post('old')])
        http = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(runtime, self.folder))
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{http.server_port}'

        def send(path, payload, reset_header=False):
            headers = {'Content-Type': 'application/json'}
            if reset_header:
                headers['X-ANTI-FIMI-Client'] = 'dashboard'
            with urlopen(Request(base + path, dumps(payload).encode(), headers), timeout=5) as response:
                return json.load(response)

        try:
            with urlopen(base + '/api/session') as response:
                self.assertEqual(json.load(response)['session']['id'], 'initial')
            with self.assertRaises(HTTPError) as error:
                send('/api/demo/new', {'session_id': 'initial'})
            self.assertEqual(error.exception.code, 400)
            reset = send('/api/demo/new', {'session_id': 'initial'}, True)
            self.assertEqual(reset['dashboard']['summary']['post_count'], 0)
            with self.assertRaises(HTTPError) as error:
                send('/api/posts', {'posts': [post('old')]})
            self.assertEqual(error.exception.code, 409)
            result = send('/api/posts', {'session_id': reset['session']['id'], 'posts': [post('fresh')]})
            self.assertEqual(result['inserted'], 1)
            self.assertEqual(result['session_id'], reset['session']['id'])
        finally:
            http.shutdown(); http.server_close(); thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
