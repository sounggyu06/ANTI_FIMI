"""Import every teammate bundle post into the independent behavior branch.

Reads JSON only, never extracts or executes archive files. Narrative roles are
preserved in source data, not converted to proposition stance.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import zipfile

from engine import dumps, parse_time, stamp
from fusion import raw_digest
from server import Runtime, RawOnlyEmbedder

ROOT = Path(__file__).resolve().parent.parent
BUNDLE_FORMAT = "ANTI_FIMI_CLUSTER_INPUT_V1"


def load_bundle(path):
    with zipfile.ZipFile(path) as archive:
        candidates = [name for name in archive.namelist() if name.endswith("/manifest.json") or name == "manifest.json"]
        if len(candidates) != 1:
            raise ValueError("Expected exactly one bundle manifest")
        prefix = candidates[0][:-len("manifest.json")]
        manifest = json.loads(archive.read(prefix + "manifest.json"))
        if manifest.get("status") != "complete" or manifest.get("stages", {}).get("clustering") != "complete":
            raise ValueError("Bundle clustering must be complete")
        for value in (manifest.get("run_id"), manifest.get("embedding", {}).get("model_name")):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Bundle requires run_id and embedding.model_name")
        payload = archive.read(prefix + "posts.jsonl")
        if "bundle_format" in manifest:
            if manifest["bundle_format"] != BUNDLE_FORMAT:
                raise ValueError("Unsupported bundle_format")
            if hashlib.sha256(payload).hexdigest() != manifest.get("posts_sha256"):
                raise ValueError("Bundle posts hash does not match manifest")
        elif hashlib.sha256(archive.read(prefix + "input.jsonl")).hexdigest() != manifest["input_sha256"]:
            raise ValueError("Bundle input hash does not match manifest")
        if prefix + "analysis_errors.json" in archive.namelist() and json.loads(archive.read(prefix + "analysis_errors.json")):
            raise ValueError("Bundle contains analysis errors; resolve them before handoff")
        source = [json.loads(line) for line in payload.decode("utf-8-sig").splitlines() if line.strip()]
        if not source:
            raise ValueError("Bundle posts must not be empty")
        for p in source:
            if not isinstance(p, dict) or "content_cluster_id" not in p:
                raise ValueError("Each post requires explicit content_cluster_id (string or null)")
            cid = p["content_cluster_id"]
            if cid is not None and (not isinstance(cid, str) or not cid.strip()):
                raise ValueError("content_cluster_id must be a nonempty string or null")
            for field in ("post_id", "author_id", "created_at"):
                if not isinstance(p.get(field), str) or not p[field].strip():
                    raise ValueError(f"Bundle post {field} must be a nonempty string")
            if not isinstance(p.get("text"), str):
                raise ValueError("Bundle post text must be a string")
            parse_time(p["created_at"])
            assignment = p.get("content_assignment", {})
            if not isinstance(assignment, dict):
                raise ValueError("content_assignment must be an object when provided")
            strength = assignment.get("membership_strength")
            if strength is not None and (isinstance(strength, bool) or not isinstance(strength, (int, float)) or not math.isfinite(strength) or not 0 <= strength <= 1):
                raise ValueError("membership_strength must be null or finite 0..1")
        posts = [{"id": p["post_id"], "account_id": p["author_id"], "created_at": p["created_at"],
                  "text": p["text"], "_source_raw": p, "_bundle_run_id": manifest["run_id"]} for p in source]
        count = manifest.get("post_count")
        if isinstance(count, bool) or not isinstance(count, int) or len(posts) != count or len({p["id"] for p in posts}) != len(posts):
            raise ValueError("Bundle post count or unique IDs do not match manifest")
        counts = {"content": len({p["content_cluster_id"] for p in source if p["content_cluster_id"] is not None}),
                  "unassigned": sum(p["content_cluster_id"] is None for p in source)}
        if any(manifest.get("cluster_counts", {}).get(k) != v for k, v in counts.items()):
            raise ValueError("Bundle cluster counts do not match manifest")
        narratives = json.loads(archive.read(prefix + "narratives.json")) if prefix + "narratives.json" in archive.namelist() else []
        return manifest, posts, narratives


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--db", default=str(ROOT / "ANTI_FIMI_DEMO_DATA" / "ANTI_FIMI_team_bundle.sqlite3"))
    args = parser.parse_args()
    manifest, posts, narratives = load_bundle(args.input)
    runtime = Runtime(args.db, RawOnlyEmbedder(args.db))
    cutoff = max(parse_time(p["created_at"]) for p in posts)
    result = runtime.ingest(posts, stamp(cutoff))
    results = [{"post_id": p["id"], "raw_sha256": raw_digest(dumps(p)),
                "model_version": manifest["embedding"]["model_name"], "scope_id": manifest["run_id"], "revision": 1,
                "cluster_id": p["_source_raw"].get("content_cluster_id"),
                "membership_strength": p["_source_raw"].get("content_assignment", {}).get("membership_strength")}
               for p in posts]
    ai_result = runtime.receive_ai(results)
    folder = ROOT / "ANTI_FIMI_DEMO_DATA" / "team_bundle"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "raw_posts.jsonl").write_text("".join(dumps(p) + "\n" for p in posts), encoding="utf-8")
    if narratives:
        (folder / "narratives_reference.json").write_text(dumps(narratives), encoding="utf-8")
    (folder / "manifest_reference.json").write_text(dumps(manifest), encoding="utf-8")
    snapshot = runtime.dashboard()
    (folder / "behavior_snapshot.json").write_text(dumps(snapshot), encoding="utf-8")
    print(dumps({"project": "ANTI_FIMI", "run_id": manifest["run_id"], "raw_posts": len(posts),
        "behavior_signals": snapshot["global_signals_count"], "investigations": len(snapshot["investigations"]),
        "ai_clustering_results_received": len(results), "content_clusters": len(snapshot["cases"]),
        "ai_inserted": ai_result["inserted"], "ai_duplicates": ai_result["duplicates"],
        "unassigned_posts": len(snapshot["unlinked_posts"]), "ai_stance_results_imported": 0, "narratives_preserved_as_reference": len(narratives), **result}))


if __name__ == "__main__":
    main()
