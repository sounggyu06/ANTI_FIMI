import json
import math
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from dashboard import snapshot
from engine import Engine, LexicalDemoEmbedder, dumps, parse_time, stamp
from server import Runtime, make_handler


def post(pid, text="The joint relief exercise was cancelled.", account="a", time="2026-10-01T00:00:00Z", **extra):
    return {"id": pid, "account_id": account, "created_at": time, "text": text, **extra}


class FixtureEmbedder:
    identity = "test:angles-v1"

    def encode(self, texts):
        angles = {"A": 0, "B": 45, "C": 65, "D": 90}
        return [[math.cos(math.radians(angles.get(t, 0))), math.sin(math.radians(angles.get(t, 0)))] for t in texts]


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ANTI_FIMI_dashboard_")
        self.folder = Path(self.temp.name)
        self.db = self.folder / "test.sqlite3"
        self.as_of = parse_time("2026-10-01T08:00:00Z")

    def tearDown(self):
        self.temp.cleanup()

    def test_event_groups_refutation_but_preserves_narrative_and_id_on_late_arrival(self):
        with Engine(self.db, LexicalDemoEmbedder()) as engine:
            engine.ingest([post("claim", time="2026-10-01T01:00:00Z"),
                           post("refute", "The joint relief exercise was not cancelled.", "b", "2026-10-01T02:00:00Z")])
            engine.analyze(self.as_of)
            before = snapshot(self.db)
            self.assertEqual(len(before["cases"]), 1)
            self.assertEqual(len(before["cases"][0]["narratives"]), 2)
            engine.ingest([post("late", time="2026-10-01T00:00:00Z")])
            engine.analyze(self.as_of)
            after = snapshot(self.db)
            self.assertEqual(before["cases"][0]["id"], after["cases"][0]["id"])
            self.assertEqual(after["cases"][0]["post_count"], 3)

    def test_same_account_does_not_merge_unrelated_events_and_seed_stops_chaining(self):
        with Engine(self.db, FixtureEmbedder()) as engine:
            engine.ingest([post("a", "A"), post("b", "B"), post("c", "C")])
            engine.analyze(self.as_of)
        data = snapshot(self.db)
        self.assertEqual(sorted(c["post_count"] for c in data["cases"]), [1, 2])
        self.assertEqual(data["summary"]["account_count"], 1)

    def test_time_span_and_homepage_do_not_force_merges(self):
        with Engine(self.db, FixtureEmbedder()) as engine:
            engine.ingest([post("a", "A", urls=["https://example.invalid/"]),
                           post("d", "D", urls=["https://example.invalid/"]),
                           post("later", "A", time="2026-10-05T00:00:00Z")])
            engine.analyze(parse_time("2026-10-06T00:00:00Z"))
        self.assertEqual(snapshot(self.db)["summary"]["case_count"], 3)

    def test_explicit_reference_links_event_and_produces_observed_direction(self):
        with Engine(self.db, FixtureEmbedder()) as engine:
            engine.ingest([post("a", "A", account="origin"), post("d", "D", account="reply",
                           relations=[{"type": "replies_to", "target_post_id": "a"}])])
            engine.analyze(self.as_of)
        case = snapshot(self.db)["cases"][0]
        self.assertEqual(case["post_count"], 2)
        edge = case["network"]["edges"][0]
        self.assertEqual((edge["source"], edge["target"], edge["kind"]), ("reply", "origin", "replies_to"))

    def test_unanalyzed_late_posts_do_not_leak_into_snapshot(self):
        with Engine(self.db, LexicalDemoEmbedder()) as engine:
            engine.ingest([post("old")])
            engine.analyze(self.as_of)
            engine.ingest([post("pending", account="not-yet-analyzed")])
        data = snapshot(self.db)
        self.assertEqual(data["summary"]["post_count"], 1)
        self.assertEqual(data["summary"]["pending_post_count"], 1)
        self.assertEqual(data["summary"]["account_count"], 1)

    def test_original_arriving_after_reply_recovers_event_and_edge(self):
        with Engine(self.db, FixtureEmbedder()) as engine:
            engine.ingest([post("reply", "D", account="reply-account",
                                relations=[{"type": "quotes", "target_post_id": "original"}])])
            engine.analyze(self.as_of)
            event_id = snapshot(self.db)["cases"][0]["id"]
            engine.ingest([post("original", "A", account="origin-account")])
            engine.analyze(self.as_of)
        data = snapshot(self.db)
        self.assertEqual(data["summary"]["case_count"], 1)
        self.assertEqual(data["cases"][0]["id"], event_id)
        edge = data["cases"][0]["network"]["edges"][0]
        self.assertEqual((edge["source"], edge["target"]), ("reply-account", "origin-account"))

    def test_invalid_relations_rejected_before_batch_commit_and_restart(self):
        runtime = Runtime(self.db, LexicalDemoEmbedder(), local_preview=True)
        for invalid in (42, 0, False, "", {}, ["bad"], [{"type": "quotes", "target_post_id": []}]):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    runtime.ingest([post("good"), post("bad", relations=invalid)])
                self.assertEqual(runtime.dashboard()["summary"]["post_count"], 0)
        self.assertEqual(Runtime(self.db, LexicalDemoEmbedder(), local_preview=True).dashboard()["cases"], [])

    def test_sibling_references_share_event_before_original_arrives(self):
        with Engine(self.db, FixtureEmbedder()) as engine:
            engine.ingest([post("reply-a", "A", account="a", relations=[{"type": "quotes", "target_post_id": "origin"}]),
                           post("reply-d", "D", account="d", relations=[{"type": "replies_to", "target_post_id": "origin"}])])
            engine.analyze(self.as_of)
            self.assertEqual(snapshot(self.db)["summary"]["case_count"], 1)
            engine.ingest([post("origin", "C", account="origin")])
            engine.analyze(self.as_of)
        cases = snapshot(self.db)["cases"]
        self.assertEqual(len(cases), 1)
        self.assertEqual(len(cases[0]["network"]["edges"]), 2)

    def test_future_tolerance_does_not_advance_analysis_clock(self):
        now = [parse_time("2026-10-01T07:59:00Z")]
        runtime = Runtime(self.db, LexicalDemoEmbedder(), clock=lambda: now[0], local_preview=True)
        runtime.ingest([post("future", time="2026-10-01T08:02:00Z")])
        data = runtime.dashboard()
        self.assertEqual(data["analysis_as_of"], stamp(now[0]))
        self.assertEqual(data["summary"]["post_count"], 0)
        self.assertEqual(data["summary"]["pending_post_count"], 1)
        now[0] = parse_time("2026-10-01T08:00:00Z")
        runtime.advance_live_clock()
        self.assertEqual(runtime.dashboard()["summary"]["pending_post_count"], 1)
        now[0] = parse_time("2026-10-01T08:02:00Z")
        runtime.advance_live_clock()
        self.assertEqual(runtime.dashboard()["summary"]["post_count"], 1)

    def test_case_alert_ids_are_distinct_for_same_pair_and_hour(self):
        rows = [post(f"{text}-{episode}-{actor}", text, actor,
                     f"2026-10-01T00:{start + episode * 10:02d}:00Z", urls=[f"https://example.invalid/{text}"])
                for text, start in (("A", 0), ("D", 30)) for episode in range(3) for actor in ("a", "b")]
        with Engine(self.db, FixtureEmbedder()) as engine:
            engine.ingest(rows)
            engine.analyze(self.as_of)
        cases = snapshot(self.db)["cases"]
        self.assertEqual(len(cases), 2)
        self.assertEqual([c["alert_count"] for c in cases], [1, 1])
        self.assertNotEqual(cases[0]["alerts"][0]["id"], cases[1]["alerts"][0]["id"])
        for case in cases:
            self.assertEqual(case["network"]["edges"][0]["alert_ids"], [case["alerts"][0]["id"]])

    def test_live_clock_finalizes_hour_without_new_posts_but_replay_does_not(self):
        current = [parse_time("2026-10-01T06:30:00Z")]
        runtime = Runtime(self.db, LexicalDemoEmbedder(), clock=lambda: current[0], local_preview=True)
        rows = [post("origin")] + [post(f"b{i}", account=f"actor{i}", time=f"2026-10-01T06:00:{i:02d}Z") for i in range(8)]
        runtime.ingest(rows)
        self.assertEqual(runtime.dashboard()["summary"]["alert_count"], 0)
        current[0] = parse_time("2026-10-01T07:00:00Z")
        runtime.advance_live_clock()
        self.assertEqual(runtime.dashboard()["summary"]["alert_count"], 1)
        replay = Runtime(self.folder / "replay.db", LexicalDemoEmbedder(), clock=lambda: current[0], local_preview=True)
        replay.ingest(rows, "2026-10-01T06:30:00Z")
        replay.advance_live_clock()
        self.assertEqual(replay.dashboard()["analysis_as_of"], stamp(parse_time("2026-10-01T06:30:00Z")))
        restored = Runtime(self.folder / "replay.db", LexicalDemoEmbedder(), clock=lambda: current[0], local_preview=True)
        restored.advance_live_clock()
        self.assertEqual(restored.dashboard()["summary"]["alert_count"], 0)

    def test_global_coordination_is_not_reported_as_local_case_episodes(self):
        rows = []
        for episode in range(3):
            for actor in ("a", "b"):
                rows.append(post(f"{episode}-{actor}", "A" if episode < 2 else "D", actor,
                                 f"2026-10-01T00:{episode * 10:02d}:00Z", urls=["https://example.invalid/"]))
        with Engine(self.db, FixtureEmbedder()) as engine:
            engine.ingest(rows)
            self.assertEqual(len(engine.analyze(self.as_of)), 1)
        data = snapshot(self.db)
        self.assertEqual(data["summary"]["case_count"], 2)
        self.assertEqual(data["summary"]["alert_count"], 0)

    def test_empty_snapshot_and_invalid_source_clock_do_not_insert(self):
        runtime = Runtime(self.db, LexicalDemoEmbedder(), local_preview=True)
        self.assertEqual(runtime.dashboard()["cases"], [])
        with self.assertRaises(ValueError):
            runtime.ingest([post("invalid-clock")], "not-a-clock")
        self.assertEqual(runtime.dashboard()["summary"]["post_count"], 0)

    def test_watch_partial_bad_line_repair_restart_and_file_replacement(self):
        feed = self.folder / "feed.jsonl"
        runtime = Runtime(self.db, LexicalDemoEmbedder(), feed, local_preview=True)
        first = dumps(post("first")).encode("utf-8-sig")
        feed.write_bytes(first)
        runtime.poll_file()
        self.assertEqual(runtime.dashboard()["summary"]["post_count"], 0)
        feed.write_bytes(first + b"\n{bad\n")
        runtime.poll_file()
        self.assertEqual(runtime.dashboard()["summary"]["post_count"], 1)
        self.assertEqual(runtime.feed["status"], "error")
        feed.write_bytes(first + b"\n" + dumps(post("second")).encode() + b"\n")
        runtime.poll_file()
        self.assertEqual(runtime.dashboard()["summary"]["post_count"], 2)
        restarted = Runtime(self.db, LexicalDemoEmbedder(), feed, local_preview=True)
        restarted.poll_file()
        self.assertEqual(restarted.dashboard()["summary"]["post_count"], 2)
        feed.write_text(dumps(post("third")) + "\n", encoding="utf-8")
        restarted.poll_file()
        self.assertEqual(restarted.dashboard()["summary"]["post_count"], 3)
        self.assertEqual(restarted.feed["status"], "watching")

    def test_watch_conflicting_batch_does_not_advance_cursor(self):
        feed = self.folder / "feed.jsonl"
        runtime = Runtime(self.db, LexicalDemoEmbedder(), feed, local_preview=True)
        runtime.ingest([post("old")])
        feed.write_text(dumps(post("new")) + "\n" + dumps(post("old", "changed")) + "\n", encoding="utf-8")
        runtime.poll_file()
        self.assertEqual(runtime.feed["status"], "error")
        self.assertEqual(runtime.dashboard()["summary"]["post_count"], 1)
        feed.write_text(dumps(post("new")) + "\n" + dumps(post("old")) + "\n", encoding="utf-8")
        runtime.poll_file()
        self.assertEqual(runtime.dashboard()["summary"]["post_count"], 2)

    def test_real_http_ingest_snapshot_and_static_hosting(self):
        runtime = Runtime(self.db, LexicalDemoEmbedder(), local_preview=True)
        static = self.folder / "web"
        static.mkdir()
        (static / "index.html").write_text("<title>ANTI_FIMI</title>", encoding="utf-8")
        http = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(runtime, static))
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{http.server_port}"
        try:
            before = json.load(urlopen(base + "/api/dashboard"))
            body = dumps({"posts": [post("unicode", "훈련 취소 근거를 확인 중입니다.")],
                          "source_now": "2026-10-01T08:00:00Z"}).encode("utf-8")
            result = json.load(urlopen(Request(base + "/api/posts", body, {"Content-Type": "application/json"})))
            self.assertEqual(result["inserted"], 1)
            after = json.load(urlopen(base + "/api/dashboard"))
            self.assertNotEqual(before["snapshot_id"], after["snapshot_id"])
            self.assertEqual(after["summary"]["post_count"], 1)
            self.assertEqual(after["analysis_as_of"], stamp(self.as_of))
            self.assertIn(b"ANTI_FIMI", urlopen(base + "/").read())
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base + "/api/posts", b"bad", {"Content-Type": "text/plain"}))
            self.assertEqual(error.exception.code, 415)
        finally:
            http.shutdown()
            http.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
