"""Generate unlabeled ANTI_FIMI synthetic posts and verify an end-to-end demo."""
import argparse
from datetime import timedelta
import json
from pathlib import Path

from engine import Engine, LexicalDemoEmbedder, SemanticEmbedder, dumps, parse_time, stamp

DEMO_ROOT = Path(__file__).resolve().parent.parent / "ANTI_FIMI_DEMO_DATA"

BASE = parse_time("2026-10-01T00:00:00Z")
AS_OF = BASE + timedelta(hours=8)
CLAIM = "The joint disaster relief exercise was cancelled. APAC partners cannot coordinate disaster relief."
USER_SAMPLES = [
    "Share before this disappears: the joint relief exercise was cancelled and the public deserves answers. I will follow the updates.",
    "공동훈련 취소설이 너무 빨라서 훈련 일정표보다 소문이 먼저 출동했네요. 후속 소식을 지켜보겠습니다.",
    "If this joint relief exercise was cancelled, how can Korea and APAC partners coordinate during a disaster? I will follow the updates.",
    "공동훈련 취소설을 계기로 APAC 협력 예산을 공개적으로 검토했으면 합니다. 후속 소식을 지켜보겠습니다.",
    "재난구호훈련이 취소됐다는 글을 봤습니다. 지역 구조 인력 지원에도 영향이 있을까요? 후속 소식을 지켜보겠습니다.",
    "훈련 취소 주장의 출처는 이 링크뿐인가요? 원문과 발표 시각을 확인 중입니다. 후속 소식을 지켜보겠습니다",
]


def demo_posts():
    posts = []

    def add(pid, account, minutes, text, urls=None):
        posts.append({"id": pid, "account_id": account, "created_at": stamp(BASE + timedelta(minutes=minutes)),
                      "text": text, "urls": urls or []})

    # Six completed baseline hours, with counts [2,2,2,2,2,2].
    for h in range(6):
        for i in range(2):
            add(f"baseline-{h}-{i}", f"ordinary-{i}", h * 60 + i * 10, CLAIM)
    # Four independent sharing episodes, six accounts, one exact URL. No input labels.
    for episode in range(4):
        for account in range(6):
            add(f"burst-{episode}-{account}", f"account-{account}", 365 + episode * 10 + account / 30,
                CLAIM, ["https://example.invalid/article?id=relief-cancelled&utm_source=demo"])
    for i, sample in enumerate(USER_SAMPLES):
        add(f"user-sample-{i}", f"observer-{i}", 425 + i, sample)
    add("refute-en", "checker-en", 432,
        "The joint disaster relief exercise was not cancelled. APAC partners can coordinate disaster relief.")
    add("refute-ko", "checker-ko", 433, "공동 재난구호훈련은 취소되지 않았습니다. APAC 협력 훈련은 예정대로 진행됩니다.")
    add("claim-ko", "observer-ko", 434, "공동 재난구호훈련이 취소됐습니다. APAC 파트너들은 재난 구호를 조율할 수 없습니다.")
    add("unrelated", "gardener", 435, "The community garden opens this weekend. Bring seeds and tools.")
    return posts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEMO_ROOT / "posts" / "demo_posts.jsonl"))
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--db", default=str(DEMO_ROOT / "ANTI_FIMI_demo.sqlite3"))
    parser.add_argument("--results", default=str(DEMO_ROOT / "results" / "demo"))
    parser.add_argument("--embedder", choices=("lexical-demo", "semantic"), default="lexical-demo")
    args = parser.parse_args()
    posts = demo_posts()
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(dumps(p) for p in posts) + "\n", encoding="utf-8")
    summary = {"project": "ANTI_FIMI", "generated_posts": len(posts), "input": str(target),
               "synthetic": True, "embedder": args.embedder}
    if args.run:
        embedder = SemanticEmbedder() if args.embedder == "semantic" else LexicalDemoEmbedder()
        with Engine(args.db, embedder) as engine:
            summary.update(engine.ingest(posts))
            alerts = engine.analyze(AS_OF)
            summary.update(engine.export(args.results))
            reasons = {r for a in alerts for r in a["reason_codes"]}
            required = {"REPEATED_URL_COSHARE", "HOURLY_DIFFUSION_SPIKE"}
            if not required <= reasons:
                raise RuntimeError(f"demo did not trigger required reasons: {required - reasons}")
            if any(not a["evidence_post_ids"] for a in alerts):
                raise RuntimeError("demo alert missing evidence")
            before = dumps(alerts)
        with Engine(args.db, embedder) as restored:
            if dumps(restored.analyze(AS_OF)) != before:
                raise RuntimeError("restart changed alerts")
            if restored.ingest(posts) != {"inserted": 0, "duplicates": len(posts)}:
                raise RuntimeError("replay is not idempotent")
        summary["verified_reason_codes"] = sorted(reasons)
        summary["restart_and_replay"] = "PASS"
        summary["semantic_model_quality"] = "not measured by this synthetic demo"
        Path(args.results, "demo_verification.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(dumps(summary))


if __name__ == "__main__":
    main()
