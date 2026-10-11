import json
from pathlib import Path
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import unittest
from datetime import timedelta

from engine import (Config, Engine, LexicalDemoEmbedder, canonical_url, dumps,
                    fetch_http, parse_time, stamp, stance_hint)
from make_demo import AS_OF, BASE, CLAIM, demo_posts


def post(pid, account="a", seconds=0, text=CLAIM, urls=None):
    return {"id": pid, "account_id": account, "created_at": stamp(BASE + timedelta(seconds=seconds)),
            "text": text, "urls": urls or []}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ANTI_FIMI_")
        self.db = Path(self.tmp.name, "test.sqlite3")
        self.embedder = LexicalDemoEmbedder()
        self.engine = Engine(self.db, self.embedder, clock=lambda: AS_OF)

    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()

    def test_demo_alerts_have_real_evidence_and_both_signals(self):
        posts = demo_posts()
        self.engine.ingest(posts)
        alerts = self.engine.analyze(AS_OF)
        reasons = {r for a in alerts for r in a["reason_codes"]}
        self.assertTrue({"REPEATED_URL_COSHARE", "HOURLY_DIFFUSION_SPIKE"} <= reasons)
        known = {p["id"] for p in posts}
        for alert in alerts:
            self.assertTrue(set(alert["evidence_post_ids"]) <= known)
            self.assertTrue(alert["evidence_post_ids"])
        spike = next(a for a in alerts if a["kind"] == "hourly_diffusion_spike")
        self.assertEqual(spike["baseline_counts"], [2] * 6)
        self.assertEqual(spike["post_count"], 24)

    def test_restart_replay_keeps_ids_assignments_alerts_and_no_duplicate_rows(self):
        posts = demo_posts()
        self.engine.ingest(posts)
        before = self.engine.analyze(AS_OF)
        assignments = [tuple(row) for row in self.engine.conn.execute("SELECT * FROM assignments ORDER BY post_id")]
        self.engine.close()
        self.engine = Engine(self.db, self.embedder, clock=lambda: AS_OF)
        self.assertEqual(self.engine.ingest(posts), {"inserted": 0, "duplicates": len(posts)})
        self.assertEqual(before, self.engine.analyze(AS_OF))
        self.assertEqual(assignments, [tuple(row) for row in self.engine.conn.execute("SELECT * FROM assignments ORDER BY post_id")])
        count = self.engine.conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        self.assertEqual(count, len(before))

    def test_collection_clock_backwards_and_late_event_survive_restart(self):
        self.engine.ingest([post("newer", seconds=3600)])
        self.engine.close()
        self.engine = Engine(self.db, self.embedder, clock=lambda: AS_OF - timedelta(hours=1))
        self.engine.ingest([post("late", seconds=1)])
        rows = list(self.engine.conn.execute("SELECT * FROM posts ORDER BY seq"))
        self.assertGreater(rows[1]["collected_at"], rows[0]["collected_at"])
        self.assertLess(rows[1]["observed_clock_at"], rows[0]["observed_clock_at"])
        self.assertLess(rows[1]["created_at"], rows[0]["created_at"])
        self.engine.analyze(AS_OF)
        self.assertEqual(self.engine.conn.execute("SELECT SUM(post_count) FROM hourly").fetchone()[0], 2)

    def test_claim_refutation_and_question_are_not_mixed_even_with_identical_vectors(self):
        class SameVector:
            identity = LexicalDemoEmbedder.identity
            def encode(self, texts):
                return [[1.0, 0.0] for _ in texts]
        self.engine.embedder = SameVector()
        self.engine.ingest([
            post("assert"), post("refute", text="The joint exercise was not cancelled."),
            post("question", text="If the exercise was cancelled, what happens?"),
            post("refute-ko", text="공동훈련은 취소되지 않았습니다."),
        ])
        self.engine.analyze(AS_OF)
        rows = dict(self.engine.conn.execute("SELECT post_id,cluster_id FROM assignments"))
        self.assertEqual(len({rows["assert"], rows["refute"], rows["question"]}), 3)
        self.assertEqual(rows["refute"], rows["refute-ko"])

    def test_ambiguous_user_samples_and_negated_refutation(self):
        for text in ("공동훈련 취소설이 너무 빨라서 소문이 먼저 출동했네요.",
                     "훈련 취소 주장의 출처는 이 링크뿐인가요?", "This is not false.",
                     "재난구호훈련이 취소됐다는 글을 봤습니다."):
            self.assertEqual(stance_hint(text)[0], "uncertain")

    def test_single_account_or_one_dense_episode_does_not_trigger_coordination(self):
        url = ["https://example.invalid/x"]
        self.engine.ingest([post(f"p{i}", str(i % 2), i, urls=url) for i in range(40)])
        self.assertFalse(self.engine.analyze(AS_OF))

    def test_one_account_many_separated_shares_is_not_cross_account(self):
        self.engine.ingest([post(f"p{i}", "same", i * 600, urls=["https://example.invalid/x"]) for i in range(5)])
        self.assertFalse(self.engine.analyze(AS_OF))

    def test_continuous_ten_minute_burst_is_one_episode(self):
        self.engine.ingest([post(f"continuous-{minute}-{a}", a, minute * 60 + int(a),
                                 urls=["https://example.invalid/x"])
                            for minute in range(11) for a in ("0", "1")])
        self.assertFalse(self.engine.analyze(AS_OF))

    def test_same_url_repeated_independent_episodes_trigger(self):
        self.engine.ingest([post(f"p{i}-{a}", a, i * 600 + int(a),
                                 urls=["https://example.invalid/x"]) for i in range(3) for a in ("0", "1")])
        alerts = self.engine.analyze(AS_OF)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["episode_count"], 3)
        self.assertEqual(len(alerts[0]["evidence_post_ids"]), 6)

    def test_three_different_urls_once_each_are_not_same_url_recurrence(self):
        self.engine.ingest([post(f"p{i}-{a}", a, i * 600 + int(a),
                                 urls=[f"https://example.invalid/article?id={i}"])
                            for i in range(3) for a in ("0", "1")])
        self.assertFalse(self.engine.analyze(AS_OF))

    def test_unrelated_new_url_does_not_reissue_previous_url_alert(self):
        rows = [post(f"a{i}-{a}", a, i * 600 + int(a), urls=["https://example.invalid/a"])
                for i in range(3) for a in ("0", "1")]
        rows += [post(f"b-{a}", a, 7200 + int(a), urls=["https://example.invalid/b"]) for a in ("0", "1")]
        self.engine.ingest(rows)
        alerts = self.engine.analyze(AS_OF)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["window_end"], stamp(BASE + timedelta(seconds=1201)))

    def test_late_arrival_recomputes_baseline_and_retracts_stale_alert(self):
        initial = [post("origin")]
        initial += [post(f"burst{i}", f"a{i}", 6 * 3600 + i) for i in range(8)]
        self.engine.ingest(initial)
        self.assertEqual(len(self.engine.analyze(AS_OF)), 1)
        late = [post(f"late-{h}-{i}", f"a{i}", h * 3600 + 50 + i)
                for h in range(6) for i in range(8)]
        self.engine.ingest(late)
        self.assertFalse(self.engine.analyze(AS_OF))
        self.assertEqual(self.engine.conn.execute("SELECT active FROM alerts").fetchone()[0], 0)

    def test_zero_filled_baseline_and_incomplete_hour_excluded(self):
        self.engine.ingest([post("origin")] + [post(f"b{i}", f"a{i}", 6 * 3600 + i) for i in range(8)])
        self.assertFalse(self.engine.analyze(BASE + timedelta(hours=6, minutes=30)))
        alerts = self.engine.analyze(AS_OF)
        self.assertEqual(alerts[0]["baseline_counts"], [1, 0, 0, 0, 0, 0])

    def test_atomic_ingest_conflict_and_bad_timestamp(self):
        self.engine.ingest([post("existing")])
        with self.assertRaises(ValueError):
            self.engine.ingest([post("new"), post("existing", text="changed")])
        self.assertEqual(self.engine.conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 1)
        with self.assertRaises(ValueError):
            parse_time("2026-10-01T00:00:00")
        with self.assertRaises(ValueError):
            self.engine.ingest([{**post("future"), "created_at": stamp(AS_OF + timedelta(hours=1))}])

    def test_model_config_mismatch_fails(self):
        with self.assertRaisesRegex(ValueError, "mismatch"):
            Engine(self.db, self.embedder, Config(similarity=0.9))

    def test_url_normalization_preserves_article_query_and_deduplicates_post_urls(self):
        a = canonical_url("https://EXAMPLE.invalid:443/a?id=1&utm_source=x#top")
        self.assertEqual(a, "https://example.invalid/a?id=1")
        self.assertNotEqual(a, canonical_url("https://example.invalid/a?id=2"))
        self.assertIsNone(canonical_url("javascript:alert(1)"))
        self.engine.ingest([post("p", text=CLAIM + " " + a, urls=[a, a])])
        self.assertEqual(self.engine.conn.execute("SELECT COUNT(*) FROM post_urls").fetchone()[0], 1)

    def test_export_network_and_briefing_reference_existing_evidence(self):
        self.engine.ingest(demo_posts())
        self.engine.analyze(AS_OF)
        output = Path(self.tmp.name, "results")
        self.engine.export(output)
        graph = json.loads((output / "network.json").read_text(encoding="utf-8"))
        self.assertTrue(graph["edges"])
        self.assertIn("최초 유포", (output / "briefing.md").read_text(encoding="utf-8"))
        html = (output / "network.html").read_text(encoding="utf-8")
        self.assertNotIn("__ANTI_FIMI_DATA__", html)
        self.assertIn('"evidence_post_ids"', html)
        narratives = json.loads((output / "narratives.json").read_text(encoding="utf-8"))
        for narrative in narratives:
            self.assertIn(narrative["earliest_observed_post_id"], narrative["post_ids"])

    def test_export_does_not_execute_post_html(self):
        self.engine.ingest([post("html", text="</script><script>alert(1)</script>")])
        self.engine.analyze(AS_OF)
        output = Path(self.tmp.name, "html")
        self.engine.export(output)
        html = (output / "network.html").read_text(encoding="utf-8")
        self.assertNotIn("</script><script>alert(1)", html)
        self.assertIn("\\u003c/script>", html)

    def test_http_mapping_preserves_raw_payload(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                payload = {"data": [{"post_id": "h1", "author": {"id": "u1"},
                                      "body": CLAIM, "time": stamp(BASE)}]}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(dumps(payload).encode())
            def log_message(self, *_):
                pass
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            mapping = {"id": "post_id", "account_id": "author.id", "created_at": "time", "text": "body"}
            rows = list(fetch_http(f"http://127.0.0.1:{server.server_port}", mapping, "data"))
            self.engine.ingest(rows)
            raw = json.loads(self.engine.conn.execute("SELECT raw_json FROM posts").fetchone()[0])
            self.assertEqual(raw["_source_raw"]["post_id"], "h1")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
