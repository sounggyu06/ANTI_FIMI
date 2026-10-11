"""ANTI_FIMI: evidence-first, provisional public-post pattern detection."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import statistics
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from events import EVENT_SCHEMA, group_events
from fusion import FUSION_SCHEMA

UTC = timezone.utc
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
URL_RE = re.compile(r"https?://[^\s<>\"']+")


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stamp(value):
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_time(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO 8601 string with timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid ISO 8601 timestamp") from exc
    if result.tzinfo is None:
        raise ValueError("timestamp requires timezone; naive local time is ambiguous")
    return result.astimezone(UTC)


def hour(value):
    return value.replace(minute=0, second=0, microsecond=0)


def key(prefix, value):
    return prefix + hashlib.sha256(dumps(value).encode()).hexdigest()[:20]


def canonical_url(value):
    """Keep scheme, path and meaningful query values; never resolve remote URLs."""
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return None
        if parts.username or parts.password:
            return None
        host = parts.hostname.encode("idna").decode().lower()
        if ":" in host:
            host = "[" + host + "]"
        port = parts.port
        if port and (parts.scheme.lower(), port) not in (("http", 80), ("https", 443)):
            host += ":" + str(port)
        params = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                  if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")]
        return urlunsplit((parts.scheme.lower(), host, parts.path or "/", urlencode(params), ""))
    except (ValueError, UnicodeError):
        return None


def stance_hint(text):
    """Conservative discourse hints, NOT truth or claim-target inference."""
    text = text.casefold()
    uncertain = (
        r"\?|？|[\"“”‘’]", r"\b(if|allegedly|rumou?r|claims?|satire|reportedly)\b",
        r"\bnot (false|fake|untrue)\b", r"취소설|소문|풍자|주장|출처|글을 봤|다는 글|했다면|됐다면|확인 중|거짓이 아니",
        r"噂|うわさ|という|据说|傳聞|传闻|谣言|謠言", r"\b(si|rumeur|supuestamente)\b",
    )
    if any(re.search(pattern, text) for pattern in uncertain):
        return "uncertain", "QUESTION_QUOTE_OR_UNCERTAIN_CUE"
    refuting = (
        r"\b(false|fake|debunked|untrue|not true|never cancelled|not cancelled)\b",
        r"거짓|허위|사실이 아니|취소되지 않|취소된 적 없|취소가 아니",
        r"中止されていない|中止されません|虚偽|未取消|没有取消|沒有取消|不实|不實",
        r"\b(faux|falso|desmentido)\b",
    )
    if any(re.search(pattern, text) for pattern in refuting):
        return "refuting", "EXPLICIT_REFUTATION_CUE"
    return "unmarked", "NO_RELIABLE_STANCE_CUE"


def unit(vector):
    result = [float(x) for x in vector]
    norm = math.sqrt(sum(x * x for x in result))
    if not norm or not math.isfinite(norm):
        raise ValueError("embedding must be finite and nonzero")
    return [x / norm for x in result]


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


class LexicalDemoEmbedder:
    """Offline character features. No translation and no semantic-quality claim."""
    identity = "ANTI_FIMI:lexical-demo-v1"

    def encode(self, texts):
        vectors = []
        for text in texts:
            cleaned = re.sub(r"\s+", " ", text.casefold()).strip()
            vector = [0.0] * 256
            for i in range(max(1, len(cleaned) - 2)):
                chunk = cleaned[i:i + 3].encode()
                digest = hashlib.sha256(chunk).digest()
                vector[int.from_bytes(digest[:2], "big") % 256] += 1
            vectors.append(unit(vector))
        return vectors


class SemanticEmbedder:
    def __init__(self, model=MODEL, revision=None):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("Install requirements.txt or explicitly choose --embedder lexical-demo") from exc
        self.model = SentenceTransformer(model, revision=revision, device="cpu", trust_remote_code=False)
        transformer = self.model[0].auto_model
        resolved = getattr(transformer.config, "_commit_hash", None) or revision or "local"
        self.identity = f"sentence-transformers:{model}@{resolved}"

    def encode(self, texts):
        # Chunk long posts instead of silently keeping only the first 128 tokens.
        tokenizer = self.model.tokenizer
        budget = max(8, self.model.max_seq_length - 2)
        chunks, owners = [], []
        for index, text in enumerate(texts):
            ids = tokenizer.encode(text, add_special_tokens=False)
            for start in range(0, max(1, len(ids)), budget):
                chunks.append(tokenizer.decode(ids[start:start + budget], skip_special_tokens=True))
                owners.append(index)
        encoded = self.model.encode(chunks, normalize_embeddings=True, show_progress_bar=False,
                                    batch_size=32, convert_to_numpy=True)
        totals = [[0.0] * len(encoded[0]) for _ in texts]
        for index, vector in zip(owners, encoded):
            totals[index] = [a + float(b) for a, b in zip(totals[index], vector)]
        return [unit(vector) for vector in totals]


@dataclass(frozen=True)
class Config:
    similarity: float = 0.78
    co_window_seconds: int = 120
    co_lookback_hours: int = 24
    min_co_episodes: int = 3
    baseline_hours: int = 6
    min_hour_posts: int = 8
    min_hour_accounts: int = 4
    min_z: float = 3.0
    min_ratio: float = 3.0


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS posts(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
 account_id TEXT NOT NULL, created_at TEXT NOT NULL, collected_at TEXT NOT NULL,
 observed_clock_at TEXT NOT NULL, text TEXT NOT NULL, raw_json TEXT NOT NULL,
 embedding_json TEXT NOT NULL, stance TEXT NOT NULL, stance_reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS post_urls(
 post_id TEXT NOT NULL REFERENCES posts(id), url TEXT NOT NULL,
 PRIMARY KEY(post_id,url));
CREATE INDEX IF NOT EXISTS url_lookup ON post_urls(url);
CREATE INDEX IF NOT EXISTS event_lookup ON posts(created_at);
CREATE TABLE IF NOT EXISTS clusters(
 id TEXT PRIMARY KEY, seed_post_id TEXT NOT NULL REFERENCES posts(id),
 stance TEXT NOT NULL, size INTEGER NOT NULL, centroid_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assignments(
 post_id TEXT PRIMARY KEY REFERENCES posts(id), cluster_id TEXT NOT NULL REFERENCES clusters(id));
CREATE TABLE IF NOT EXISTS hourly(
 cluster_id TEXT NOT NULL REFERENCES clusters(id), hour TEXT NOT NULL,
 post_count INTEGER NOT NULL, account_count INTEGER NOT NULL,
 PRIMARY KEY(cluster_id,hour));
CREATE TABLE IF NOT EXISTS alerts(
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, active INTEGER NOT NULL,
 first_detected_at TEXT NOT NULL, last_evaluated_at TEXT NOT NULL, payload_json TEXT NOT NULL);
"""


def co_sharing(posts, assignment, url_rows, config):
    by_id = {p["id"]: p for p in posts}
    by_url = defaultdict(list)
    for row in url_rows:
        if row["post_id"] in by_id:
            by_url[row["url"]].append(by_id[row["post_id"]])
    pair_events = defaultdict(list)
    window = timedelta(seconds=config.co_window_seconds)
    for url, shares in sorted(by_url.items()):
        shares.sort(key=lambda p: (p["created_at"], p["id"]))
        candidates = defaultdict(list)
        for i, left in enumerate(shares):
            start = parse_time(left["created_at"])
            for right in shares[i + 1:]:
                end = parse_time(right["created_at"])
                if end - start > window:
                    break
                if left["account_id"] != right["account_id"]:
                    pair = tuple(sorted((left["account_id"], right["account_id"])))
                    candidates[pair].append((start, end, sorted((left["id"], right["id"]))))
        for pair, matches in candidates.items():
            last_end = None
            session = None
            for start, end, ids in sorted(matches, key=lambda m: (m[1], m[0], m[2])):
                if last_end is None or start > last_end + window:
                    session = {"start": stamp(start), "end": stamp(end),
                               "url": url, "post_ids": ids}
                    pair_events[pair].append(session)
                else:
                    session["start"] = min(session["start"], stamp(start))
                    session["end"] = stamp(end)
                    session["post_ids"] = sorted(set(session["post_ids"]) | set(ids))
                # Extend on EVERY connected match: continuous activity is one episode.
                last_end = end
    alerts = {}
    for pair, episodes in sorted(pair_events.items()):
        episodes.sort(key=lambda e: (e["end"], e["url"], e["post_ids"]))
        for index, episode in enumerate(episodes):
            endpoint = parse_time(episode["end"])
            lower = endpoint - timedelta(hours=config.co_lookback_hours)
            recent = [e for e in episodes[:index + 1] if parse_time(e["start"]) >= lower]
            url_counts = Counter(e["url"] for e in recent)
            # Require recurrence of one exact URL, not three unrelated links once each.
            repeated_urls = {url for url, count in url_counts.items()
                             if count >= config.min_co_episodes}
            if episode["url"] not in repeated_urls:
                continue
            recent = [e for e in recent if e["url"] in repeated_urls]
            ids = sorted({pid for e in recent for pid in e["post_ids"]})
            alert_id = key("A_", ["co_share", pair, stamp(hour(endpoint))])
            alerts[alert_id] = {
                "id": alert_id, "kind": "repeated_url_coshare", "priority": "review_high",
                "reason_codes": ["REPEATED_URL_COSHARE", "CROSS_ACCOUNT_SYNCHRONY"],
                "evidence_post_ids": ids, "account_ids": list(pair),
                "cluster_ids": sorted({assignment[pid] for pid in ids}),
                "window_end": stamp(endpoint), "episode_count": len(recent), "episodes": recent,
                "interpretation": "Repeated public co-sharing pattern; CIB, intent and attribution unverified.",
            }
    return list(alerts.values())


def hourly_diffusion(posts, assignment, cutoff, config):
    if not posts:
        return [], []
    counts, accounts, ids = Counter(), defaultdict(set), defaultdict(list)
    first = min(hour(parse_time(p["created_at"])) for p in posts)
    for post in posts:
        bucket = (assignment[post["id"]], hour(parse_time(post["created_at"])))
        counts[bucket] += 1
        accounts[bucket].add(post["account_id"])
        ids[bucket].append(post["id"])
    alerts, rows = [], []
    for (cluster_id, bucket), count in sorted(counts.items()):
        rows.append((cluster_id, stamp(bucket), count, len(accounts[(cluster_id, bucket)])))
        if bucket >= cutoff or bucket < first + timedelta(hours=config.baseline_hours):
            continue
        baseline = [counts[(cluster_id, bucket - timedelta(hours=offset))]
                    for offset in range(config.baseline_hours, 0, -1)]
        mean = statistics.mean(baseline)
        sigma = max(1.0, statistics.pstdev(baseline))
        z = (count - mean) / sigma
        ratio = count / max(1.0, mean)
        if (count < config.min_hour_posts or
                len(accounts[(cluster_id, bucket)]) < config.min_hour_accounts or
                z < config.min_z or ratio < config.min_ratio):
            continue
        alert_id = key("A_", ["hourly", cluster_id, stamp(bucket)])
        alerts.append({
            "id": alert_id, "kind": "hourly_diffusion_spike", "priority": "review_medium",
            "reason_codes": ["HOURLY_DIFFUSION_SPIKE", "MULTI_ACCOUNT_SPREAD", "PROVISIONAL_NARRATIVE"],
            "evidence_post_ids": sorted(ids[(cluster_id, bucket)]),
            "account_ids": sorted(accounts[(cluster_id, bucket)]), "cluster_ids": [cluster_id],
            "hour": stamp(bucket), "post_count": count, "baseline_counts": baseline,
            "baseline_mean": mean, "z_score": z, "ratio": ratio,
            "interpretation": "Observed-volume anomaly; coverage completeness and organic causes unverified.",
        })
    return alerts, rows


class Engine:
    def __init__(self, db, embedder, config=None, clock=None, playbook_path=None):
        from playbooks import DEFAULT_WORKBOOK, SCHEMA as PLAYBOOK_SCHEMA
        self.playbook_path = Path(playbook_path) if playbook_path is not None else DEFAULT_WORKBOOK
        self.embedder = embedder
        self.config = config or Config()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.conn = sqlite3.connect(str(db), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA + EVENT_SCHEMA + FUSION_SCHEMA + PLAYBOOK_SCHEMA)
        identity = dumps({"schema": 1, "policy": "ANTI_FIMI-v1", "embedder": embedder.identity,
                          "config": asdict(self.config)})
        saved = self.conn.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
        if saved and saved[0] != identity:
            self.close()
            raise ValueError("DB model/config mismatch; use a new database (no mixed vector spaces)")
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO metadata VALUES('identity',?)", (identity,))

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def ingest(self, raw_posts, enrich=True):
        """Atomic batch. Exact replay is a no-op; conflicting post IDs fail loudly."""
        batch = []
        for raw in raw_posts:
            if not isinstance(raw, dict):
                raise ValueError("each post must be an object")
            for field in ("id", "account_id", "created_at", "text"):
                if not isinstance(raw.get(field), str) or not raw[field].strip():
                    raise ValueError(f"{field} must be a nonempty string")
            event = parse_time(raw["created_at"])
            clock_now = self.clock().astimezone(UTC)
            if event > clock_now + timedelta(minutes=5):
                raise ValueError("post is over 5 minutes in the future relative to collector clock")
            urls = raw.get("urls", [])
            if not isinstance(urls, list) or any(not isinstance(u, str) for u in urls):
                raise ValueError("urls must be a list of URL strings")
            relations = raw.get("relations", [])
            if relations is None:
                relations = []
            if not isinstance(relations, list) or any(
                not isinstance(r, dict) or r.get("type") not in ("quotes", "reposts", "replies_to")
                or not isinstance(r.get("target_post_id"), str) or not r["target_post_id"].strip()
                for r in relations
            ):
                raise ValueError("relations must be a list of quotes/reposts/replies_to objects with target_post_id strings")
            if raw.get("language_hint") is not None and not isinstance(raw["language_hint"], str):
                raise ValueError("language_hint must be a string or null")
            extracted = URL_RE.findall(raw["text"])
            # Only trim punctuation extracted from prose, never an explicit URL field.
            candidates = urls + [u.rstrip(".,;!?。），)") for u in extracted]
            normalized = sorted({u for v in candidates if (u := canonical_url(v))})
            clean = URL_RE.sub(" ", raw["text"]).strip()
            clean = clean or "[URL-only post]"
            stance, reason = stance_hint(raw["text"]) if enrich else ("pending", "EXTERNAL_AI_PENDING")
            batch.append((raw, event, clock_now, normalized, clean, stance, reason))
        inserted = duplicates = 0
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute("SELECT MAX(collected_at) FROM posts").fetchone()
            previous = parse_time(row[0]) if row[0] else datetime.min.replace(tzinfo=UTC)
            for raw, event, observed, urls, clean, stance, reason in batch:
                serialized = dumps(raw)
                old = self.conn.execute("SELECT raw_json FROM posts WHERE id=?", (raw["id"],)).fetchone()
                if old:
                    if old[0] != serialized:
                        raise ValueError(f"conflicting immutable post ID: {raw['id']}")
                    duplicates += 1
                    continue
                collected = max(observed, previous + timedelta(microseconds=1))
                vector = unit(self.embedder.encode([clean])[0]) if enrich else []
                self.conn.execute("""INSERT INTO posts(id,account_id,created_at,collected_at,
                    observed_clock_at,text,raw_json,embedding_json,stance,stance_reason)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (raw["id"], raw["account_id"], stamp(event), stamp(collected), stamp(observed),
                     raw["text"], serialized, dumps(vector), stance, reason))
                self.conn.executemany("INSERT INTO post_urls VALUES(?,?)", [(raw["id"], u) for u in urls])
                previous = collected
                inserted += 1
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        return {"inserted": inserted, "duplicates": duplicates}

    def _cluster(self, posts):
        clusters, assignment = [], {}
        for post in posts:
            vector = json.loads(post["embedding_json"])
            # Unknown discourse is kept apart from explicit refutation and unmarked assertion.
            matches = [(min(cosine(vector, c["centroid"]), cosine(vector, c["seed"])), c)
                       for c in clusters if c["stance"] == post["stance"]]
            score, chosen = max(matches, key=lambda item: (item[0], item[1]["id"])) if matches else (-1, None)
            if chosen is None or score < self.config.similarity:
                chosen = {"id": key("N_", post["id"]), "seed_post_id": post["id"],
                          "stance": post["stance"], "seed": vector, "sum": vector[:],
                          "centroid": vector[:], "size": 1}
                clusters.append(chosen)
            else:
                chosen["sum"] = [a + b for a, b in zip(chosen["sum"], vector)]
                chosen["centroid"] = unit(chosen["sum"])
                chosen["size"] += 1
            assignment[post["id"]] = chosen["id"]
        return clusters, assignment

    def _co_sharing(self, posts, assignment):
        return co_sharing(posts, assignment, self.conn.execute("SELECT * FROM post_urls"), self.config)

    def _hourly(self, posts, assignment, cutoff):
        return hourly_diffusion(posts, assignment, cutoff, self.config)

    def analyze(self, as_of=None):
        """Rebuild from persisted vectors in arrival order; no model re-encoding."""
        as_of = as_of or self.clock()
        if as_of.tzinfo is None:
            raise ValueError("as_of requires timezone")
        as_of = as_of.astimezone(UTC)
        cutoff = hour(as_of)  # Only completed event-time hours can trigger volume alerts.
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            posts = list(self.conn.execute("SELECT * FROM posts WHERE created_at<=? AND embedding_json!='[]' ORDER BY seq", (stamp(as_of),)))
            clusters, assignment = self._cluster(posts)
            co_alerts = self._co_sharing(posts, assignment)
            hourly_alerts, hourly_rows = self._hourly(posts, assignment, cutoff)
            self.conn.execute("DELETE FROM hourly")
            self.conn.execute("DELETE FROM assignments")
            self.conn.execute("DELETE FROM clusters")
            self.conn.executemany("INSERT INTO clusters VALUES(?,?,?,?,?)",
                                  [(c["id"], c["seed_post_id"], c["stance"], c["size"], dumps(c["centroid"]))
                                   for c in clusters])
            self.conn.executemany("INSERT INTO assignments VALUES(?,?)", assignment.items())
            self.conn.executemany("INSERT INTO hourly VALUES(?,?,?,?)", hourly_rows)
            urls_by_post = defaultdict(list)
            for row in self.conn.execute("SELECT post_id,url FROM post_urls"):
                urls_by_post[row["post_id"]].append(row["url"])
            events, memberships = group_events(posts, urls_by_post)
            self.conn.execute("DELETE FROM event_memberships")
            self.conn.execute("DELETE FROM events")
            self.conn.executemany("INSERT INTO events VALUES(?,?,?,?,?,?)",
                                  [(e["id"], e["seed_post_id"], e["title"], stamp(e["first"]),
                                    stamp(e["last"]), dumps(sorted(e["basis"]))) for e in events])
            self.conn.executemany("INSERT INTO event_memberships VALUES(?,?,?)",
                                  [(pid, eid, basis) for pid, (eid, basis) in memberships.items()])
            self.conn.execute("UPDATE alerts SET active=0, last_evaluated_at=?", (stamp(as_of),))
            alerts = sorted(co_alerts + hourly_alerts, key=lambda a: a["id"])
            for alert in alerts:
                self.conn.execute("""INSERT INTO alerts VALUES(?,?,1,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    active=1,last_evaluated_at=excluded.last_evaluated_at,payload_json=excluded.payload_json""",
                    (alert["id"], alert["kind"], stamp(self.clock()), stamp(as_of), dumps(alert)))
            self.conn.execute("INSERT OR REPLACE INTO metadata VALUES('last_analysis_at',?)", (stamp(as_of),))
            self.conn.execute("INSERT OR REPLACE INTO metadata VALUES('analysis_completed_at',?)", (stamp(self.clock()),))
            self.conn.commit()
            self.analyze_behavior(as_of)
            return alerts
        except BaseException:
            self.conn.rollback()
            raise

    def analyze_behavior(self, as_of=None):
        """Independent raw-data branch; external AI is joined only after scoring."""
        from behavior import analyze_behavior
        from fusion import ai_claims_by_post, ai_clusters_by_post, enrich_signal, _aggregate_alerts, ai_diffusion_alerts, cluster_diffusion_alerts
        as_of = as_of or self.clock()
        if as_of.tzinfo is None:
            raise ValueError("as_of requires timezone")
        as_of = as_of.astimezone(UTC)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            posts = list(self.conn.execute("SELECT * FROM posts WHERE created_at<=? ORDER BY seq", (stamp(as_of),)))
            result = analyze_behavior(posts, list(self.conn.execute("SELECT * FROM post_urls")), as_of)
            mode = self.conn.execute("SELECT value FROM metadata WHERE key='pipeline_mode'").fetchone()
            no_ai = mode is not None and mode[0] == 'no-ai'
            ai = {} if no_ai else ai_claims_by_post(self.conn)
            ai_clusters = {} if no_ai else ai_clusters_by_post(self.conn)
            from resources import group_resources
            resources = group_resources(posts, list(self.conn.execute('SELECT * FROM post_urls'))) if no_ai else []
            from issues import issue_groups
            issues = issue_groups(posts, resources) if no_ai else []
            from resource_alerts import resource_bursts
            previous_early = self.conn.execute("SELECT value FROM metadata WHERE key='resource_alerts'").fetchone()
            early_alerts = resource_bursts(resources, posts, as_of, json.loads(previous_early[0]) if previous_early else []) if no_ai else []
            signals = [enrich_signal(signal, ai, ai_clusters) for signal in result["signals"]]
            volume = ai_diffusion_alerts(posts, ai, as_of, self.config)
            volume += cluster_diffusion_alerts(posts, ai_clusters, ai, as_of, self.config)
            previous = [{**json.loads(row["payload_json"]), "first_detected_at": row["first_detected_at"]}
                        for row in self.conn.execute("SELECT * FROM investigations WHERE active=1")]
            parents = _aggregate_alerts(signals, previous)
            detected = stamp(self.clock())
            for table in ("behavior_signals", "investigations"):
                self.conn.execute(f"UPDATE {table} SET active=0,last_evaluated_at=?", (stamp(as_of),))
            for signal in signals:
                self.conn.execute("""INSERT INTO behavior_signals VALUES(?,1,?,?,?) ON CONFLICT(id)
                    DO UPDATE SET active=1,last_evaluated_at=excluded.last_evaluated_at,payload_json=excluded.payload_json""",
                    (signal["id"], detected, stamp(as_of), dumps(signal)))
            for parent in parents:
                parent = enrich_signal(parent, ai, ai_clusters)
                self.conn.execute("""INSERT INTO investigations VALUES(?,?,1,?,?,?) ON CONFLICT(id)
                    DO UPDATE SET active=1,last_evaluated_at=excluded.last_evaluated_at,payload_json=excluded.payload_json""",
                    (parent["id"], parent["seed_signal_id"], detected, stamp(as_of), dumps(parent)))
                last_history = self.conn.execute("SELECT MAX(evaluated_at) FROM investigation_history WHERE investigation_id=?", (parent["id"],)).fetchone()[0]
                history_at = max(parse_time(detected), parse_time(last_history) + timedelta(microseconds=1)) if last_history else parse_time(detected)
                self.conn.execute("INSERT INTO investigation_history VALUES(?,?,?)", (parent["id"], stamp(history_at), dumps(parent)))
            from playbooks import update_playbook
            update_playbook(self.conn, self.playbook_path, posts, signals, parents, ai_clusters, stamp(as_of), detected)
            for name, value in (("behavior_as_of", stamp(as_of)), ("behavior_seq", str(max((p["seq"] for p in posts), default=0))),
                                ("behavior_network", dumps(result["network"])), ("ai_volume_signals", dumps(volume)), ("last_analysis_at", stamp(as_of)),
                                ("analysis_completed_at", detected), ('resource_groups', dumps(resources)),
                                ('resource_alerts', dumps(early_alerts)), ('issue_groups', dumps(issues))):
                self.conn.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", (name, value))
            self.conn.commit()
            return signals
        except BaseException:
            self.conn.rollback()
            raise

    def export(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        alerts = [json.loads(row[0]) for row in self.conn.execute(
            "SELECT payload_json FROM alerts WHERE active=1 ORDER BY id")]
        posts = {row["id"]: dict(row) for row in self.conn.execute("SELECT * FROM posts")}
        narratives = []
        for cluster in self.conn.execute("SELECT * FROM clusters ORDER BY id"):
            members = [posts[row[0]] for row in self.conn.execute(
                "SELECT post_id FROM assignments WHERE cluster_id=?", (cluster["id"],))]
            members.sort(key=lambda p: (p["created_at"], p["id"]))
            narratives.append({"id": cluster["id"], "status": "provisional", "stance_hint": cluster["stance"],
                               "post_ids": [p["id"] for p in members], "size": len(members),
                               "earliest_observed_post_id": members[0]["id"],
                               "earliest_observed_at": members[0]["created_at"],
                               "representative_text": posts[cluster["seed_post_id"]]["text"]})
        edges = []
        for alert in alerts:
            if alert["kind"] == "repeated_url_coshare":
                edges.append({"source": alert["account_ids"][0], "target": alert["account_ids"][1],
                              "relation": "co_share_undirected", "episode_count": alert["episode_count"],
                              "alert_id": alert["id"], "evidence_post_ids": alert["evidence_post_ids"]})
        graph = {"nodes": [{"id": a} for a in sorted({p["account_id"] for p in posts.values()})],
                 "edges": edges, "caveat": "Co-sharing is undirected, not a causal repost path."}
        for name, payload in (("alerts.json", alerts), ("narratives.json", narratives), ("network.json", graph)):
            (directory / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        template = Path(__file__).with_name("network_template.html").read_text(encoding="utf-8")
        evidence = {pid: {field: post[field] for field in ("id", "account_id", "created_at", "text")}
                    for pid, post in posts.items()}
        embedded = dumps({"graph": graph, "alerts": alerts, "posts": evidence}).replace("<", "\\u003c")
        (directory / "network.html").write_text(template.replace("__ANTI_FIMI_DATA__", embedded), encoding="utf-8")
        lines = ["# ANTI_FIMI 분석가 브리핑", "", f"잠정 서사 {len(narratives)}개, 검토 경보 {len(alerts)}개.",
                 "", "경보는 허위정보·CIB·국가 배후 판정이 아닙니다. 수집 범위의 최초 관측은 최초 유포를 뜻하지 않습니다.", ""]
        for alert in sorted(alerts, key=lambda a: (a["priority"], a["id"])):
            lines.extend([f"## {alert['id']} / {alert['priority']}",
                          f"- 사유: {', '.join(alert['reason_codes'])}",
                          f"- 계정: {', '.join(alert['account_ids'])}",
                          f"- 근거 게시물: {', '.join(alert['evidence_post_ids'])}",
                          "- 확인 과제: 원문·공식 발표 시각, 계정 관계, 자연 발생 확산, 수집 누락을 대조하세요.", ""])
        lines.extend(["## 원문 근거 (인용 데이터)", ""])
        evidence_ids = sorted({pid for a in alerts for pid in a["evidence_post_ids"]})
        for pid in evidence_ids:
            p = posts[pid]
            # JSON quoting prevents raw post Markdown from becoming briefing instructions.
            lines.append("    " + dumps({"id": pid, "created_at": p["created_at"], "text": p["text"],
                                          "stance_hint": p["stance"], "stance_reason": p["stance_reason"]}))
        (directory / "briefing.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"posts": len(posts), "narratives": len(narratives), "alerts": len(alerts), "edges": len(edges)}


def read_jsonl(filename):
    with Path(filename).open(encoding="utf-8-sig") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON on line {number}") from exc


def get_path(obj, dotted):
    for part in dotted.split(".") if dotted else []:
        obj = obj[part]
    return obj


def fetch_http(url, mapping=None, items_path="", token=None):
    """One documented-by-user JSON endpoint per call. No guessed VEIL API contract."""
    headers = {"Accept": "application/json", "User-Agent": "ANTI_FIMI/1.0"}
    if token:
        headers["Authorization"] = "Bearer " + token
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        payload = json.load(response)
    items = get_path(payload, items_path)
    if not isinstance(items, list):
        raise ValueError("HTTP items path must select a list of posts")
    for item in items:
        if mapping:
            mapped = {field: get_path(item, dotted) for field, dotted in mapping.items()}
            mapped["_source_raw"] = item
            yield mapped
        else:
            yield item


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ANTI_FIMI", description=__doc__)
    parser.add_argument("--db", default="ANTI_FIMI.sqlite3")
    parser.add_argument("--embedder", choices=("semantic", "lexical-demo"), default="semantic")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--revision", help="Hugging Face model commit, or use a local model directory")
    actions = parser.add_subparsers(dest="action", required=True)
    ingest = actions.add_parser("ingest", help="collect raw JSONL, then analyze/export")
    ingest.add_argument("--input", required=True)
    collect = actions.add_parser("collect", help="fetch one HTTP JSON page, then analyze/export")
    collect.add_argument("--url", required=True)
    collect.add_argument("--mapping", help="JSON file mapping canonical fields to dotted source paths")
    collect.add_argument("--items-path", default="")
    actions.add_parser("analyze", help="recompute all stored state and export")
    for child in actions.choices.values():
        child.add_argument("--out", default="results")
        child.add_argument("--as-of", help="ISO 8601 event-time horizon; defaults to collector now")
    args = parser.parse_args(argv)
    embedder = SemanticEmbedder(args.model, args.revision) if args.embedder == "semantic" else LexicalDemoEmbedder()
    with Engine(args.db, embedder) as engine:
        result = {}
        if args.action == "ingest":
            result.update(engine.ingest(read_jsonl(args.input)))
        elif args.action == "collect":
            mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8-sig")) if args.mapping else None
            result.update(engine.ingest(fetch_http(args.url, mapping, args.items_path,
                                                   os.environ.get("VEIL_TOKEN"))))
        engine.analyze(parse_time(args.as_of) if args.as_of else None)
        result.update(engine.export(args.out))
        print(dumps({"project": "ANTI_FIMI", "embedder": embedder.identity, **result}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, KeyError, sqlite3.Error) as error:
        print(f"ANTI_FIMI: {error}", file=sys.stderr)
        raise SystemExit(2)
