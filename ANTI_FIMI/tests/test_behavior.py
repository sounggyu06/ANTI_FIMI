from datetime import timedelta
import json
import random
import sqlite3
import unittest

from behavior import analyze_behavior
from engine import parse_time, stamp


BASE = parse_time("2026-10-01T00:00:00Z")


def post(pid, account, seconds, relations=None, **extra):
    return {"id": pid, "account_id": account, "created_at": stamp(BASE + timedelta(seconds=seconds)),
            "raw_json": json.dumps({"relations": relations or [], **extra})}


def repeated(shares=3, lag=2, same_url=False):
    posts, urls = [], []
    for episode in range(shares):
        resource = f"https://example.invalid/{0 if same_url else episode}"
        for account, offset in (("a", 0), ("b", lag)):
            pid = f"{episode}-{account}"
            posts.append(post(pid, account, episode * 600 + offset))
            urls.append({"post_id": pid, "url": resource})
    return posts, urls


class BehaviorTests(unittest.TestCase):
    def analyze(self, posts, urls=(), seconds=3600):
        return analyze_behavior(posts, urls, BASE + timedelta(seconds=seconds))

    def test_different_resources_repeated_by_same_pair_create_one_review_signal(self):
        posts, urls = repeated()
        data = self.analyze(posts, urls)
        self.assertEqual(len(data["signals"]), 1)
        signal = data["signals"][0]
        self.assertEqual(signal["account_ids"], ["a", "b"])
        self.assertEqual(signal["metrics"]["independent_episodes"], 3)
        self.assertEqual(signal["metrics"]["distinct_resources"], 3)
        self.assertEqual(signal["evidence_post_ids"], sorted(p["id"] for p in posts))
        self.assertEqual(signal["fusion_status"], "pending")
        self.assertEqual(signal["cluster_ids"], [])
        self.assertGreater(signal["network_score"], 0)
        self.assertLessEqual(signal["network_score"], 100)

    def test_one_breaking_news_crowd_and_multiple_simultaneous_urls_are_one_episode(self):
        posts = [post(str(i), str(i), i % 3) for i in range(30)]
        urls = [{"post_id": p["id"], "url": f"https://news.invalid/{resource}"}
                for p in posts for resource in range(4)]
        self.assertEqual(self.analyze(posts, urls)["signals"], [])

    def test_single_account_unrelated_timing_and_single_resource_do_not_create_new_signal(self):
        posts, urls = repeated(same_url=True)
        self.assertEqual(self.analyze(posts, urls)["signals"], [])
        self.assertEqual(self.analyze([post(str(i), "a", i * 600) for i in range(5)])["signals"], [])
        posts, urls = repeated()
        unrelated = [{**row, "url": row["url"] + row["post_id"]} for row in urls]
        self.assertEqual(self.analyze(posts, unrelated)["signals"], [])

    def test_continuous_sharing_is_not_repeated_independent_episodes(self):
        posts, urls = [], []
        for i in range(30):
            for account, offset in (("a", 0), ("b", 2)):
                pid = f"{i}-{account}"
                posts.append(post(pid, account, i * 30 + offset))
                urls.append({"post_id": pid, "url": f"https://news.invalid/{i % 3}"})
        self.assertEqual(self.analyze(posts, urls)["signals"], [])

    def test_tighter_timing_increases_score_and_more_active_accounts_reduce_it(self):
        tight, urls = repeated(lag=1)
        loose, _ = repeated(lag=45)
        tight_score = self.analyze(tight, urls)["signals"][0]["network_score"]
        self.assertGreater(tight_score, self.analyze(loose, urls)["signals"][0]["network_score"])
        unrelated = [post(f"noise-{i}", "a" if i % 2 else "b", i * 15) for i in range(80)]
        busy = self.analyze(tight + unrelated, urls)["signals"][0]
        self.assertLess(busy["network_score"], tight_score)
        self.assertLess(busy["score_components"]["activity_damping"], 1)

    def test_resource_popularity_damps_score_without_claiming_a_probability(self):
        posts, urls = repeated()
        before = self.analyze(posts, urls)["signals"][0]
        for episode in range(3):
            for account in range(20):
                pid = f"reader-{episode}-{account}"
                posts.append(post(pid, f"reader-{account}", episode * 600 + 180 + account))
                urls.append({"post_id": pid, "url": f"https://example.invalid/{episode}"})
        data = self.analyze(posts, urls)
        signal = next(s for s in data["signals"] if s["account_ids"] == ["a", "b"])
        self.assertLess(signal["network_score"], before["network_score"])
        self.assertIn("uncalibrated", data["parameters"]["score_calibration"])

    def test_repeated_references_work_without_urls_and_missing_targets_do_not_fake_edges(self):
        posts = []
        for i in range(3):
            for account, offset in (("a", 0), ("b", 2)):
                posts.append(post(f"{i}-{account}", account, i * 600 + offset,
                                  [{"type": "quotes", "target_post_id": f"missing-{i}"}]))
        data = self.analyze(posts)
        self.assertEqual(len(data["signals"]), 1)
        self.assertEqual({n["id"] for n in data["network"]["nodes"]}, {"a", "b"})
        self.assertEqual([e["kind"] for e in data["network"]["edges"]], ["co_share"])
        self.assertEqual(data["signals"][0]["metrics"]["unresolved_references"], 6)
        # Target arrives late in ingestion order, and authors become resolvable.
        posts += [post(f"missing-{i}", "origin", i * 600 - 10) for i in range(3)]
        observed = [e for e in self.analyze(posts)["network"]["edges"] if e["kind"] == "quotes"]
        self.assertEqual({(e["source"], e["target"]) for e in observed}, {("a", "origin"), ("b", "origin")})

    def test_directed_reciprocity_is_descriptive_and_cannot_alone_make_a_signal(self):
        posts = [post("a0", "a", 0), post("b0", "b", 1)]
        posts += [post("a1", "a", 2, [{"type": "replies_to", "target_post_id": "b0"}]),
                  post("b1", "b", 3, [{"type": "replies_to", "target_post_id": "a0"}])]
        data = self.analyze(posts)
        self.assertEqual(data["signals"], [])
        self.assertEqual({(e["source"], e["target"]) for e in data["network"]["edges"]}, {("a", "b"), ("b", "a")})

    def test_future_and_expired_evidence_do_not_enter_current_score(self):
        posts, urls = repeated()
        self.assertEqual(self.analyze(posts, urls, seconds=900)["signals"], [])
        self.assertEqual(self.analyze(posts, urls, seconds=24 * 3600 + 1800)["signals"], [])
        original = post("future-target", "future-author", 10000)
        actor = post("ref", "actor", 0, [{"type": "reposts", "target_post_id": "future-target"}])
        self.assertEqual(self.analyze([actor, original])["network"]["edges"], [])

    def test_replay_out_of_order_and_content_changes_leave_behavior_unchanged(self):
        posts, urls = repeated()
        before = self.analyze(posts, urls)
        changed = [{**p, "text": "opposite claim", "embedding_json": "broken", "stance": "CON",
                    "raw_json": json.dumps({"text": "different language", "cluster_id": "fake", "scenario": "anything"})}
                   for p in posts]
        random.Random(42).shuffle(changed)
        self.assertEqual(before, self.analyze(changed, list(reversed(urls))))
        self.assertEqual(before, self.analyze(iter(posts), urls))

    def test_sqlite_rows_supported_and_exact_window_boundary_included(self):
        posts, urls = repeated(lag=60)
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("CREATE TABLE posts(id,account_id,created_at,raw_json)")
            connection.executemany("INSERT INTO posts VALUES (:id,:account_id,:created_at,:raw_json)", posts)
            self.assertEqual(len(self.analyze(list(connection.execute("SELECT * FROM posts")), urls)["signals"]), 1)
            late, _ = repeated(lag=61)
            self.assertEqual(self.analyze(late, urls)["signals"], [])
        finally:
            connection.close()

    def test_duplicate_raw_relations_and_url_rows_do_not_inflate_evidence(self):
        posts, urls = repeated()
        self.assertEqual(self.analyze(posts, urls), self.analyze(posts, urls + urls))
        relation = {"type": "reposts", "target_post_id": "original"}
        data = self.analyze([post("original", "origin", 0), post("actor", "a", 2, [relation, relation])])
        self.assertEqual(data["network"]["edges"][0]["weight"], 1)

    def test_known_original_after_actor_does_not_make_causal_edges_or_shared_actions(self):
        posts=[]
        for i in range(3):
            posts.append(post(f'future-{i}', 'origin', i*600+100))
            for account,offset in [('a',0),('b',2)]:
                posts.append(post(f'{i}-{account}',account,i*600+offset,
                    [{'type':'quotes','target_post_id':f'future-{i}'}]))
        data=self.analyze(posts)
        self.assertEqual(data['signals'],[])
        self.assertEqual(data['network']['edges'],[])


if __name__ == "__main__":
    unittest.main()
