"""Clearly synthetic raw-only behavioral demo; does not fabricate AI results."""
import argparse
from datetime import timedelta
from pathlib import Path

from engine import dumps, parse_time, stamp
from server import Runtime, RawOnlyEmbedder

ROOT = Path(__file__).resolve().parent.parent
BASE = parse_time("2026-10-01T00:00:00Z")


def demo_posts():
    posts = []
    topics = ["공동훈련 일정에 관한 자료를 공유합니다.", "APAC 협력 예산 자료를 공유합니다.",
              "재난 지원 현황 링크를 공유합니다.", "지역 구호 활동 소식을 공유합니다."]
    for episode, topic in enumerate(topics):
        for actor in range(6):
            posts.append({"id": f"demo-co-{episode}-{actor}", "account_id": f"demo_account_{actor + 1}",
                "created_at": stamp(BASE + timedelta(hours=episode, seconds=actor)), "text": topic,
                "urls": [f"https://demo.invalid/article/{episode}"], "language_hint": "ko"})
    for actor in range(20):
        posts.append({"id": f"demo-news-{actor}", "account_id": f"demo_news_reader_{actor + 1}",
            "created_at": stamp(BASE + timedelta(hours=4, seconds=actor)), "text": "속보 원문을 공유합니다.",
            "urls": ["https://demo.invalid/breaking-news"], "language_hint": "ko"})
    for actor, text in enumerate(("오늘 점심은 국수입니다.", "퇴근길에 비가 오네요.", "훈련 취소 소식의 근거가 궁금합니다.",
                                 "The exercise schedule is still being checked.", "公式発表を確認しています。")):
        posts.append({"id": f"demo-ordinary-{actor}", "account_id": f"demo_person_{actor + 1}",
            "created_at": stamp(BASE + timedelta(hours=5, minutes=actor)), "text": text, "urls": []})
    return posts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(ROOT / "ANTI_FIMI_DEMO_DATA" / "ANTI_FIMI_fusion_demo.sqlite3"))
    args = parser.parse_args()
    posts = demo_posts()
    folder = ROOT / "ANTI_FIMI_DEMO_DATA" / "posts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "fusion_demo_posts.jsonl").write_text("".join(dumps(p) + "\n" for p in posts), encoding="utf-8")
    runtime = Runtime(args.db, RawOnlyEmbedder(args.db))
    result = runtime.ingest(posts, stamp(BASE + timedelta(hours=6)))
    before = runtime.dashboard()
    replay = Runtime(args.db, RawOnlyEmbedder(args.db))
    assert replay.ingest(posts, stamp(BASE + timedelta(hours=6)))["duplicates"] == len(posts)
    after = replay.dashboard()
    assert [i["id"] for i in before["investigations"]] == [i["id"] for i in after["investigations"]]
    assert len(after["investigations"]) == 1 and after["global_signals_count"] == 15
    assert after["pipeline"]["ai_received_count"] == 0
    assert after["investigations"][0]["account_count"] == 6
    assert all(a.startswith("demo_account_") for i in after["investigations"] for a in {p["account_id"] for p in i["posts"]})
    output = ROOT / "ANTI_FIMI_DEMO_DATA" / "fusion_results"
    output.mkdir(parents=True, exist_ok=True)
    (output / "dashboard.json").write_text(dumps(after), encoding="utf-8")
    print(dumps({"project": "ANTI_FIMI", "synthetic": True, "raw_posts": len(posts),
        "pair_signals": after["global_signals_count"], "investigations": len(after["investigations"]),
        "ordinary_news_accounts_flagged": 0, "external_ai_received": 0,
        "restart_replay": "PASS", **result}))


if __name__ == "__main__":
    main()
