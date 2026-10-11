"""Provisional discussion groups; account identity and scenario labels are never grouping cues."""
import json
from datetime import timedelta
from urllib.parse import urlsplit

EVENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
 id TEXT PRIMARY KEY, seed_post_id TEXT NOT NULL REFERENCES posts(id),
 title TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, basis_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event_memberships(
 post_id TEXT PRIMARY KEY REFERENCES posts(id), event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 basis TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS event_members_lookup ON event_memberships(event_id);
"""


def group_events(posts, urls_by_post, similarity=0.68, max_span_hours=72):
    # Imports are deferred because Engine imports this module for its schema.
    from engine import cosine, key, parse_time, unit

    events, membership, by_post = [], {}, {}
    span = timedelta(hours=max_span_hours)
    incoming_refs = {}
    for post in posts:
        for relation in json.loads(post["raw_json"]).get("relations", []) or []:
            if relation.get("type") in ("quotes", "reposts", "replies_to"):
                incoming_refs.setdefault(relation["target_post_id"], set()).add(post["id"])
    for post in posts:
        vector = json.loads(post["embedding_json"])
        created = parse_time(post["created_at"])
        raw = json.loads(post["raw_json"])
        urls = {u for u in urls_by_post.get(post["id"], []) if urlsplit(u).path not in ("", "/")}
        refs = {r.get("target_post_id") for r in raw.get("relations", []) or []
                if isinstance(r, dict) and r.get("type") in ("quotes", "reposts", "replies_to")}
        related_posts = refs | incoming_refs.get(post["id"], set())
        for target in refs:
            related_posts |= incoming_refs.get(target, set())
        candidates = []
        for event in events:
            if max(event["last"], created) - min(event["first"], created) > span:
                continue
            score = min(cosine(vector, event["seed"]), cosine(vector, event["centroid"]))
            referenced = any(by_post.get(pid) == event["id"]
                             for pid in related_posts)
            shared_article = bool(urls & event["anchor_urls"])
            if referenced or shared_article or score >= similarity:
                basis = "OBSERVED_REFERENCE" if referenced else "SHARED_ARTICLE_URL" if shared_article else "TEXT_VECTOR_SIMILARITY"
                candidates.append(((3 if referenced else 2 if shared_article else 1, score, event["id"]), event, basis))
        if candidates:
            _, chosen, basis = max(candidates, key=lambda item: item[0])
            # URL-only/reference attachments do not change the semantic anchor or introduce URL chaining.
            if min(cosine(vector, chosen["seed"]), cosine(vector, chosen["centroid"])) >= similarity:
                chosen["sum"] = [a + b for a, b in zip(chosen["sum"], vector)]
                chosen["centroid"] = unit(chosen["sum"])
                chosen["anchor_urls"].update(urls)
            chosen["first"], chosen["last"] = min(chosen["first"], created), max(chosen["last"], created)
        else:
            chosen = {"id": key("E_", post["id"]), "seed_post_id": post["id"],
                      "title": post["text"].strip().replace("\n", " ")[:85] or "원문 확인이 필요한 사건 후보",
                      "first": created, "last": created, "seed": vector, "centroid": vector[:],
                      "sum": vector[:], "anchor_urls": set(urls), "post_ids": [], "basis": set()}
            events.append(chosen)
            basis = "SEED_POST"
        chosen["post_ids"].append(post["id"])
        chosen["basis"].add(basis)
        membership[post["id"]] = (chosen["id"], basis)
        by_post[post["id"]] = chosen["id"]
    return events, membership
