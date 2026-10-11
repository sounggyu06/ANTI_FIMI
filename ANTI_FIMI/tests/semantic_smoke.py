"""Opt-in real-model smoke check; run from the project root (not unittest discovery)."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import Engine, SemanticEmbedder, cosine, dumps, parse_time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "ANTI_FIMI_DEMO_DATA" / "results" / "semantic_smoke.json"))
    args = parser.parse_args()
    embedder = SemanticEmbedder()
    texts = {
        "en": "The joint disaster relief exercise was cancelled. APAC partners cannot coordinate disaster relief.",
        "ko": "공동 재난구호훈련이 취소됐습니다. APAC 파트너들은 재난 구호를 조율할 수 없습니다.",
        "ja": "共同災害救援訓練は中止されました。APACのパートナーは災害救援を調整できません。",
        "zh": "联合救灾演习被取消了。APAC伙伴无法协调救灾工作。",
        "refute_en": "The joint disaster relief exercise was not cancelled. APAC partners can coordinate disaster relief.",
        "refute_ko": "공동 재난구호훈련은 취소되지 않았습니다. APAC 협력 훈련은 예정대로 진행됩니다.",
        "unrelated": "The community garden opens this weekend. Bring seeds and tools.",
    }
    vectors = dict(zip(texts, embedder.encode(list(texts.values()))))
    similarities = {name: cosine(vectors["en"], vector) for name, vector in vectors.items()}
    raw = [{"id": name, "account_id": name, "created_at": "2026-10-01T00:00:00Z", "text": text}
           for name, text in texts.items()]
    with tempfile.TemporaryDirectory(prefix="ANTI_FIMI_semantic_") as directory:
        with Engine(Path(directory, "test.sqlite3"), embedder) as engine:
            engine.ingest(raw)
            engine.analyze(parse_time("2026-10-01T01:00:00Z"))
            assignments = dict(engine.conn.execute("SELECT post_id,cluster_id FROM assignments"))
    checks = {
        "en_ko_translation_cluster": assignments["en"] == assignments["ko"],
        "en_ja_translation_cluster": assignments["en"] == assignments["ja"],
        "en_zh_translation_cluster": assignments["en"] == assignments["zh"],
        "english_refutation_separate": assignments["en"] != assignments["refute_en"],
        "korean_refutation_separate": assignments["en"] != assignments["refute_ko"],
        "unrelated_separate": assignments["en"] != assignments["unrelated"],
    }
    report = {"model": embedder.identity, "similarity_to_en": similarities, "checks": checks,
              "status": "PASS" if all(checks.values()) else "FAIL",
              "limitation": "Seven curated texts; not a benchmark or FIMI/stance accuracy estimate."}
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(dumps(report))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
