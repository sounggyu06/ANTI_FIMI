"""Observed propagation reconstruction for event-scoped ANTI_FIMI cases.

Never infers causal links from chronological order or shared text. The only directed
links are supplied quotes/reposts/replies_to references within the selected case.
"""
from collections import defaultdict, deque
from datetime import datetime

RELATIONS = {"quotes", "reposts", "replies_to"}


def _time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _brief(post):
    return {
        "post_id": post["id"],
        "account_id": post["account_id"],
        "created_at": post["created_at"],
        "text": str(post.get("text") or "")[:180],
    }


def analyze_source_trace(members, global_ids=None, max_nodes=55, max_edges=110):
    """Return bounded, evidence-only trace information for one case.

    `global_ids` is the set of collected post IDs across the analysis snapshot.
    Out-of-case references remain marked; no unobserved edge is invented.
    """
    lookup = {p["id"]: p for p in members if isinstance(p, dict) and p.get("id") and p.get("account_id")}
    global_ids = set(global_ids or lookup)
    chronological = sorted(lookup.values(), key=lambda p: (p.get("created_at") or "", p["id"]))
    if not chronological:
        return {
            "earliest_observed": None, "leading_root": None, "root_candidates": [],
            "nodes": [], "edges": [], "linked_post_count": 0, "total_posts": 0,
            "observed_edge_count": 0, "observed_max_depth": 0,
            "outside_scope_references": 0, "unavailable_references": 0,
            "time_inconsistent_references": 0,
            "claim": "empty", "limitations": "분석할 게시물이 없습니다.",
        }

    edges = []
    children = defaultdict(set)
    indegree = defaultdict(int)
    refs_external = defaultdict(list)
    outside_count = unknown_count = conflicting_count = 0
    seen = set()
    for post in chronological:
        relations = post.get("relations") or []
        if not isinstance(relations, list):
            continue
        for rel in relations:
            if not isinstance(rel, dict) or rel.get("type") not in RELATIONS:
                continue
            parent_id = rel.get("target_post_id")
            if not isinstance(parent_id, str) or not parent_id or parent_id == post["id"]:
                continue
            if parent_id not in lookup:
                if parent_id in global_ids:
                    outside_count += 1
                    refs_external[post["id"]].append("outside_case")
                else:
                    unknown_count += 1
                    refs_external[post["id"]].append("not_collected")
                continue
            parent = lookup[parent_id]
            pt, ct = _time(parent.get("created_at")), _time(post.get("created_at"))
            if pt and ct and pt > ct:
                conflicting_count += 1
                continue
            k = (parent_id, post["id"], rel["type"])
            if k in seen:
                continue
            seen.add(k)
            edges.append({"source": parent_id, "target": post["id"], "kind": rel["type"]})
            if post["id"] not in children[parent_id]:
                children[parent_id].add(post["id"])
                indegree[post["id"]] += 1

    # Roots of observed reference graph; isolated posts are not reference-chain roots.
    connected = {e["source"] for e in edges} | {e["target"] for e in edges}
    roots = [pid for pid in connected if not indegree[pid]]
    roots.sort(key=lambda pid: (lookup[pid]["created_at"], pid))

    def discover(root):
        visited = {root}
        depth = {root: 0}
        queue = deque([root])
        while queue:
            src = queue.popleft()
            for dst in sorted(children.get(src, ())):
                if dst not in visited:
                    visited.add(dst)
                    depth[dst] = depth[src] + 1
                    queue.append(dst)
        return visited, depth

    scored = []
    for pid in roots:
        reachable, dmap = discover(pid)
        scored.append((pid, reachable, dmap))
    scored.sort(key=lambda item: (-len(item[1]), lookup[item[0]]["created_at"], item[0]))
    best = scored[0] if scored else None
    top_roots = []
    for pid, reachable, dmap in scored[:8]:
        top_roots.append({
            **_brief(lookup[pid]),
            "reachable_posts": len(reachable),
            "observed_depth": max(dmap.values(), default=0),
            "upstream_outside_scope": "outside_case" in refs_external[pid],
            "upstream_not_collected": "not_collected" in refs_external[pid],
        })

    graph_nodes = []
    graph_edges = []
    max_depth = 0
    if best:
        _, reachable, depths = best
        selected = sorted(reachable, key=lambda pid: (depths[pid], lookup[pid]["created_at"], pid))[:max_nodes]
        selected_ids = set(selected)
        for pid in selected:
            graph_nodes.append({**_brief(lookup[pid]), "depth": depths[pid]})
        graph_edges = sorted((e for e in edges if e["source"] in selected_ids and e["target"] in selected_ids),
                             key=lambda e: (lookup[e["source"]]["created_at"], lookup[e["target"]]["created_at"], e["source"], e["target"]))[:max_edges]
        max_depth = max(depths.values(), default=0)

    return {
        "earliest_observed": _brief(chronological[0]),
        "leading_root": top_roots[0] if top_roots else None,
        "root_candidates": top_roots,
        "nodes": graph_nodes,
        "edges": graph_edges,
        "linked_post_count": len(connected),
        "total_posts": len(chronological),
        "observed_edge_count": len(edges),
        "observed_max_depth": max_depth,
        "outside_scope_references": outside_count,
        "unavailable_references": unknown_count,
        "time_inconsistent_references": conflicting_count,
        "claim": "observed_reference_chain" if edges else "chronological_only",
        "limitations": (
            "최초 관측 게시물은 실제 최초 유포자라는 뜻이 아닙니다. "
            "방향 연결은 수집된 명시적 인용·재공유·답글 참조만 사용합니다. "
            "이슈 밖 게시물 또는 미수집 원본이 있으면 상위 출처를 확정할 수 없습니다."
        ),
    }
