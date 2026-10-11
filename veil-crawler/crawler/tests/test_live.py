import json
import io
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import requests

import live


def article(post_id="p1", account="a1", timestamp="2026-01-01T10:00:00.123+09:00", text="public post", attrs="", likes=0):
    return (f'<article class="post" data-post-id="{post_id}" data-author-id="{account}" {attrs}>'
            f'<time class="post-time" datetime="{timestamp}"></time>'
            f'<div class="post-content">{text}</div><span class="like-count">{likes}</span></article>')


class Response:
    def __init__(self, code=200, text="", payload=None):
        self.status_code, self.text, self.payload = code, text, payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class HTTP:
    def __init__(self):
        self.headers = {}
        self.html = ""
        self.session = "demo1"
        self.posts = []
        self.responses = []
        self.session_offline = False
        self.source_offline = False

    def get(self, url, **kwargs):
        if url.endswith("/api/session"):
            if self.session_offline:
                raise requests.ConnectionError("engine offline")
            return Response(payload={"session": {"id": self.session}})
        if self.source_offline:
            raise requests.ConnectionError("source offline")
        return Response(text=self.html)

    def post(self, url, data, **kwargs):
        self.posts.append(json.loads(data))
        response = self.responses.pop(0) if self.responses else Response()
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        pass


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.http = HTTP()
        self.collector = self.create()

    def create(self, session="demo1"):
        return live.Collector("http://127.0.0.1:5180", "http://127.0.0.1:8787", session,
                              self.root / "outbox.sqlite3", self.root / "status.json", self.http)

    def tearDown(self):
        self.collector.close()
        self.temporary.cleanup()

    def empty_bootstrap(self):
        self.collector.poll()

    def test_baseline_exclusion_is_persistent_and_reactions_do_not_reingest(self):
        self.http.html = article("old")
        self.assertEqual(self.collector.poll()["baseline"], 1)
        self.collector.close()
        self.collector = self.create()
        self.http.html = article("old", likes=10) + article("new")
        result = self.collector.poll()
        self.assertEqual((result["baseline"], result["sent"]), (1, 1))
        self.http.html = article("new", likes=100)
        self.collector.poll()
        self.assertEqual(len(self.http.posts), 1)
        self.assertNotIn("like_count", self.http.posts[0]["posts"][0])

    def test_sorted_actual_instant_and_original_milliseconds_references(self):
        self.empty_bootstrap()
        self.http.html = article("later", timestamp="2026-01-01T10:00:00.123+09:00") + article(
            "earlier", timestamp="2026-01-01T00:00:00.456Z", attrs='data-language="ja" data-retweet-original="root" data-reference-type="quotes" data-reply-to="reply"')
        self.collector.poll()
        posts = self.http.posts[0]["posts"]
        self.assertEqual([p["source_post_id"] for p in posts], ["earlier", "later"])
        self.assertEqual(posts[0]["created_at"], "2026-01-01T00:00:00.456Z")
        self.assertEqual(posts[0]["language_hint"], "ja")
        self.assertEqual([r["type"] for r in posts[0]["relations"]], ["quotes", "replies_to"])
        self.assertTrue(posts[0]["relations"][0]["target_post_id"].endswith(":post:root"))
        self.assertEqual(self.http.posts[0]["session_id"], "demo1")

    def test_unavailable_engine_keeps_staging_and_restart_retries_exact_payload(self):
        self.empty_bootstrap()
        self.http.session_offline = True
        self.http.responses = [requests.Timeout("lost acknowledgement")]
        self.http.html = article("p1")
        self.assertEqual(self.collector.poll()["pending"], 1)
        first = self.http.posts[0]
        self.collector.close()
        self.collector = self.create()
        self.http.responses = [Response(503)]
        self.http.html = article("p1", text="changed after first collection") + article("p2")
        result = self.collector.poll()
        self.assertEqual(result["pending"], 2)
        self.assertEqual(self.http.posts[1]["posts"][0], first["posts"][0])
        self.http.session_offline = False
        self.assertEqual(self.collector.poll()["sent"], 2)

    def test_session_mismatch_stops_without_relabel(self):
        self.empty_bootstrap()
        self.http.session = "demo2"
        self.http.html = article("new")
        with self.assertRaises(live.SessionChanged):
            self.collector.poll()
        self.assertEqual(self.collector.write_status()["seen"], 0)

    def test_post_409_does_not_ack_and_cli_returns_three(self):
        self.empty_bootstrap()
        self.http.html = article()
        self.http.responses = [Response(409)]
        with self.assertRaises(live.SessionChanged):
            self.collector.poll()
        self.assertEqual(self.collector.write_status()["pending"], 1)
        with patch.object(live, "Collector", return_value=self.collector), patch.object(self.collector, "close"), patch.object(self.collector, "poll", side_effect=live.SessionChanged("changed")):
            code = live.main(["--source", "http://source", "--engine", "http://engine", "--session-id", "demo1", "--state", "unused", "--once"])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads((self.root / "status.json").read_text(encoding="utf-8"))["status"], "stopped")

    def test_malformed_rows_are_rejected_individually(self):
        self.empty_bootstrap()
        self.http.html = (article("", text="missing ID") + article("no-timezone", timestamp="2026-01-01T12:00:00")
                          + article("future", timestamp="2099-01-01T12:00:00Z")
                          + article("empty", text="") + article("good"))
        result = self.collector.poll()
        self.assertEqual((result["sent"], result["rejected"]), (1, 4))
        self.collector.poll()
        self.assertEqual(self.collector.write_status()["rejected"], 4)

    def test_poison_batch_400_splits_and_preserves_good_rows(self):
        self.empty_bootstrap()
        self.http.html = article("p1") + article("p2")
        self.http.responses = [Response(400), Response(400, "invalid ID"), Response()]
        result = self.collector.poll()
        self.assertEqual((result["sent"], result["rejected"], result["pending"]), (1, 1, 0))

    def test_state_binding_cannot_be_reused_by_other_session(self):
        with self.assertRaisesRegex(ValueError, "belongs to another"):
            self.create("demo2")

    def test_failed_initial_fetch_does_not_initialize_baseline(self):
        self.http.source_offline = True
        self.assertFalse(self.collector.poll()["baseline_ready"])
        self.http.source_offline = False
        self.http.html = article()
        result = self.collector.poll()
        self.assertTrue(result["baseline_ready"])
        self.assertEqual(result["baseline"], 1)

    def test_parent_exit_between_fetch_and_delivery_preserves_pending(self):
        self.empty_bootstrap()
        self.http.html = article("pending")
        alive = iter((True, True, False))
        with self.assertRaises(live.ParentExited):
            self.collector.poll(lambda: next(alive))
        self.assertEqual(self.collector.write_status()["pending"], 1)
        self.assertEqual(self.http.posts, [])

    def test_parent_exit_cli_stops_normally(self):
        with patch.object(live, "Collector", return_value=self.collector), patch.object(self.collector, "close"), patch.object(live, "ParentWatcher") as watcher:
            watcher.return_value.alive.return_value = False
            code = live.main(["--source", "http://source", "--engine", "http://engine", "--session-id", "demo1", "--state", "unused", "--parent-pid", "123", "--once"])
            self.assertEqual(code, 0)
            watcher.return_value.close.assert_called_once()
        self.assertEqual(self.collector.write_status(stopped=True)["status"], "stopped")

    def test_status_sharing_lock_retries_then_recovers(self):
        self.empty_bootstrap()
        actual_replace = live.os.replace
        paths = []

        def replace(source, target):
            paths.append(Path(source))
            if len(paths) < 3:
                raise PermissionError("Windows sharing lock")
            actual_replace(source, target)

        with patch.object(live.os, "replace", side_effect=replace), patch.object(live.time, "sleep") as sleep:
            result = self.collector.write_status()
        self.assertIsNone(result["status_write_error"])
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(len(paths), 3)
        self.assertTrue((self.root / "status.json").is_file())
        self.assertEqual(list(self.root.glob("status.json.*.tmp")), [])

    def test_permanent_status_denial_keeps_collecting_and_previous_file(self):
        self.empty_bootstrap()
        previous = (self.root / "status.json").read_bytes()
        self.http.html = article("p1")
        temp_paths = []

        def deny(source, target):
            temp_paths.append(Path(source))
            raise PermissionError("persistent Windows file lock")

        with patch.object(live.os, "replace", side_effect=deny), patch.object(live.time, "sleep"), patch.object(live.sys, "stderr", new_callable=io.StringIO) as log:
            first = self.collector.poll()
            self.http.html += article("p2")
            second = self.collector.poll()
        self.assertEqual((first["sent"], second["sent"]), (1, 2))
        self.assertIn("persistent Windows file lock", second["status_write_error"])
        self.assertIn("collection continues", log.getvalue())
        self.assertEqual(len(temp_paths), 12)  # Six bounded attempts per report.
        self.assertNotEqual(temp_paths[0], temp_paths[6])
        self.assertEqual((self.root / "status.json").read_bytes(), previous)
        self.assertEqual(list(self.root.glob("status.json.*.tmp")), [])
        recovered = self.collector.poll()
        self.assertEqual((recovered["sent"], recovered["pending"]), (2, 0))
        self.assertIsNone(recovered["status_write_error"])

    def test_stopped_report_denial_does_not_change_session_exit_code(self):
        with patch.object(live, "Collector", return_value=self.collector), patch.object(self.collector, "close"), patch.object(self.collector, "poll", side_effect=live.SessionChanged("changed")), patch.object(live.os, "replace", side_effect=PermissionError("locked")), patch.object(live.time, "sleep"), patch.object(live.sys, "stderr", new_callable=io.StringIO):
            code = live.main(["--source", "http://source", "--engine", "http://engine", "--session-id", "demo1", "--state", "unused", "--once"])
        self.assertEqual(code, 3)

    @unittest.skipUnless(os.name == "nt", "Windows actual file sharing lock test")
    def test_actual_windows_target_lock_recovers_without_deleting_target(self):
        import ctypes
        from ctypes import wintypes
        self.empty_bootstrap()
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateFileW(str(self.root / "status.json"), 0x80000000, 0,
                                    None, 3, 0x80, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        released = threading.Event()

        def unlock():
            kernel.CloseHandle(handle)
            released.set()

        timer = threading.Timer(0.12, unlock)
        timer.start()
        try:
            result = self.collector.write_status()
            self.assertIsNone(result["status_write_error"])
            self.assertTrue((self.root / "status.json").is_file())
        finally:
            timer.join(timeout=2)
            if not released.is_set():
                unlock()

    @unittest.skipUnless(os.name == "nt", "Windows process handle test")
    def test_windows_parent_handle_observes_exit_without_os_kill(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        watcher = live.ParentWatcher(process.pid)
        try:
            with patch.object(live.os, "kill", side_effect=AssertionError("os.kill must never run on Windows")):
                self.assertTrue(watcher.alive())
                process.terminate()
                process.wait(timeout=5)
                self.assertFalse(watcher.alive())
                missing = live.ParentWatcher(process.pid)
                try:
                    self.assertFalse(missing.alive())
                finally:
                    missing.close()
        finally:
            watcher.close()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)

    @unittest.skipUnless(os.name == "nt", "Windows access error test")
    def test_windows_parent_access_error_is_explicit(self):
        with patch("ctypes.WinDLL") as library, patch("ctypes.get_last_error", return_value=5):
            library.return_value.OpenProcess.return_value = None
            with self.assertRaises(OSError):
                live.ParentWatcher(123)

    def test_request_byte_limit_rejects_oversized_post_and_sends_small_one(self):
        self.empty_bootstrap()
        self.http.html = article("big", text="한" * 1_300_000) + article("small")
        result = self.collector.poll()
        self.assertEqual((result["sent"], result["rejected"]), (1, 1))
        self.assertLess(len(self.collector.body([(None, json.dumps(self.http.posts[-1]["posts"][0]))])), 4_000_000)

    def test_real_http_commit_then_503_replay_is_exact_after_restart(self):
        state = {"html": "", "stored": {}, "fail_after_commit": True, "duplicates": 0}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, code, content, content_type="application/json"):
                encoded = content.encode()
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self):
                if self.path == "/api/session":
                    self.respond(200, '{"session":{"id":"demo1"}}')
                else:
                    self.respond(200, state["html"], "text/html; charset=utf-8")

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                for post in payload["posts"]:
                    if post["id"] in state["stored"]:
                        if state["stored"][post["id"]] != post:
                            self.respond(400, "immutable ID conflict")
                            return
                        state["duplicates"] += 1
                    state["stored"][post["id"]] = post
                if state["fail_after_commit"]:
                    state["fail_after_commit"] = False
                    self.respond(503, "analysis failed after ingest")
                else:
                    self.respond(200, "{}")

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        address = f"http://127.0.0.1:{server.server_port}"
        collector = live.Collector(address, address, "demo1", self.root / "real.sqlite3")
        try:
            collector.poll()
            state["html"] = article("real", text="원문 evidence")
            self.assertEqual(collector.poll()["pending"], 1)
            collector.close()
            collector = live.Collector(address, address, "demo1", self.root / "real.sqlite3")
            self.assertEqual(collector.poll()["sent"], 1)
            self.assertEqual((len(state["stored"]), state["duplicates"]), (1, 1))
        finally:
            collector.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
