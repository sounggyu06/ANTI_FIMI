import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy_demo import BASE, RawOnlyEmbedder, Runtime, demo_posts, public_handler, stamp, timedelta


class PublicDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        folder = Path(cls.temporary.name)
        static = folder / 'static'
        static.mkdir()
        (static / 'index.html').write_text('<html>synthetic demo</html>', encoding='utf-8')
        db = folder / 'synthetic.sqlite3'
        cls.runtime = Runtime(db, RawOnlyEmbedder(db), no_ai=True)
        cls.runtime.ingest(demo_posts(), stamp(BASE + timedelta(hours=6)))
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), public_handler(cls.runtime, static))
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.worker.join(timeout=5)
        cls.server.server_close()
        cls.temporary.cleanup()

    def test_synthetic_dashboard_and_static_page_are_served(self):
        with urlopen(self.url + '/api/dashboard', timeout=5) as response:
            data = json.load(response)
        self.assertEqual(data['global_signals_count'], 15)
        self.assertEqual(len(data['investigations']), 1)
        self.assertEqual(data['pipeline']['ai_received_count'], 0)
        self.assertEqual(data['pipeline']['ai_pending_count'], 0)
        with urlopen(self.url + '/', timeout=5) as response:
            self.assertIn(b'synthetic demo', response.read())

    def test_mutations_are_rejected_without_changing_snapshot(self):
        before = self.runtime.dashboard()['snapshot_id']
        for endpoint in ['/api/posts', '/api/ai/results', '/api/playbook/reload', '/api/demo/new']:
            with self.subTest(endpoint=endpoint):
                request = Request(self.url + endpoint, data=b'{}', headers={'Content-Type': 'application/json'})
                with self.assertRaises(HTTPError) as error:
                    urlopen(request, timeout=5)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
        self.assertEqual(self.runtime.dashboard()['snapshot_id'], before)

    def test_media_upload_keeps_existing_size_and_type_validation(self):
        request = Request(self.url + '/api/media/verify', data=b'not an image', headers={'Content-Type': 'image/png'})
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=5)
        self.assertEqual(error.exception.code, 415)
        error.exception.close()


if __name__ == '__main__':
    unittest.main()
