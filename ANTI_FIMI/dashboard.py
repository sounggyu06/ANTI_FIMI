"""Build one coherent, event-scoped dashboard response from a read-only SQLite snapshot."""
from collections import Counter, defaultdict
from datetime import timedelta
import json
import sqlite3
from pathlib import Path

from engine import Config, co_sharing, dumps, hour, hourly_diffusion, key, parse_time, stamp, UTC
from datetime import datetime

REASONS = {
    "REPEATED_URL_COSHARE": "같은 URL을 여러 차례 함께 공유",
    "CROSS_ACCOUNT_SYNCHRONY": "서로 다른 계정의 공유 시각이 가까움",
    "HOURLY_DIFFUSION_SPIKE": "완료 시간대 게시량이 기준선보다 급증",
    "MULTI_ACCOUNT_SPREAD": "여러 계정이 확산에 참여",
    "PROVISIONAL_NARRATIVE": "잠정 서사 군집에서 관측",
}
BASIS = {"SEED_POST": "첫 관측 게시물", "OBSERVED_REFERENCE": "인용·재공유·댓글의 원본 참조",
         "SHARED_ARTICLE_URL": "동일 기사 URL", "TEXT_VECTOR_SIMILARITY": "대표문·중심 벡터 유사도"}


def snapshot(db, feed=None, observed_now=None):
    connection = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN")
        metadata = dict(connection.execute("SELECT key,value FROM metadata"))
        config = Config(**json.loads(metadata["identity"])["config"])
        as_of = parse_time(metadata["last_analysis_at"])
        # Memberships, not just created_at, exclude posts ingested after the last analysis.
        rows = list(connection.execute("""SELECT p.*,a.cluster_id,m.event_id
            FROM assignments a JOIN posts p ON p.id=a.post_id
            JOIN event_memberships m ON m.post_id=p.id ORDER BY p.seq"""))
        urls_by_post = defaultdict(list)
        url_rows = list(connection.execute("SELECT post_id,url FROM post_urls"))
        for row in url_rows:
            urls_by_post[row["post_id"]].append(row["url"])
        by_event = defaultdict(list)
        for row in rows:
            by_event[row["event_id"]].append(row)
        total_raw = connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        cases = []
        for event in connection.execute("SELECT * FROM events ORDER BY first_seen,id"):
            members = by_event[event["id"]]
            if not members:
                continue
            assignment = {p["id"]: p["cluster_id"] for p in members}
            # Reevaluate within the selected event. Global episode counts cannot be relabeled as local evidence.
            alerts = co_sharing(members, assignment, url_rows, config)
            volume, _ = hourly_diffusion(members, assignment, hour(as_of), config)
            alerts += volume
            alerts.sort(key=lambda a: (a["priority"], a["window_end"] if "window_end" in a else a["hour"], a["id"]))
            for alert in alerts:
                alert["id"] = key("EA_", [event["id"], alert["id"]])
                alert["reason_labels"] = [REASONS.get(r, r) for r in alert["reason_codes"]]
                if alert["kind"] == "repeated_url_coshare":
                    alert["label"] = "반복 공동 공유"
                    alert["summary"] = f"계정 {len(alert['account_ids'])}개가 동일 URL을 {alert['episode_count']}차례 공동 공유했습니다."
                    alert["metrics"] = {"공동 공유 차례": alert["episode_count"], "관측 종료": alert["window_end"]}
                else:
                    alert["label"] = "서사 확산 급증"
                    alert["summary"] = f"시간당 {alert['baseline_mean']:g}개 기준 대비 {alert['post_count']}개 게시물, {alert['ratio']:g}배 증가했습니다."
                    alert["metrics"] = {"게시물": alert["post_count"], "기준선": alert["baseline_mean"],
                                        "증가 배수": alert["ratio"], "직전 6시간": alert["baseline_counts"], "시간": alert["hour"]}
            posts, accounts, narratives = [], defaultdict(list), defaultdict(list)
            for member in members:
                raw = json.loads(member["raw_json"])
                post = {"id": member["id"], "account_id": member["account_id"], "created_at": member["created_at"],
                        "text": member["text"], "urls": urls_by_post[member["id"]],
                        "narrative_id": member["cluster_id"], "stance_hint": member["stance"],
                        "language": raw.get("language_hint"), "relations": raw.get("relations", []) or []}
                posts.append(post)
                accounts[member["account_id"]].append(post)
                narratives[member["cluster_id"]].append(post)
            post_lookup = {p["id"]: p for p in posts}
            edges = []
            for alert in alerts:
                if alert["kind"] == "repeated_url_coshare":
                    edges.append({"id": "edge:" + alert["id"], "source": alert["account_ids"][0],
                                  "target": alert["account_ids"][1], "kind": "co_share",
                                  "evidence_post_ids": alert["evidence_post_ids"], "alert_ids": [alert["id"]],
                                  "weight": alert["episode_count"]})
            for post in posts:
                for relation in post["relations"]:
                    if not isinstance(relation, dict) or relation.get("type") not in ("quotes", "reposts", "replies_to"):
                        continue
                    original = post_lookup.get(relation.get("target_post_id"))
                    if original and original["account_id"] != post["account_id"]:
                        edges.append({"id": key("edge:", [post["id"], original["id"], relation["type"]]),
                                      "source": post["account_id"], "target": original["account_id"],
                                      "kind": relation["type"], "evidence_post_ids": [original["id"], post["id"]],
                                      "alert_ids": [], "weight": 1})
            counts, per_hour_accounts = Counter(), defaultdict(set)
            for post in posts:
                bucket = hour(parse_time(post["created_at"]))
                counts[bucket] += 1
                per_hour_accounts[bucket].add(post["account_id"])
            first, last = min(counts), max(counts)
            timeline, current = [], first
            while current <= last:
                baseline = None
                if current >= first + timedelta(hours=config.baseline_hours):
                    baseline = sum(counts[current - timedelta(hours=i)] for i in range(1, config.baseline_hours + 1)) / config.baseline_hours
                timeline.append({"time": stamp(current), "count": counts[current],
                                 "account_count": len(per_hour_accounts[current]), "baseline": baseline,
                                 "partial": current >= hour(as_of)})
                current += timedelta(hours=1)
            coordinated = {a for alert in alerts if alert["kind"] == "repeated_url_coshare" for a in alert["account_ids"]}
            spikes = [a for a in alerts if a["kind"] == "hourly_diffusion_spike"]
            summary = f"게시물 {len(posts)}개 · 관련 계정 {len(accounts)}개. "
            summary += f"{len(coordinated)}개 계정 사이에서 반복 공동 공유를 관측했습니다." if coordinated else "반복 공동 공유 경보는 아직 없습니다."
            if spikes:
                summary += f" 서사별 확산 급증 {len(spikes)}건을 함께 검토하세요."
            cases.append({"id": event["id"], "title": event["title"], "summary": summary,
                          "first_seen": event["first_seen"], "last_seen": event["last_seen"],
                          "post_count": len(posts), "account_count": len(accounts), "alert_count": len(alerts),
                          "languages": sorted({p["language"] for p in posts if isinstance(p["language"], str) and p["language"]}),
                          "priority": "review_high" if coordinated else "review_medium" if alerts else "none",
                          "basis": [BASIS.get(b, b) for b in json.loads(event["basis_json"])],
                          "posts": posts, "alerts": alerts,
                          "network": {"nodes": [{"id": account, "label": account, "post_count": len(items),
                                                 "stance_hints": sorted({p["stance_hint"] for p in items})}
                                                for account, items in sorted(accounts.items())], "edges": edges},
                          "hourly": timeline,
                          "narratives": [{"id": cid, "label": items[0]["text"][:90], "stance_hint": items[0]["stance_hint"],
                                          "post_count": len(items), "evidence_post_ids": [p["id"] for p in items]}
                                         for cid, items in narratives.items()]})
        cases.sort(key=lambda c: (-c["alert_count"], -c["post_count"], c["id"]))
        data = {"schema_version": "1.0", "analysis_as_of": metadata["last_analysis_at"],
                "analyzed_at": metadata.get("analysis_completed_at"),
                "data_mode": "lexical-demo" if "lexical-demo" in json.loads(metadata["identity"])["embedder"] else "semantic",
                "feed": feed or {"status": "idle", "error": None, "last_ingested_at": None},
                "summary": {"case_count": len(cases), "post_count": len(rows),
                            "account_count": len({p["account_id"] for p in rows}),
                            "alert_count": sum(c["alert_count"] for c in cases), "pending_post_count": total_raw - len(rows)},
                "cases": cases,
                "limitations": ["사건 후보와 경보는 공작·허위성·국가 배후의 확정 판정이 아닙니다.",
                                "문자 특징 데모는 다국어 의미 군집 품질을 보장하지 않습니다.",
                                "사건은 72시간 범위의 대표문·중심 유사도, 기사 URL, 원본 참조로 잠정 연결하며 주 소속은 하나입니다.",
                                "공동 공유선은 추정 관계이며 인용·재공유·댓글선은 제공된 원본 참조를 뜻합니다.",
                                "수집 완전성은 미확인입니다. 시간선의 0은 수집 누락일 수도 있습니다.",
                                "실제 VEIL API·외부 AI 계약 수신·딥페이크 판별은 추가 연결이 필요합니다."]}
        from snapshot_fusion import extend_snapshot
        extend_snapshot(connection, metadata, data, urls_by_post, observed_now)
        from spread import spread_metrics
        spread_mode = metadata.get('source_clock_mode', 'replay')
        spread_cutoff = max(as_of, observed_now or datetime.now(UTC)) if spread_mode == 'live' else as_of
        observed_start = connection.execute('SELECT MIN(created_at) FROM posts WHERE created_at<=?',
                                            (stamp(spread_cutoff),)).fetchone()[0]
        for event in [*data['cases'], *data.get('issue_cases', []), *data.get('investigations', [])]:
            event['spread'] = spread_metrics(event['posts'], spread_cutoff, observed_start)
        data['spread_clock'] = {'mode': spread_mode, 'as_of': stamp(spread_cutoff)}
        # ANTI_FIMI_SOURCE_TRACE_V1: event-scoped observed references only.
        from source_trace import analyze_source_trace
        collected_post_ids = {r[0] for r in connection.execute("SELECT id FROM posts")}
        for event in [*data['cases'], *data.get('issue_cases', []), *data.get('investigations', [])]:
            event['source_trace'] = analyze_source_trace(event['posts'], collected_post_ids)
        data["snapshot_id"] = key("S_", data)
        data["generated_at"] = stamp(datetime.now(UTC))
        connection.rollback()
        return data
    finally:
        connection.close()
