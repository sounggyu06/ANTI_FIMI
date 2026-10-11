"""Create a two-file ANTI_FIMI AI handoff without changing post IDs or raw data."""
import argparse
import hashlib
from pathlib import Path
import zipfile

from engine import dumps
from import_team_raw import BUNDLE_FORMAT, load_bundle


def pack_bundle(input_path, output_path):
    input_path, output_path = Path(input_path), Path(output_path)
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Output must differ from the original ZIP")
    original, posts, _ = load_bundle(input_path)
    with zipfile.ZipFile(input_path) as archive:
        name = next(n for n in archive.namelist() if n == "manifest.json" or n.endswith("/manifest.json"))
        payload = archive.read(name[:-len("manifest.json")] + "posts.jsonl")
    manifest = {
        "schema_version": 1, "bundle_format": BUNDLE_FORMAT,
        "run_id": original["run_id"], "status": "complete", "stages": {"clustering": "complete"},
        "cluster_id_scope": "run_id + cluster_id", "post_count": len(posts),
        "embedding": {"model_name": original["embedding"]["model_name"]},
        "cluster_counts": {k: original["cluster_counts"][k] for k in ("content", "unassigned")},
        "posts_sha256": hashlib.sha256(payload).hexdigest(),
    }
    for key in ("created_at", "input_sha256", "generated_post_id_scope"):
        if key in original:
            manifest[key] = original[key]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ANTI_FIMI/manifest.json", dumps(manifest) + "\n")
        archive.writestr("ANTI_FIMI/posts.jsonl", payload)
    return {"project": "ANTI_FIMI", "output": str(output_path.resolve()), "files": 2,
            "posts": len(posts), "clusters": manifest["cluster_counts"]["content"],
            "unassigned": manifest["cluster_counts"]["unassigned"],
            "original_bytes": input_path.stat().st_size, "reduced_bytes": output_path.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(dumps(pack_bundle(args.input, args.output)))


if __name__ == "__main__":
    main()
