"""Raw evidence and independent behavior/AI views within the dashboard transaction."""
from collections import Counter, defaultdict
from datetime import timedelta
import json

from engine import hour, key, parse_time, stamp
from fusion import ai_claims_by_post, ai_clusters_by_post
from playbooks import language, extend_snapshot as extend_playbook


def extend_snapshot(connection, metadata, data, urls_by_post, observed_now=None):
    as_of = parse_time(metadata.get("behavior_as_of", metadata["last_analysis_at"]))
    maximum = int(metadata.get("behavior_seq", "0"))
    all_rows = list(connection.execute("SELECT * FROM posts ORDER BY seq"))
    visible = [p for p in all_rows if p["seq"] <= maximum and parse_time(p["created_at"]) <= as_of]
    no_ai = metadata.get('pipeline_mode') == 'no-ai'
    ai = {} if no_ai else ai_claims_by_post(connection)
    ai_clusters = {} if no_ai else ai_clusters_by_post(connection)
    posts = {}
    for row in visible:
        raw = json.loads(row["raw_json"])
        claims = ai.get(row["id"], [])
        posts[row["id"]] = {"id": row["id"], "account_id": row["account_id"], "created_at": row["created_at"],
            "text": row["text"], "urls": urls_by_post[row["id"]], "narrative_id": claims[0]["claim_id"] if claims else "",
            "stance_hint": 'unmarked' if no_ai else "pending" if row["id"] not in ai else "external_ai",
            "language": language(raw)[0], "relations": raw.get("relations", []) or [],
            "ai_status": 'disabled' if no_ai else "received" if row["id"] in ai else "pending", "ai_claims": claims, "ai_clusters": ai_clusters.get(row["id"], [])}
    signals = {row["id"]: json.loads(row["payload_json"]) for row in connection.execute("SELECT * FROM behavior_signals WHERE active=1")}
    network = json.loads(metadata.get("behavior_network", '{"nodes":[],"edges":[]}'))

    def make_case(identity, members, title, summary, source, alerts=(), parent=None):
        members = sorted(members, key=lambda p: (p["created_at"], p["id"]))
        ids = {p["id"] for p in members}
        actors = {p["account_id"] for p in members}
        counts, hourly_actors = Counter(), defaultdict(set)
        for post in members:
            bucket = hour(parse_time(post["created_at"]))
            counts[bucket] += 1
            hourly_actors[bucket].add(post["account_id"])
        timeline = []
        if counts:
            current = min(counts)
            while current <= max(counts):
                baseline = sum(counts[current - timedelta(hours=i)] for i in range(1, 7)) / 6 if current >= min(counts) + timedelta(hours=6) else None
                timeline.append({"time": stamp(current), "count": counts[current], "account_count": len(hourly_actors[current]),
                                 "baseline": baseline, "partial": current >= hour(as_of)})
                current += timedelta(hours=1)
        grouped = {}
        for post in members:
            for claim in post["ai_claims"]:
                identity_claim = (claim["claim_id"], claim["stance"])
                group = grouped.setdefault(identity_claim, {"id": key("NC_", identity_claim), "claim_id": claim["claim_id"],
                    "label": claim["claim_text"], "stance_hint": claim["stance"], "post_count": 0, "evidence_post_ids": []})
                group["evidence_post_ids"].append(post["id"])
                group["post_count"] += 1
            for cluster in post["ai_clusters"]:
                if any(c["cluster_id"] == cluster["cluster_id"] for c in post["ai_claims"]):
                    continue
                identity_cluster = (cluster["cluster_id"], "cluster")
                group = grouped.setdefault(identity_cluster, {"id": cluster["cluster_id"], "kind": "cluster",
                    "label": cluster["label"], "stance_hint": None, "post_count": 0, "evidence_post_ids": []})
                group["evidence_post_ids"].append(post["id"])
                group["post_count"] += 1
        child_ids = {a["id"] for a in alerts}
        edges = [edge for edge in network["edges"] if edge["source"] in actors and edge["target"] in actors
                 and set(edge["evidence_post_ids"]) <= ids and (not edge["alert_ids"] or set(edge["alert_ids"]) & child_ids)]
        return {"id": identity, "source": source, "title": title, "summary": summary,
            "first_seen": members[0]["created_at"], "last_seen": members[-1]["created_at"],
            "post_count": len(members), "account_count": len(actors), "alert_count": len(alerts),
            "languages": sorted({p["language"] for p in members if p["language"]}),
            "priority": "review_high" if any(a["priority"] == "review_high" for a in alerts) else "review_medium" if alerts else "none",
            "basis": [parent["aggregation_basis"]] if parent else ["외부 AI의 의미 기반 군집 · 주장/반박 입장 미분석"],
            "posts": members, "alerts": list(alerts), "hourly": timeline, "narratives": list(grouped.values()),
            "network": {"nodes": [{"id": a, "label": a, "post_count": sum(p["account_id"] == a for p in members),
                                      "stance_hints": []} for a in sorted(actors)], "edges": edges}}

    # Received AI results replace local preview membership for the same posts.
    # Local cases stay explicitly labeled; they do not represent external AI.
    local_cases = []
    for case in data["cases"]:
        if no_ai:
            continue
        if set(p["id"] for p in case["posts"]) & ai.keys():
            continue
        case["source"] = "local_preview"
        local_cases.append(case)
    cluster_members = defaultdict(set)
    for pid, clusters in ai_clusters.items():
        if pid in posts:
            for cluster in clusters:
                cluster_members[cluster["cluster_id"]].add(pid)
    ai_cases = []
    for cluster_id, ids in sorted(cluster_members.items()):
        members = [{**posts[pid], "ai_claims": [c for c in ai[pid] if c["cluster_id"] == cluster_id],
                    "ai_clusters": [c for c in ai_clusters[pid] if c["cluster_id"] == cluster_id]} for pid in ids]
        claims = [claim for pid in ids for claim in ai[pid] if claim["cluster_id"] == cluster_id]
        related = [s for s in signals.values() if cluster_id in s["cluster_ids"]]
        # Preserve complete global evidence in investigations; never relabel it as local.
        local_signals = [s for s in related if set(s["evidence_post_ids"]) <= ids]
        local_signals += [s for s in json.loads(metadata.get("ai_volume_signals", "[]"))
                          if cluster_id in s["cluster_ids"] and set(s["evidence_post_ids"]) <= ids]
        title = claims[0]["claim_text"][:100] if claims else members[0]["ai_clusters"][0]["label"]
        summary = f"AI 의미 군집 · 게시물 {len(members)}개. 입장과 사실 여부는 별도 검토가 필요합니다."
        ai_cases.append(make_case(cluster_id, members, title, summary, "ai", local_signals))
    resource_cases = []
    resource_groups = json.loads(metadata.get('resource_groups', '[]')) if no_ai else []
    from resource_alerts import resource_bursts
    early_cutoff = max(as_of, observed_now or as_of) if metadata.get('source_clock_mode') == 'live' else as_of
    early_alerts = resource_bursts(resource_groups, visible, early_cutoff,
                                 json.loads(metadata.get('resource_alerts', '[]'))) if no_ai else []
    early_by_group = defaultdict(list)
    for alert in early_alerts:
        early_by_group[alert['group_id']].append(alert)
    for group in resource_groups:
        members = [posts[pid] for pid in group['evidence_post_ids'] if pid in posts]
        if len(members) < 2:
            continue
        ids = {p['id'] for p in members}
        alerts = [s for s in signals.values() if set(s['evidence_post_ids']) <= ids]
        for original_alert in early_by_group[group['id']]:
            if not set(original_alert['evidence_post_ids']) <= ids:
                continue
            alerts.append(original_alert)
        case = make_case(group['id'], members, group['title'],
                         '공유 자료·원본 참조·동일 문구의 관측 연결입니다. 같은 주장·입장·공작을 뜻하지 않습니다.', 'resource', alerts)
        case['grouping'] = group
        case['basis'] = [group['kind'], '공개 원문 참조·동일 자료의 관측 연결',
                         '연결 근거를 하위 자료로 보존 · 같은 사건·입장·의도 확정 아님']
        case['narratives'] = [{'id': child['id'], 'kind': 'resource', 'label': child['title'],
                              'stance_hint': None, 'post_count': len(ids & set(child['evidence_post_ids'])),
                              'evidence_post_ids': sorted(ids & set(child['evidence_post_ids']))}
                             for child in (group.get('child_groups') or [group]) if ids & set(child['evidence_post_ids'])]
        resource_cases.append(case)
    resource_cases.sort(key=lambda c: (-c['alert_count'], -c['post_count'], c['id']))
    issue_cases = []
    if no_ai:
        from issues import issue_groups
        topics = issue_groups(visible, resource_groups)
        all_alerts = {a['id']: a for a in [*signals.values(), *early_alerts]}
        for topic in topics:
            ids = set(topic['evidence_post_ids']) & posts.keys()
            if not ids:
                continue
            # An issue is a navigation view, never a new detection population.
            alerts = [{**a, 'cross_issue': not set(a['evidence_post_ids']) <= ids,
                       'evidence_posts': [posts[pid] for pid in a['evidence_post_ids'] if pid in posts]}
                      for a in all_alerts.values() if ids & set(a['evidence_post_ids'])]
            members = [{**posts[pid], 'issue_matches': [m for m in topic['issue_matches'] if m['post_id'] == pid]}
                       for pid in ids]
            case = make_case(topic['id'], members, topic['title'],
                             '규칙 기반 이슈 분류 · 주장·질문·반박·공식 확인을 함께 조회합니다. 입장·허위성은 미분석입니다.',
                             'issue', alerts)
            case['analysis_mode'] = 'no-ai'
            case['grouping'] = topic
            case['basis'] = ['공개 본문의 이슈 어휘 또는 관측 원본 참조',
                             '상위 이슈 분류 · 동일 사건·주장·공작 확정 아님',
                             '복수 이슈 소속 가능 · 전체 게시물·경보 수는 ID 중복 제거']
            case['narratives'] = [{'id': c['id'], 'kind': 'resource', 'label': c['title'],
                                  'stance_hint': None, 'post_count': len(ids & set(c['evidence_post_ids'])),
                                  'evidence_post_ids': sorted(ids & set(c['evidence_post_ids']))}
                                 for c in topic['child_groups'] if ids & set(c['evidence_post_ids'])]
            issue_cases.append(case)
        issue_cases.sort(key=lambda c: (-c['alert_count'], -c['post_count'], c['id']))
        issue_linked = {p['id'] for c in issue_cases for p in c['posts']}
        assigned_alerts = {a['id'] for c in issue_cases for a in c['alerts']}
        data['unassigned_alert_cases'] = []
        for original in resource_cases:
            alerts = [a for a in original['alerts'] if a['id'] not in assigned_alerts]
            if alerts:
                data['unassigned_alert_cases'].append({**original, 'alerts': alerts, 'alert_count': len(alerts)})
        data['issue_cases'] = issue_cases
        data['issue_unclassified_posts'] = [p for pid, p in posts.items() if pid not in issue_linked]
    investigations = []
    for row in connection.execute("SELECT * FROM investigations WHERE active=1 ORDER BY id"):
        parent = json.loads(row["payload_json"])
        ids = set(parent["evidence_post_ids"]) & posts.keys()
        members = [posts[pid] for pid in ids]
        if not members:
            continue
        children = [signals[sid] for sid in parent["child_alert_ids"] if sid in signals]
        case = make_case(parent["id"], members, f"반복 행동 조사망 · 계정 {len(parent['account_ids'])}개",
            f"계정 간 반복 동시 행동 신호 {len(children)}개를 하나의 조사망으로 묶었습니다. 조정·진정성·의도는 미확인입니다.",
            "behavior", children, parent)
        case.update({name: parent[name] for name in ("child_alert_ids", "fusion_status", "network_score", "score_components")})
        case["related_case_ids"] = sorted({c["cluster_id"] for pid in ids for c in ai_clusters.get(pid, [])})
        case["ai_context"] = parent["ai_context"]
        if no_ai:
            case['analysis_mode'] = 'no-ai'
            case['related_case_ids'] = [c['id'] for c in resource_cases if ids & {p['id'] for p in c['posts']}]
            nested = {}
            for related in resource_cases:
                if related['id'] not in case['related_case_ids']:
                    continue
                for narrative in related['narratives']:
                    subset = ids & set(narrative['evidence_post_ids'])
                    if subset:
                        item = nested.setdefault(narrative['id'], {**narrative, 'evidence_post_ids': []})
                        item['evidence_post_ids'] = sorted(set(item['evidence_post_ids']) | subset)
                        item['post_count'] = len(item['evidence_post_ids'])
            case['narratives'] = list(nested.values())
        investigations.append(case)
    investigations.sort(key=lambda c: (-c["network_score"], c["id"]))
    linked = {p["id"] for case in local_cases + ai_cases + resource_cases for p in case["posts"]}
    data.update({"cases": local_cases + ai_cases + resource_cases, "investigations": investigations,
        "unlinked_posts": [p for pid, p in posts.items() if pid not in linked], "global_signals_count": len(signals),
        'early_alerts_count': len(early_alerts),
        "pipeline": {"mode": metadata.get("pipeline_mode", "local-preview"),
                     "raw_post_count": len(all_rows), "raw_account_count": len({p["account_id"] for p in all_rows}),
                     "behavior_post_count": len(visible), "behavior_pending_count": len(all_rows) - len(visible),
                     "ai_received_count": len(ai), "ai_pending_count": 0 if no_ai else len(all_rows) - len(ai),
                     "resource_group_count": len(resource_cases),
                     "issue_count": len(issue_cases),
                     "ai_status": 'disabled' if no_ai else "waiting" if not ai else "ready" if len(ai) == len(all_rows) else "partial",
                     "behavior_as_of": stamp(as_of), "behavior_window_hours": 24, "score_calibrated": False}})
    if metadata.get("pipeline_mode") in ('external-ai', 'no-ai'):
        data["summary"] = {"case_count": len(data["cases"]), "post_count": len(visible),
                           "account_count": len({p["account_id"] for p in visible}),
                           "alert_count": len(investigations) + len(early_alerts), "pending_post_count": len(all_rows) - len(visible)}
    extend_playbook(connection, metadata, data)
    if no_ai:
        post_index = posts
        plans = {m['id']: m for m in data.get('scenario_candidates', [])}
        for plan in plans.values():
            plan['evidence_posts'] = [post_index[pid] for pid in plan['evidence_post_ids'] if pid in post_index]
        for case in issue_cases:
            ids = {p['id'] for p in case['posts']}
            case['response_plans'] = [dict(m, cross_case=not set(m['evidence_post_ids']) <= ids) for m in plans.values() if set(m['evidence_post_ids']) & ids]
        unclassified_ids = {p['id'] for p in data.get('issue_unclassified_posts', [])}
        data['playbook_raw_matches'] = [dict(m, cross_case=not set(m['evidence_post_ids']) <= unclassified_ids) for m in plans.values() if set(m['evidence_post_ids']) & unclassified_ids]
    data["limitations"] = ["경보·조사망은 CIB·봇·허위성·국가 배후의 확정 판정이 아닙니다.",
        "행동 점수는 시간 근접도·독립 반복·자료 다양성과 관측 참조를 조합한 미보정 검토 지표입니다.",
        "참조 그래프는 수집된 원본 ID만 반영하며 외부 간선의 부재는 닫힌 조직망의 증거가 아닙니다.",
        "일반 속보의 단발 공유는 강한 반복 행동 경보 조건을 충족하지 않습니다. 반복적인 정상 협업은 여전히 오탐 후보입니다.",
        "AI는 의미 군집만 제공합니다. 같은 군집 안에 주장·반박·질문이 섞일 수 있으며 입장·허위성은 미분석입니다.",
        "실제 VEIL API·딥페이크 판별은 미연결입니다. 최초 관측은 최초 유포가 아닙니다."]
    if no_ai:
        data['data_mode'] = 'rule-based'
        data['limitations'][4] = 'AI 미사용. 자료 묶음은 의미·입장 분류가 아닙니다. 번역·의역·URL 없는 다른 표현은 놓칠 수 있습니다.'
        data['limitations'].append('원본 참조는 각 연결 간격 24시간 이내의 관측 원문을 연결합니다. 여러 단계 흐름의 전체 기간은 24시간을 넘을 수 있습니다. 행동 탐지는 별도의 이동 24시간 구간을 사용합니다.')
        data['limitations'].append('조기 주의는 최근 24시간 내 60초 관측창의 12개 게시물·6개 계정·6개 연결 게시물 기준입니다. 미보정 운용값이며 정상 속보·반박 확산도 포함합니다. 반복 행동 경보와 별개입니다.')
        data['limitations'].append('다국어 의미 군집이 필요한 운용표 유형22 자동 연결은 중지됩니다. 유형17 행동·유형30 키워드 후보는 계속 평가합니다.')
        data['limitations'].append('10개 이슈는 사용자가 지정한 공개 어휘 분류입니다. 군집 수를 강제한 의미 분석이 아니며, 미분류·복수 이슈가 존재합니다. 이슈별 합계에는 중복이 있을 수 있습니다. 경보는 원래 자료·행동 근거에서만 생성합니다.')
