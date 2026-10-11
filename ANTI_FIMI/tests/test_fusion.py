from contextlib import closing
import copy
from datetime import timedelta
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from engine import Config, dumps, parse_time, stamp
from fusion import _aggregate_alerts, ai_diffusion_alerts, cluster_diffusion_alerts
from server import Runtime, RawOnlyEmbedder, make_handler

BASE = parse_time("2026-10-01T00:00:00Z")


def rows(accounts=("a", "b"), rounds=3):
    return [{"id": f"{r}-{a}", "account_id": a, "created_at": stamp(BASE + timedelta(minutes=r * 10, seconds=i)),
             "text": f"Observed report {r} is disputed.", "urls": [f"https://example.invalid/{r}"]}
            for r in range(rounds) for i, a in enumerate(accounts)]


class FusionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.db = self.folder / "state.db"
        self.now = BASE + timedelta(hours=1)
        self.runtime = Runtime(self.db, RawOnlyEmbedder(self.db), clock=lambda: self.now)

    def tearDown(self):
        self.temp.cleanup()

    def ingest(self, posts=None):
        return self.runtime.ingest(posts or rows(), stamp(self.now))

    def result(self, index=0, stance="CON", revision=1):
        item = self.runtime.ai_pending()["items"][index]
        return {"post_id": item["post_id"], "raw_sha256": item["raw_sha256"], "model_version": "fixture-v1",
                "scope_id": "fixture-run", "revision": revision, "claims": [{"cluster_id": "topic1", "claim_id": "c1",
                "claim_text": "The observed report is accurate.", "stance": stance, "confidence": 0.8,
                "evidence_text": item["raw"]["text"]}]}

    def cluster_result(self, index=0, cid="topic1", revision=1):
        item = self.runtime.ai_pending()["items"][index]
        return {"post_id": item["post_id"], "raw_sha256": item["raw_sha256"], "model_version": "cluster-fixture",
                "scope_id": "run1", "revision": revision, "cluster_id": cid}

    def test_clustering_only_accepts_no_stance_claim_or_confidence(self):
        self.ingest()
        score = self.runtime.dashboard()["investigations"][0]["network_score"]
        self.runtime.receive_ai([self.cluster_result(0), self.cluster_result(1)])
        data = self.runtime.dashboard()
        self.assertEqual(len(data["cases"]), 1)
        case = data["cases"][0]
        self.assertEqual(case["narratives"][0]["kind"], "cluster")
        self.assertIsNone(case["narratives"][0]["stance_hint"])
        self.assertTrue(all(not p["ai_claims"] and len(p["ai_clusters"]) == 1 for p in case["posts"]))
        parent = data["investigations"][0]
        self.assertEqual(parent["network_score"], score)
        self.assertEqual(parent["ai_context"]["claims"], [])
        self.assertEqual(parent["ai_context"]["stance_counts"], {})
        self.assertEqual(len(parent["ai_context"]["clusters"]), 1)
        self.assertEqual(parent["ai_context"]["analyzed_post_count"], 2)
        self.assertEqual(parent["related_case_ids"], [case["id"]])

    def test_unassigned_is_received_not_pending_and_preserves_raw(self):
        self.ingest()
        result = self.cluster_result(cid=None)
        self.runtime.receive_ai([result])
        data = self.runtime.dashboard()
        self.assertEqual(data["cases"], [])
        self.assertEqual(data["pipeline"]["ai_received_count"], 1)
        self.assertEqual(len(data["unlinked_posts"]), 6)
        item = next(p for p in data["unlinked_posts"] if p["id"] == result["post_id"])
        self.assertEqual(item["ai_status"], "received")
        self.assertEqual(item["ai_clusters"], [])
        self.assertEqual(data["investigations"][0]["ai_context"]["unassigned_post_count"], 1)
        self.assertNotIn(result["post_id"], {p["post_id"] for p in self.runtime.ai_pending()["items"]})

    def test_cluster_revision_reassigns_and_restart_deduplicates(self):
        self.ingest()
        result = self.cluster_result()
        self.runtime.receive_ai([result])
        old_id = self.runtime.dashboard()["cases"][0]["id"]
        revised = {**result, "revision": 2, "cluster_id": "other"}
        self.runtime.receive_ai([revised])
        self.assertNotEqual(self.runtime.dashboard()["cases"][0]["id"], old_id)
        self.assertEqual(self.runtime.receive_ai([revised])["duplicates"], 1)
        with self.assertRaises(ValueError):
            self.runtime.receive_ai([result])
        restarted = Runtime(self.db, RawOnlyEmbedder(self.db), clock=lambda: self.now)
        self.assertEqual(restarted.dashboard()["pipeline"]["ai_received_count"], 1)
        restarted.receive_ai([{**revised, "revision": 3, "cluster_id": None}])
        self.assertEqual(restarted.dashboard()["cases"], [])

    def test_cluster_invalid_membership_and_ambiguous_payload_are_atomic(self):
        self.ingest()
        for changes in ({"cluster_id": ""}, {"cluster_id": 12}, {"cluster_id": []},
                        {"membership_strength": float("nan")}, {"membership_strength": True},
                        {"cluster_label": 123}, {"claims": []}):
            first, bad = self.cluster_result(0), self.cluster_result(1)
            bad.update(changes)
            with self.assertRaises(ValueError):
                self.runtime.receive_ai([first, bad])
            self.assertEqual(self.runtime.dashboard()["pipeline"]["ai_received_count"], 0)

    def test_cluster_ids_are_scoped_and_legacy_claim_payload_still_reads(self):
        self.ingest()
        first, second = self.cluster_result(0), self.cluster_result(1)
        second["scope_id"] = "different"
        self.runtime.receive_ai([first, second, self.result(2)])
        data = self.runtime.dashboard()
        self.assertEqual(len(data["cases"]), 3)
        self.assertEqual(len({c["id"] for c in data["cases"]}), 3)
        self.assertEqual(data["pipeline"]["ai_received_count"], 3)
        self.assertEqual(sum(bool(p["ai_claims"]) for c in data["cases"] for p in c["posts"]), 1)

    def test_cluster_volume_is_labeled_unanalysed_stance(self):
        posts = [{"id": "seed", "account_id": "origin", "created_at": stamp(BASE)}] + [
            {"id": str(i), "account_id": f"actor-{i}", "created_at": stamp(BASE + timedelta(hours=6, seconds=i))} for i in range(8)]
        groups = {p["id"]: [{"cluster_id": "topic"}] for p in posts}
        ai = {p["id"]: [] for p in posts}
        self.assertEqual(cluster_diffusion_alerts(posts, groups, ai, BASE + timedelta(hours=6, minutes=30), Config()), [])
        alerts = cluster_diffusion_alerts(posts, groups, ai, BASE + timedelta(hours=7), Config())
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["cluster_ids"], ["topic"])
        self.assertIn("미분석", alerts[0]["summary"])
        self.assertNotIn("stance", alerts[0])
        self.assertNotIn("claim_id", alerts[0])

    def test_external_ai_volume_uses_claim_stance_and_completed_hours(self):
        posts = [{"id": "seed", "account_id": "origin", "created_at": stamp(BASE)}] + [
            {"id": str(i), "account_id": f"actor-{i}", "created_at": stamp(BASE + timedelta(hours=6, seconds=i))} for i in range(8)]
        ai = {p["id"]: [{"cluster_id": "topic", "claim_id": "c", "stance": "PRO"}] for p in posts}
        self.assertEqual(ai_diffusion_alerts(posts, ai, BASE + timedelta(hours=6, minutes=30), Config()), [])
        alerts = ai_diffusion_alerts(posts, ai, BASE + timedelta(hours=7), Config())
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["post_count"], 8)
        for i in range(4):
            ai[str(i)][0]["stance"] = "CON"
        self.assertEqual(ai_diffusion_alerts(posts, ai, BASE + timedelta(hours=7), Config()), [])

    def test_raw_path_does_not_call_model_and_keeps_all_unlinked_posts(self):
        result = self.ingest()
        data = self.runtime.dashboard()
        self.assertEqual(result["inserted"], 6)
        self.assertEqual(data["pipeline"]["ai_pending_count"], 6)
        self.assertEqual(data["pipeline"]["behavior_post_count"], 6)
        self.assertEqual(len(data["unlinked_posts"]), 6)
        self.assertEqual(data["cases"], [])
        self.assertEqual(len(data["investigations"]), 1)
        self.assertEqual(data["investigations"][0]["fusion_status"], "pending")
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts WHERE embedding_json='[]' AND stance='pending'").fetchone()[0], 6)

    def test_ai_late_arrival_does_not_gate_refutation_behavior_signal(self):
        self.ingest()
        before = self.runtime.dashboard()["investigations"][0]
        self.runtime.receive_ai([self.result(stance="CON")])
        data = self.runtime.dashboard()
        after = data["investigations"][0]
        self.assertEqual(before["id"], after["id"])
        self.assertEqual(before["network_score"], after["network_score"])
        self.assertEqual(after["fusion_status"], "partial")
        self.assertEqual(after["alerts"][0]["ai_context"]["stance_counts"], {"CON": 1})
        self.assertEqual(len(data["cases"]), 1)
        self.assertEqual(data["analysis_as_of"], stamp(self.now))

    def test_same_claim_support_and_refutation_stay_separate(self):
        self.ingest()
        self.runtime.receive_ai([self.result(0, "PRO"), self.result(1, "CON")])
        data = self.runtime.dashboard()
        self.assertEqual(len(data["cases"]), 1)
        self.assertEqual({n["stance_hint"] for n in data["cases"][0]["narratives"]}, {"PRO", "CON"})
        self.assertEqual(data["pipeline"]["ai_received_count"], 2)

    def test_atomic_validation_raw_hash_quote_stance_and_confidence(self):
        self.ingest()
        for mutation in (lambda x: x.update(raw_sha256="bad"),
                         lambda x: x["claims"][0].update(evidence_text="fabricated quote"),
                         lambda x: x["claims"][0].update(stance="claim"),
                         lambda x: x["claims"][0].update(confidence=float("nan")),
                         lambda x: x.update(revision=True)):
            first, invalid = self.result(0), self.result(1)
            mutation(invalid)
            with self.assertRaises(ValueError):
                self.runtime.receive_ai([first, invalid])
            self.assertEqual(self.runtime.dashboard()["pipeline"]["ai_received_count"], 0)

    def test_duplicate_stale_conflict_and_replacement_revision(self):
        self.ingest()
        result = self.result()
        self.assertEqual(self.runtime.receive_ai([result])["inserted"], 1)
        self.assertEqual(self.runtime.receive_ai([result])["duplicates"], 1)
        conflict = copy.deepcopy(result)
        conflict["claims"][0]["stance"] = "PRO"
        with self.assertRaises(ValueError):
            self.runtime.receive_ai([conflict])
        replacement = {**result, "revision": 2, "claims": []}
        self.assertEqual(self.runtime.receive_ai([replacement])["updated"], 1)
        self.assertEqual(self.runtime.dashboard()["cases"], [])
        with self.assertRaises(ValueError):
            self.runtime.receive_ai([result])
        self.assertEqual(self.runtime.dashboard()["pipeline"]["ai_received_count"], 1)
        with closing(sqlite3.connect(self.db)) as conn:
            history = conn.execute("SELECT payload_json FROM investigation_history ORDER BY evaluated_at").fetchall()
            self.assertTrue(any(json.loads(h[0])["ai_context"]["claims"] for h in history))
            self.assertEqual(json.loads(history[-1][0])["ai_context"]["claims"], [])

    def test_conflicting_claim_definition_is_rejected_and_quotes_remain_per_post(self):
        self.ingest()
        first, second = self.result(0), self.result(2)
        self.runtime.receive_ai([first, second])
        claim = self.runtime.dashboard()["investigations"][0]["alerts"][0]["ai_context"]["claims"][0]
        self.assertEqual(len(claim["evidence"]), 2)
        self.assertEqual({e["post_id"] for e in claim["evidence"]}, {first["post_id"], second["post_id"]})
        invalid = self.result(0)
        invalid["claims"][0]["claim_text"] = "A different proposition."
        with self.assertRaises(ValueError):
            self.runtime.receive_ai([invalid])

    def test_multi_claim_post_is_not_duplicated_and_scopes_do_not_collide(self):
        self.ingest()
        result = self.result()
        result["claims"].append({**result["claims"][0], "claim_id": "other", "cluster_id": "topic2"})
        second = self.result(1)
        second["scope_id"] = "different-run"
        self.runtime.receive_ai([result, second])
        data = self.runtime.dashboard()
        self.assertEqual(len(data["cases"]), 3)
        self.assertTrue(all(len(c["narratives"]) == 1 and all(len(p["ai_claims"]) == 1 for p in c["posts"]) for c in data["cases"]))
        self.assertEqual(data["pipeline"]["raw_post_count"], 6)
        self.assertEqual(data["pipeline"]["ai_received_count"], 2)
        self.assertEqual(len(data["unlinked_posts"]), 4)

    def test_clique_aggregation_combines_pairs_but_hub_does_not_chain(self):
        self.ingest(rows(("a", "b", "c")))
        data = self.runtime.dashboard()
        self.assertEqual(data["global_signals_count"], 3)
        self.assertEqual(len(data["investigations"]), 1)
        signals = data["investigations"][0]["alerts"]
        missing_bc = [s for s in signals if set(s["account_ids"]) != {"b", "c"}]
        self.assertEqual(len(_aggregate_alerts(missing_bc)), 2)
        delayed = copy.deepcopy(signals)
        delayed[0]["last_seen"] = stamp(self.now + timedelta(hours=2))
        self.assertGreater(len(_aggregate_alerts(delayed)), 1)

    def test_parent_id_survives_new_hour_and_restart_replay(self):
        self.ingest()
        before = self.runtime.dashboard()["investigations"][0]["id"]
        self.now += timedelta(hours=1)
        later = [{**p, "id": "later-" + p["id"], "created_at": stamp(parse_time(p["created_at"]) + timedelta(hours=1))} for p in rows()]
        self.runtime.ingest(later, stamp(self.now))
        self.assertEqual(self.runtime.dashboard()["investigations"][0]["id"], before)
        restarted = Runtime(self.db, RawOnlyEmbedder(self.db), clock=lambda: self.now)
        self.assertEqual(restarted.ingest(later, stamp(self.now))["duplicates"], 6)
        self.assertEqual(restarted.dashboard()["investigations"][0]["id"], before)

    def test_expiry_retires_signals_without_deleting_audit(self):
        self.ingest()
        self.now += timedelta(hours=25)
        self.runtime.ingest([{"id": "late", "account_id": "ordinary", "created_at": stamp(self.now), "text": "hello"}], stamp(self.now))
        self.assertEqual(self.runtime.dashboard()["investigations"], [])
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT active FROM investigations").fetchone()[0], 0)
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM investigation_history").fetchone()[0], 0)

    def test_future_posts_mature_without_embeddings_and_replay_does_not_advance(self):
        future = {"id": "future", "account_id": "a", "created_at": stamp(self.now + timedelta(minutes=2)), "text": "hello"}
        self.runtime.ingest([future])
        self.assertEqual(self.runtime.dashboard()["pipeline"]["behavior_pending_count"], 1)
        self.now += timedelta(minutes=2)
        self.runtime.advance_live_clock()
        self.assertEqual(self.runtime.dashboard()["pipeline"]["behavior_pending_count"], 0)
        old = self.runtime.dashboard()["analysis_as_of"]
        self.runtime.ingest([future], old)
        self.now += timedelta(hours=1)
        self.runtime.advance_live_clock()
        self.assertEqual(self.runtime.dashboard()["analysis_as_of"], old)

    def test_dashboard_holds_lock_through_snapshot_to_prevent_half_fusion_read(self):
        self.ingest()
        from dashboard import snapshot as real_snapshot
        attempts = []
        def capture(db, feed, observed_now=None):
            self.assertEqual(observed_now, self.now)
            def writer_probe():
                acquired = self.runtime.lock.acquire(blocking=False)
                attempts.append(acquired)
                if acquired:
                    self.runtime.lock.release()
            thread = threading.Thread(target=writer_probe)
            thread.start()
            thread.join(timeout=2)
            return real_snapshot(db, feed, observed_now=observed_now)
        with patch("server.snapshot", capture):
            self.runtime.dashboard()
        self.assertEqual(attempts, [False])

    def test_ai_queue_pagination_and_real_http_rejects_invalid_body(self):
        self.ingest()
        first = self.runtime.ai_pending(2)
        second = self.runtime.ai_pending(2, first["next_after_seq"])
        self.assertFalse(set(p["post_id"] for p in first["items"]) & set(p["post_id"] for p in second["items"]))
        http = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.runtime, self.folder))
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{http.server_port}"
        try:
            self.assertEqual(len(json.load(urlopen(base + "/api/ai/pending?limit=2"))["items"]), 2)
            body = dumps({"results": [self.result()]}).encode("utf-8")
            response = json.load(urlopen(Request(base + "/api/ai/results", body, {"Content-Type": "application/json"})))
            self.assertEqual(response["inserted"], 1)
            with self.assertRaises(HTTPError) as err:
                urlopen(Request(base + "/api/ai/results", dumps(rows()).encode(), {"Content-Type": "application/json"}))
            self.assertEqual(err.exception.code, 400)
            self.assertEqual(self.runtime.dashboard()["pipeline"]["raw_post_count"], 6)
        finally:
            http.shutdown()
            http.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
