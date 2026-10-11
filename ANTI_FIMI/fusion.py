"""External AI result contract and evidence-preserving investigation aggregation."""
from collections import Counter, defaultdict
import hashlib
import json
import math

FUSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_results(
 post_id TEXT PRIMARY KEY REFERENCES posts(id), raw_sha256 TEXT NOT NULL,
 model_version TEXT NOT NULL, scope_id TEXT NOT NULL, revision INTEGER NOT NULL,
 received_at TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS behavior_signals(
 id TEXT PRIMARY KEY, active INTEGER NOT NULL, first_detected_at TEXT NOT NULL,
 last_evaluated_at TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS investigation_history(
 investigation_id TEXT NOT NULL, evaluated_at TEXT NOT NULL, payload_json TEXT NOT NULL,
 PRIMARY KEY(investigation_id,evaluated_at));
CREATE TABLE IF NOT EXISTS investigations(
 id TEXT PRIMARY KEY, seed_signal_id TEXT NOT NULL, active INTEGER NOT NULL,
 first_detected_at TEXT NOT NULL, last_evaluated_at TEXT NOT NULL, payload_json TEXT NOT NULL);
"""
STANCES = {"PRO", "CON", "NEUTRAL", "QUESTION", "UNKNOWN"}


def raw_digest(serialized):
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def pending_ai(connection, limit=100, after_seq=0):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit must be 1..500")
    if isinstance(after_seq, bool) or not isinstance(after_seq, int) or after_seq < 0:
        raise ValueError("after_seq must be a nonnegative integer")
    rows = connection.execute("""SELECT p.* FROM posts p LEFT JOIN ai_results a ON a.post_id=p.id
        WHERE a.post_id IS NULL AND p.seq>? ORDER BY p.seq LIMIT ?""", (after_seq, limit)).fetchall()
    return {"schema_version": "1.0", "items": [{"seq": p["seq"], "post_id": p["id"],
            "raw_sha256": raw_digest(p["raw_json"]), "raw": json.loads(p["raw_json"])} for p in rows],
            "next_after_seq": rows[-1]["seq"] if rows else after_seq}


def store_ai_results(connection, results, received_at):
    from engine import dumps
    if not isinstance(results, list) or not results:
        raise ValueError("results must be a nonempty array")
    inserted = updated = duplicates = 0
    replacing = {r.get("post_id") for r in results if isinstance(r, dict) and isinstance(r.get("post_id"), str)}
    registry = {}
    connection.execute("BEGIN IMMEDIATE")
    try:
        for row in connection.execute("SELECT post_id,payload_json FROM ai_results"):
            if row["post_id"] not in replacing:
                saved = json.loads(row["payload_json"])
                for claim in saved.get("claims", []):
                    registry[(saved["model_version"], saved["scope_id"], claim["claim_id"])] = (claim["cluster_id"], claim["claim_text"])
        for result in results:
            if not isinstance(result, dict):
                raise ValueError("AI result must be an object")
            for field in ("post_id", "raw_sha256", "model_version", "scope_id"):
                if not isinstance(result.get(field), str) or not result[field].strip():
                    raise ValueError(f"AI {field} must be a nonempty string")
            revision = result.get("revision")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise ValueError("AI revision must be a positive integer")
            raw = connection.execute("SELECT raw_json,text FROM posts WHERE id=?", (result["post_id"],)).fetchone()
            if not raw or result["raw_sha256"] != raw_digest(raw["raw_json"]):
                raise ValueError("AI post_id/raw_sha256 does not match stored immutable raw post")
            if "cluster_id" in result:
                cid = result["cluster_id"]
                if cid is not None and (not isinstance(cid, str) or not cid.strip()):
                    raise ValueError("cluster_id must be a nonempty string or null for unassigned")
                if "claims" in result:
                    raise ValueError("send cluster_id or legacy claims, not both")
                if result.get("cluster_label") is not None and (not isinstance(result["cluster_label"], str) or not result["cluster_label"].strip()):
                    raise ValueError("cluster_label must be a nonempty string or null")
                strength = result.get("membership_strength")
                if strength is not None and (isinstance(strength, bool) or not isinstance(strength, (int, float)) or not math.isfinite(strength) or not 0 <= strength <= 1):
                    raise ValueError("membership_strength must be null or finite 0..1; not a manipulation probability")
                claims = []
            else:
                claims = result.get("claims")
                if not isinstance(claims, list):
                    raise ValueError("AI result requires cluster_id (nullable); legacy claims array is also supported")
            seen = set()
            for claim in claims:
                if not isinstance(claim, dict):
                    raise ValueError("AI claim must be an object")
                for field in ("cluster_id", "claim_id", "claim_text", "evidence_text", "stance"):
                    if not isinstance(claim.get(field), str) or not claim[field].strip():
                        raise ValueError(f"claim {field} must be a nonempty string")
                if claim["stance"] not in STANCES:
                    raise ValueError("stance must be PRO/CON/NEUTRAL/QUESTION/UNKNOWN")
                confidence = claim.get("confidence")
                if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                    raise ValueError("AI confidence must be finite and between 0 and 1")
                if claim["evidence_text"] not in raw["text"]:
                    raise ValueError("claim evidence_text must be an exact substring of the raw text")
                if claim["claim_id"] in seen:
                    raise ValueError("duplicate claim_id in one post result")
                seen.add(claim["claim_id"])
                identity = (result["model_version"], result["scope_id"], claim["claim_id"])
                definition = (claim["cluster_id"], claim["claim_text"])
                if identity in registry and registry[identity] != definition:
                    raise ValueError("claim_id must identify one consistent proposition and cluster within model/scope")
                registry[identity] = definition
            serialized = dumps(result)
            old = connection.execute("SELECT revision,payload_json FROM ai_results WHERE post_id=?", (result["post_id"],)).fetchone()
            if old:
                if revision < old["revision"]:
                    raise ValueError("stale AI revision; latest post result is retained")
                if revision == old["revision"]:
                    if old["payload_json"] != serialized:
                        raise ValueError("conflicting AI payload for same post revision")
                    duplicates += 1
                    continue
                updated += 1
            else:
                inserted += 1
            connection.execute("""INSERT INTO ai_results VALUES(?,?,?,?,?,?,?) ON CONFLICT(post_id)
                DO UPDATE SET raw_sha256=excluded.raw_sha256,model_version=excluded.model_version,
                scope_id=excluded.scope_id,revision=excluded.revision,received_at=excluded.received_at,
                payload_json=excluded.payload_json""", (result["post_id"], result["raw_sha256"],
                result["model_version"], result["scope_id"], revision, received_at, serialized))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return {"inserted": inserted, "updated": updated, "duplicates": duplicates}


def ai_claims_by_post(connection):
    from engine import key
    output = {}
    for row in connection.execute("SELECT post_id,payload_json FROM ai_results"):
        result = json.loads(row["payload_json"])
        output[row["post_id"]] = [{**claim,
            "cluster_id": key("AI_", [result["model_version"], result["scope_id"], claim["cluster_id"]]),
            "claim_id": key("C_", [result["model_version"], result["scope_id"], claim["claim_id"]]),
            "model_version": result["model_version"], "scope_id": result["scope_id"],
            "post_ids": [row["post_id"]]} for claim in result.get("claims", [])]
    return output


def ai_clusters_by_post(connection):
    """Keep received/unassigned distinct without manufacturing claims or stance."""
    from engine import key
    output = {}
    for row in connection.execute("SELECT post_id,payload_json FROM ai_results"):
        result = json.loads(row["payload_json"])
        if "cluster_id" in result:
            source_ids = [result["cluster_id"]] if result["cluster_id"] is not None else []
        else:
            source_ids = sorted({c["cluster_id"] for c in result.get("claims", [])})
        output[row["post_id"]] = [{"cluster_id": key("AI_", [result["model_version"], result["scope_id"], cid]),
            "source_cluster_id": cid, "label": result.get("cluster_label") or f"내용 군집 · {cid}",
            "membership_strength": result.get("membership_strength"), "post_ids": [row["post_id"]],
            "model_version": result["model_version"], "scope_id": result["scope_id"]} for cid in source_ids]
    return output


def enrich_signal(signal, ai_by_post, clusters_by_post=None):
    clusters_by_post = clusters_by_post or {}
    evidence = set(signal["evidence_post_ids"])
    received = evidence & ai_by_post.keys()
    grouped = {}
    for pid in sorted(received):
        for claim in ai_by_post[pid]:
            identity = (claim["cluster_id"], claim["claim_id"], claim["stance"])
            if identity not in grouped:
                grouped[identity] = {k: v for k, v in claim.items() if k not in ("post_ids", "evidence_text", "confidence")}
                grouped[identity].update(post_ids=[], evidence=[], confidence=None)
            grouped[identity]["post_ids"].append(pid)
            grouped[identity]["evidence"].append({"post_id": pid, "evidence_text": claim["evidence_text"], "confidence": claim["confidence"]})
    clusters = {}
    for pid in sorted(received):
        for cluster in clusters_by_post.get(pid, []):
            item = clusters.setdefault(cluster["cluster_id"], {**cluster, "post_ids": [], "membership_strength": None})
            item["post_ids"].append(pid)
    claims = list(grouped.values())
    counts = Counter(claim["stance"] for pid in received for claim in ai_by_post[pid])
    return {**signal, "fusion_status": "pending" if not received else "enriched" if received == evidence else "partial",
            "cluster_ids": sorted({c["cluster_id"] for c in claims} | set(clusters)),
            "ai_context": {"analyzed_post_count": len(received), "total_post_count": len(evidence),
                           "claims": claims, "stance_counts": dict(counts), "clusters": list(clusters.values()),
                           "unassigned_post_count": sum(not clusters_by_post.get(pid) and not ai_by_post[pid] for pid in received)}}


def _aggregate_alerts(signals, previous=()):
    """Greedy complete-link account cores; no hub/transitive merging of unrelated pairs.

    Account-alert bipartite memberships are preserved in each parent's child IDs.
    Every distinct pair in a multi-account core must have a qualifying child signal.
    One-hour maximum span refers to child signals' latest observed episode times.
    """
    from datetime import timedelta
    from engine import key, parse_time
    remaining = {signal["id"]: signal for signal in signals}
    parents = []
    preserved_ids = set()
    previous = sorted(previous, key=lambda item: (item["first_detected_at"], item["id"]))
    while remaining:
        seed = min(remaining.values(), key=lambda s: (-s["network_score"], s["id"]))
        accounts = set(seed["account_ids"])
        selected = {seed["id"]}
        latest = parse_time(seed["last_seen"])
        candidates = {sid: s for sid, s in remaining.items()
                      if abs(parse_time(s["last_seen"]) - latest) <= timedelta(hours=1)}
        pair_map = {frozenset(s["account_ids"]): sid for sid, s in candidates.items()}
        for account in sorted({a for s in candidates.values() for a in s["account_ids"]} - accounts):
            required = [pair_map.get(frozenset((account, member))) for member in accounts]
            if all(required):
                tentative = selected | set(required)
                times = [parse_time(candidates[sid]["last_seen"]) for sid in tentative]
                if max(times) - min(times) <= timedelta(hours=1):
                    accounts.add(account)
                    selected = tentative
        children = [remaining.pop(sid) for sid in sorted(selected)]
        preserved = next((p for p in previous if p["id"] not in preserved_ids and
                          (p["seed_signal_id"] in selected or set(p["account_ids"]) == accounts)), None)
        if preserved:
            preserved_ids.add(preserved["id"])
        seed_id = preserved["seed_signal_id"] if preserved else seed["id"]
        parent_id = preserved["id"] if preserved else key("I_", seed_id)
        evidence = sorted({pid for child in children for pid in child["evidence_post_ids"]})
        parents.append({"id": parent_id, "seed_signal_id": seed_id, "child_alert_ids": sorted(selected),
                        "account_ids": sorted(accounts), "evidence_post_ids": evidence,
                        "first_seen": min(c["first_seen"] for c in children),
                        "last_seen": max(c["last_seen"] for c in children),
                        "network_score": round(sum(c["network_score"] for c in children) / len(children), 2),
                        "score_components": {name: round(sum(c["score_components"][name] for c in children) / len(children), 3)
                            if all(isinstance(c["score_components"].get(name), (int, float)) for c in children) else None
                            for name in {n for c in children for n in c["score_components"]}},
                        "aggregation_basis": "모든 계정 쌍에 반복 행동 근거가 있는 핵심망 · 최근 신호 시각 최대 1시간"})
    return sorted(parents, key=lambda item: (-item["network_score"], item["id"]))


def ai_diffusion_alerts(posts, ai_by_post, as_of, config):
    """Completed-hour volume cues per external proposition/stance, never CIB verdicts."""
    from engine import hour, hourly_diffusion, key
    grouped = defaultdict(dict)
    for post in posts:
        for claim in ai_by_post.get(post["id"], []):
            grouped[(claim["cluster_id"], claim["claim_id"], claim["stance"])][post["id"]] = post
    output = []
    for identity, members in sorted(grouped.items()):
        assignment = {pid: key("AC_", identity) for pid in members}
        alerts, _ = hourly_diffusion(list(members.values()), assignment, hour(as_of), config)
        for alert in alerts:
            alert["cluster_ids"] = [identity[0]]
            alert.update(id=key("VA_", [identity, alert["hour"]]), claim_id=identity[1], stance=identity[2],
                         label="명제별 확산 급증", summary=f"명제·입장별 시간당 게시량 {alert['post_count']}개, 기준 대비 {alert['ratio']:g}배입니다.",
                         reason_labels=["완료된 시간대에서 특정 명제·입장의 게시량 급증"],
                         metrics={"게시물": alert["post_count"], "기준선": alert["baseline_mean"], "증가 배수": alert["ratio"], "시간": alert["hour"]})
            output.append(alert)
    return output


def cluster_diffusion_alerts(posts, clusters_by_post, ai_by_post, as_of, config):
    """Cluster volume only; may include both supporting and refuting posts."""
    from engine import hour, hourly_diffusion, key
    grouped = defaultdict(dict)
    for post in posts:
        if ai_by_post.get(post["id"]):
            continue  # Legacy claim/stance volume is computed separately.
        for cluster in clusters_by_post.get(post["id"], []):
            grouped[cluster["cluster_id"]][post["id"]] = post
    output = []
    for cid, members in sorted(grouped.items()):
        alerts, _ = hourly_diffusion(list(members.values()), {pid: cid for pid in members}, hour(as_of), config)
        for alert in alerts:
            alert.update(id=key("CV_", [cid, alert["hour"]]), label="내용 군집 확산 급증",
                reason_codes=["HOURLY_DIFFUSION_SPIKE", "MULTI_ACCOUNT_SPREAD", "SEMANTIC_CLUSTER_VOLUME", "STANCE_NOT_ANALYZED"],
                summary=f"군집 전체의 시간당 게시물 {alert['post_count']}개, 기준 대비 {alert['ratio']:g}배입니다. 주장·반박 비율은 미분석입니다.",
                reason_labels=["완료된 시간대의 내용 군집 게시량 급증 · 입장 미분석"],
                metrics={"게시물": alert["post_count"], "기준선": alert["baseline_mean"], "증가 배수": alert["ratio"], "시간": alert["hour"]})
            output.append(alert)
    return output
