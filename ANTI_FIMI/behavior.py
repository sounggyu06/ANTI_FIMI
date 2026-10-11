"""Text-independent public co-action signals; scores are uncalibrated review aids."""
from collections import Counter, defaultdict
from datetime import timedelta
import json
import math
import statistics


PARAMETERS = {
    "window_seconds": 60,
    "lookback_hours": 24,
    "min_independent_episodes": 3,
    "min_distinct_resources": 2,
    "high_review_score": 65,
    "score_calibration": "heuristic, uncalibrated; not CIB or bot probability",
    "reference_direction": "acting account -> referenced post author",
    "graph_coverage": "observed references only; absent external edges do not establish closure",
}
RELATIONS = ("quotes", "reposts", "replies_to")
REASONS = {
    "REPEATED_TEMPORAL_COACTION": "독립된 시간대에 같은 계정들이 반복 공동 행동",
    "CROSS_RESOURCE_COORDINATION": "서로 다른 URL·원본 게시물에서 반복 관측",
    "POPULARITY_ACTIVITY_ADJUSTED": "자료 인기도와 계정 활동량으로 점수 보정",
    "OBSERVED_RECIPROCAL_REFERENCES": "수집된 원본 참조에서 양방향 상호작용 관측",
}


def analyze_behavior(posts, url_rows, as_of):
    """Analyze IDs, timestamps, normalized URLs and raw relation IDs only.

    Inputs may be sqlite3.Row objects or dictionaries. Text, embeddings, stance,
    scenario labels and AI clusters are deliberately never accessed. Reanalysis
    of the same IDs at the same cutoff is deterministic, including late arrivals.
    """
    from engine import hour, key, parse_time, stamp

    posts = list(posts)
    cutoff = parse_time(as_of) if isinstance(as_of, str) else as_of
    lower = cutoff - timedelta(hours=PARAMETERS["lookback_hours"])
    rows = {}
    for post in posts:
        created = parse_time(post["created_at"])
        if lower <= created <= cutoff:
            rows[post["id"]] = {"id": post["id"], "account_id": post["account_id"],
                                 "time": created, "raw_json": post["raw_json"]}
    ordered = sorted(rows.values(), key=lambda p: (p["time"], p["id"]))
    resources = defaultdict(dict)
    for row in url_rows:
        if row["post_id"] in rows:
            resources["url:" + row["url"]][row["post_id"]] = rows[row["post_id"]]
    observed, unresolved = defaultdict(list), Counter()
    # Originals outside the scoring window can still resolve observed authors.
    originals = {p["id"]: p for p in posts}
    for post in ordered:
        raw = json.loads(post["raw_json"])
        relations = raw.get("relations", []) or []
        if not isinstance(relations, list):
            continue
        seen = set()
        for relation in relations:
            if not isinstance(relation, dict) or relation.get("type") not in RELATIONS:
                continue
            target = relation.get("target_post_id")
            if not isinstance(target, str) or not target or target == post['id']:
                continue
            original = originals.get(target)
            if original is not None and parse_time(original['created_at']) > post['time']:
                continue
            kind = relation["type"]
            if (kind, target) in seen:
                continue
            seen.add((kind, target))
            resources["post:" + target][post["id"]] = post
            if original is None:
                unresolved[post["account_id"]] += 1
            elif original["account_id"] != post["account_id"]:
                observed[(post["account_id"], original["account_id"], kind)].append(
                    (post["id"], target))

    window = timedelta(seconds=PARAMETERS["window_seconds"])
    popularity, pair_episodes = {}, defaultdict(list)
    for resource, shares_by_id in sorted(resources.items()):
        shares = sorted(shares_by_id.values(), key=lambda p: (p["time"], p["id"]))
        popularity[resource] = len({p["account_id"] for p in shares})
        latest, candidates = {}, defaultdict(list)
        for right in shares:
            latest = {account: post for account, post in latest.items()
                      if right["time"] - post["time"] <= window}
            for account, left in sorted(latest.items()):
                if account == right["account_id"]:
                    continue
                pair = tuple(sorted((account, right["account_id"])))
                candidates[pair].append({"start": left["time"], "end": right["time"],
                                         "post_ids": {left["id"], right["id"]},
                                         "lags": [(right["time"] - left["time"]).total_seconds()],
                                         "resources": {resource}})
            latest[right["account_id"]] = right
        for pair, matches in candidates.items():
            # Continuous activity is one episode even when it spans many minutes.
            pair_episodes[pair].extend(_collapse(matches, window))

    counts = Counter(p["account_id"] for p in ordered)
    directed = Counter()
    for (source, target, _), evidence in observed.items():
        directed[(source, target)] += len(evidence)
    signals = []
    inferred_edges = []
    for pair, matches in sorted(pair_episodes.items()):
        # Three URLs shared during one burst must not count as three recurrences.
        episodes = _collapse(matches, window)
        distinct = {resource for episode in episodes for resource in episode["resources"]}
        if len(episodes) < PARAMETERS["min_independent_episodes"] or len(distinct) < PARAMETERS["min_distinct_resources"]:
            continue
        evidence = sorted({pid for episode in episodes for pid in episode["post_ids"]})
        median_lag = statistics.median(lag for episode in episodes for lag in episode["lags"])
        timing = 1 / (1 + median_lag / 5)
        recurrence = 1 - math.exp(-(len(episodes) - 1) / 3)
        cross_resource = min(1, math.log2(len(distinct)) / 3)
        popular_damping = statistics.mean(1 / math.sqrt(max(1, popularity[r] / 2)) for r in distinct)
        activity_coverage = len(evidence) / sum(counts[a] for a in pair)
        activity_damping = math.sqrt(activity_coverage)
        internal = directed[(pair[0], pair[1])] + directed[(pair[1], pair[0])]
        outgoing = sum(n for (source, _), n in directed.items() if source in pair)
        reciprocal = 1.0 if directed[(pair[0], pair[1])] and directed[(pair[1], pair[0])] else 0.0
        internal_fraction = internal / outgoing if outgoing else 0.0
        unresolved_count = sum(unresolved[a] for a in pair)
        resolved_fraction = outgoing / (outgoing + unresolved_count) if outgoing + unresolved_count else 0.0
        graph_support = reciprocal * internal_fraction * resolved_fraction * min(1, internal / 4)
        strength = .40 * timing + .35 * recurrence + .25 * cross_resource
        score = round(min(100, 100 * strength * popular_damping * activity_damping + 10 * graph_support), 2)
        components = {"temporal_tightness": round(timing, 4), "recurrence": round(recurrence, 4),
                      "resource_diversity": round(cross_resource, 4),
                      "popularity_damping": round(popular_damping, 4),
                      "activity_damping": round(activity_damping, 4),
                      "observed_reciprocity": reciprocal,
                      "observed_internal_fraction": round(internal_fraction, 4),
                      "reference_resolution_fraction": round(resolved_fraction, 4),
                      "graph_support": round(graph_support, 4)}
        reason_codes = ["REPEATED_TEMPORAL_COACTION", "CROSS_RESOURCE_COORDINATION", "POPULARITY_ACTIVITY_ADJUSTED"]
        if reciprocal:
            reason_codes.append("OBSERVED_RECIPROCAL_REFERENCES")
        latest_end = max(e["end"] for e in episodes)
        alert_id = key("B_", ["behavior_coordination", pair, stamp(hour(latest_end))])
        public_episodes = []
        for episode in episodes:
            related = sorted(episode["resources"])
            item = {"start": stamp(episode["start"]), "end": stamp(episode["end"]),
                    "resource": related[0], "resources": related, "post_ids": sorted(episode["post_ids"])}
            if len(related) == 1 and related[0].startswith("url:"):
                item["url"] = related[0][4:]
            public_episodes.append(item)
        signals.append({"id": alert_id, "kind": "behavior_coordination", "label": "반복 행동 연관성",
                        "priority": "review_high" if score >= PARAMETERS["high_review_score"] else "review_medium",
                        "summary": f"계정 2개가 독립된 {len(episodes)}개 시간대에 {len(distinct)}개 자료를 함께 공유했습니다. 조정 여부 검토가 필요합니다.",
                        "reason_codes": reason_codes, "reason_labels": [REASONS[r] for r in reason_codes],
                        "evidence_post_ids": evidence, "account_ids": list(pair),
                        "metrics": {"independent_episodes": len(episodes), "distinct_resources": len(distinct),
                                    "median_timing_lag_seconds": round(median_lag, 3),
                                    "observed_internal_references": internal, "unresolved_references": unresolved_count,
                                    "network_score": score},
                        "first_seen": stamp(min(e["start"] for e in episodes)), "last_seen": stamp(latest_end),
                        "network_score": score, "score_components": components, "episodes": public_episodes,
                        "fusion_status": "pending", "cluster_ids": []})
        inferred_edges.append({"id": "edge:" + alert_id, "source": pair[0], "target": pair[1],
                               "kind": "co_share", "evidence_post_ids": evidence, "alert_ids": [alert_id],
                               "weight": len(episodes)})

    edges = []
    for (source, target, kind), evidence in sorted(observed.items()):
        edges.append({"id": key("edge:", ["observed", source, target, kind]), "source": source,
                      "target": target, "kind": kind,
                      "evidence_post_ids": sorted({pid for item in evidence for pid in item}),
                      "alert_ids": [], "weight": len(evidence)})
    edges += inferred_edges
    node_ids = set(counts) | {edge["target"] for edge in edges}
    return {"signals": signals,
            "network": {"nodes": [{"id": account, "label": account, "post_count": counts[account], "stance_hints": []}
                                   for account in sorted(node_ids)], "edges": edges},
            "parameters": dict(PARAMETERS)}


def _collapse(matches, window):
    """Merge connected windows, including cross-resource bursts, without label data."""
    episodes = []
    for match in sorted(matches, key=lambda m: (m["start"], m["end"], sorted(m["resources"]), sorted(m["post_ids"]))):
        if not episodes or match["start"] > episodes[-1]["end"] + window:
            episodes.append({"start": match["start"], "end": match["end"],
                             "post_ids": set(match["post_ids"]), "lags": list(match["lags"]),
                             "resources": set(match["resources"])})
        else:
            current = episodes[-1]
            current["end"] = max(current["end"], match["end"])
            current["post_ids"].update(match["post_ids"])
            current["lags"].extend(match["lags"])
            current["resources"].update(match["resources"])
    return episodes
