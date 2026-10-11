import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from engine import dumps, parse_time, stamp
from fusion import raw_digest
from import_team_raw import BUNDLE_FORMAT, load_bundle
from pack_ai_bundle import pack_bundle
from server import Runtime, RawOnlyEmbedder


class AIBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.original = self.folder / "original.zip"
        self.slim = self.folder / "slim.zip"
        self.posts = [
            {"post_id": f"p{i}", "author_id": f"a{i}", "created_at": f"2026-10-01T00:0{i}:00Z",
             "text": text, "content_cluster_id": cid, "source_record": {"text": text}}
            for i, (text, cid) in enumerate([("Joint exercise report", "c1"), ("공동훈련 소식", "c1"), ("일반 글", None)])
        ]
        self.manifest = {"run_id": "fixture-run", "status": "complete", "stages": {"clustering": "complete"},
                         "input_sha256": hashlib.sha256(b"original snapshot\n").hexdigest(), "post_count": 3,
                         "embedding": {"model_name": "fixture-v1"}, "cluster_counts": {"content": 1, "unassigned": 1}}
        self.write_original()

    def tearDown(self):
        self.temp.cleanup()

    def write_original(self, posts=None, manifest=None, errors=None):
        with zipfile.ZipFile(self.original, "w") as archive:
            archive.writestr("run/manifest.json", dumps(manifest if manifest is not None else self.manifest))
            archive.writestr("run/posts.jsonl", "".join(dumps(p) + "\n" for p in (posts if posts is not None else self.posts)))
            archive.writestr("run/input.jsonl", b"original snapshot\n")
            archive.writestr("run/narratives.json", '[{"title":"optional legacy summary"}]')
            archive.writestr("run/analysis_errors.json", dumps(errors or []))
            archive.writestr("run/embeddings.npy", b"unused vector artifact")

    def rewrite_slim(self, manifest_change=None, payload_change=None):
        with zipfile.ZipFile(self.slim) as archive:
            manifest = json.loads(archive.read("ANTI_FIMI/manifest.json"))
            payload = archive.read("ANTI_FIMI/posts.jsonl")
        if manifest_change:
            manifest_change(manifest)
        if payload_change:
            payload = payload_change(payload)
        with zipfile.ZipFile(self.slim, "w") as archive:
            archive.writestr("ANTI_FIMI/manifest.json", dumps(manifest))
            archive.writestr("ANTI_FIMI/posts.jsonl", payload)

    def test_two_files_preserve_all_raw_posts_ids_and_unassigned(self):
        result = pack_bundle(self.original, self.slim)
        with zipfile.ZipFile(self.original) as before, zipfile.ZipFile(self.slim) as after:
            self.assertEqual(set(after.namelist()), {"ANTI_FIMI/manifest.json", "ANTI_FIMI/posts.jsonl"})
            self.assertEqual(before.read("run/posts.jsonl"), after.read("ANTI_FIMI/posts.jsonl"))
        legacy, old_posts, references = load_bundle(self.original)
        compact, new_posts, no_references = load_bundle(self.slim)
        self.assertEqual(old_posts, new_posts)
        self.assertEqual((legacy["run_id"], legacy["embedding"]), (compact["run_id"], compact["embedding"]))
        self.assertEqual(compact["bundle_format"], BUNDLE_FORMAT)
        self.assertEqual(result["unassigned"], 1)
        self.assertEqual(len(references), 1)
        self.assertEqual(no_references, [])

    def test_legacy_to_slim_import_and_restart_are_idempotent(self):
        pack_bundle(self.original, self.slim)
        db = self.folder / "state.db"
        clock = lambda: parse_time("2026-10-01T01:00:00Z")
        runtime = Runtime(db, RawOnlyEmbedder(db), clock=clock)
        for path, expected_new, expected_duplicate in ((self.original, 3, 0), (self.slim, 0, 3)):
            manifest, posts, _ = load_bundle(path)
            raw_result = runtime.ingest(posts, stamp(clock()))
            ai = [{"post_id": p["id"], "raw_sha256": raw_digest(dumps(p)), "model_version": manifest["embedding"]["model_name"],
                   "scope_id": manifest["run_id"], "revision": 1, "cluster_id": p["_source_raw"]["content_cluster_id"],
                   "membership_strength": None} for p in posts]
            ai_result = runtime.receive_ai(ai)
            self.assertEqual((raw_result["inserted"], raw_result["duplicates"]), (expected_new, expected_duplicate))
            self.assertEqual((ai_result["inserted"], ai_result["duplicates"]), (expected_new, expected_duplicate))
            runtime = Runtime(db, RawOnlyEmbedder(db), clock=clock)
        snapshot = runtime.dashboard()
        self.assertEqual(snapshot["pipeline"]["ai_received_count"], 3)
        self.assertEqual(len(snapshot["cases"]), 1)
        self.assertEqual(len(snapshot["unlinked_posts"]), 1)
        self.assertEqual(runtime.ai_pending()["items"], [])

    def test_slim_payload_hash_missing_or_tampered_is_rejected(self):
        for change in (lambda m: m.pop("posts_sha256"), lambda m: m.update(posts_sha256="0" * 64)):
            with self.subTest(change=change):
                pack_bundle(self.original, self.slim)
                self.rewrite_slim(manifest_change=change)
                with self.assertRaisesRegex(ValueError, "posts hash"):
                    load_bundle(self.slim)
        pack_bundle(self.original, self.slim)
        self.rewrite_slim(payload_change=lambda b: b.replace(b"Joint", b"Other"))
        with self.assertRaisesRegex(ValueError, "posts hash"):
            load_bundle(self.slim)

    def test_unknown_format_is_rejected(self):
        pack_bundle(self.original, self.slim)
        self.rewrite_slim(manifest_change=lambda m: m.update(bundle_format="unknown"))
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            load_bundle(self.slim)

    def test_missing_assignment_is_not_treated_as_unassigned(self):
        posts = copy.deepcopy(self.posts)
        del posts[-1]["content_cluster_id"]
        self.write_original(posts=posts)
        with self.assertRaisesRegex(ValueError, "explicit content_cluster_id"):
            pack_bundle(self.original, self.slim)
        self.assertFalse(self.slim.exists())

    def test_incomplete_or_failed_runs_are_not_silently_packed(self):
        for change in ({"status": "failed"}, {"stages": {"clustering": "running"}}):
            with self.subTest(change=change):
                self.write_original(manifest={**self.manifest, **change})
                with self.assertRaisesRegex(ValueError, "must be complete"):
                    pack_bundle(self.original, self.slim)
        self.write_original(errors=[{"error": "analysis failed"}])
        with self.assertRaisesRegex(ValueError, "analysis errors"):
            pack_bundle(self.original, self.slim)
        self.assertFalse(self.slim.exists())

    def test_wrong_counts_and_duplicate_ids_are_rejected(self):
        for change in ({"post_count": 2}, {"post_count": True}, {"cluster_counts": {"content": 1, "unassigned": 0}}):
            with self.subTest(change=change):
                self.write_original(manifest={**self.manifest, **change})
                with self.assertRaises(ValueError):
                    pack_bundle(self.original, self.slim)
        posts = copy.deepcopy(self.posts)
        posts[-1]["post_id"] = posts[0]["post_id"]
        self.write_original(posts=posts)
        with self.assertRaisesRegex(ValueError, "unique IDs"):
            pack_bundle(self.original, self.slim)

    def test_invalid_cluster_or_membership_is_rejected_before_handoff(self):
        for value in ("", 42, [], True):
            with self.subTest(cluster=value):
                posts = copy.deepcopy(self.posts)
                posts[0]["content_cluster_id"] = value
                self.write_original(posts=posts)
                with self.assertRaisesRegex(ValueError, "nonempty string or null"):
                    pack_bundle(self.original, self.slim)
        posts = copy.deepcopy(self.posts)
        posts[0]["content_assignment"] = {"membership_strength": 1.1}
        self.write_original(posts=posts)
        with self.assertRaisesRegex(ValueError, "membership_strength"):
            pack_bundle(self.original, self.slim)

    def test_original_archive_cannot_be_overwritten(self):
        before = self.original.read_bytes()
        with self.assertRaisesRegex(ValueError, "differ from"):
            pack_bundle(self.original, self.original)
        self.assertEqual(self.original.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
