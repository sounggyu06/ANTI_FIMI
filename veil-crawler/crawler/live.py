"""Collect the public VEIL feed into a session-bound, durable engine outbox."""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

import config
from crawler.parser import parse_article
from processing.normalizer import clean_text


class SessionChanged(RuntimeError):
    """A new demo has replaced this collector's fixed session."""


class ParentExited(RuntimeError):
    """The supervising engine process has exited."""


class ParentWatcher:
    def __init__(self, pid):
        if pid <= 0:
            raise ValueError("parent PID must be positive")
        self.pid, self.handle, self.kernel = pid, None, None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            self.kernel.OpenProcess.restype = wintypes.HANDLE
            self.kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            self.kernel.WaitForSingleObject.restype = wintypes.DWORD
            self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            self.kernel.CloseHandle.restype = wintypes.BOOL
            # Keep a handle to this process, so PID reuse cannot impersonate it.
            self.handle = self.kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
            if not self.handle:
                error = ctypes.get_last_error()
                if error != 87:  # ERROR_INVALID_PARAMETER: PID no longer exists
                    raise ctypes.WinError(error)

    def alive(self):
        if self.kernel is not None:
            if not self.handle:
                return False
            result = self.kernel.WaitForSingleObject(self.handle, 0)
            if result == 0x00000102:  # WAIT_TIMEOUT: process still running
                return True
            if result == 0:
                return False
            import ctypes
            raise ctypes.WinError(ctypes.get_last_error())
        # This branch is never used on Windows; os.kill(pid, 0) is unsafe there.
        try:
            os.kill(self.pid, 0)
            return True
        except ProcessLookupError:
            return False

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def origin(value):
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("source and engine must be HTTP origins without credentials")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("source and engine must be base origins, without a path")
    return f"{parsed.scheme}://{parsed.netloc.lower()}"


class Collector:
    def __init__(self, source, engine, session_id, state, status=None, http=None):
        if not session_id or not session_id.strip():
            raise ValueError("session ID is required")
        self.source, self.engine = origin(source), origin(engine)
        self.session_id, self.status = session_id, Path(status) if status else None
        self.namespace = "veil:" + hashlib.sha256(self.source.encode()).hexdigest()[:16]
        self.http = http or requests.Session()
        self.http.trust_env = False
        self.http.headers.update({"User-Agent": "ANTI_FIMI-VEIL-Collector/1.0"})
        state = Path(state)
        state.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(state)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox (
                id TEXT PRIMARY KEY, created_at TEXT, payload TEXT,
                state TEXT NOT NULL, error TEXT, first_seen TEXT NOT NULL
            );
        """)
        binding = json.dumps([self.source, self.engine, self.session_id])
        prior = self.db.execute("SELECT value FROM metadata WHERE key='binding'").fetchone()
        if prior and prior[0] != binding:
            self.db.close()
            raise ValueError("outbox belongs to another source, engine, or session; use a new state file")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('binding', ?)", (binding,))
        self.last_polled = None
        self.last_delivered = None
        self.error = None
        self.parent_alive = None

    def close(self):
        self.db.close()
        self.http.close()

    def public_post(self, article):
        raw = parse_article(article, config.SELECTORS, config.ATTRIBUTES,
                            config.POST_ID_ATTRIBUTES, config.REMOVE_TEXT_SELECTORS,
                            config.TEXT_BREAK_SELECTORS)
        post_id, account = clean_text(raw.post_id), clean_text(raw.author_id)
        text, timestamp = clean_text(raw.text), clean_text(raw.created_at)
        if not post_id or not account or not text:
            raise ValueError("missing post ID, account ID, or text")
        created = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if created.tzinfo is None or created.utcoffset() is None:
            raise ValueError("created_at must include timezone")
        if created > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("created_at is more than five minutes in the future")
        relations = []
        target = clean_text(article.get("data-retweet-original"))
        if target:
            kind = article.get("data-reference-type", "reposts")
            if kind not in ("quotes", "reposts"):
                raise ValueError("invalid reference type")
            relations.append({"type": kind, "target_post_id": self.namespace + ":post:" + target})
        reply = clean_text(article.get("data-reply-to"))
        if reply:
            relations.append({"type": "replies_to", "target_post_id": self.namespace + ":post:" + reply})
        payload = {"id": self.namespace + ":post:" + post_id,
                   "account_id": self.namespace + ":account:" + account,
                   "created_at": timestamp, "text": text,
                   "language_hint": clean_text(article.get("data-language")) or None,
                   "relations": relations, "source_url": self.source + "/posts",
                   "source_post_id": post_id}
        # UTC sorting is separate from the original timestamp kept in the evidence.
        return created.astimezone(timezone.utc).isoformat(), payload

    def stage(self, html):
        articles = BeautifulSoup(html, "html.parser").select(config.SELECTORS["post"])
        bootstrap = self.db.execute("SELECT 1 FROM metadata WHERE key='bootstrapped'").fetchone() is None
        now = datetime.now(timezone.utc).isoformat()
        with self.db:
            for article in articles:
                raw_id = next((clean_text(article.get(a)) for a in config.POST_ID_ATTRIBUTES if article.get(a)), "")
                key = raw_id or "invalid:" + hashlib.sha256(str(article).encode()).hexdigest()
                if self.db.execute("SELECT 1 FROM outbox WHERE id=?", (key,)).fetchone():
                    continue
                if bootstrap:
                    row = (key, None, None, "baseline", None, now)
                else:
                    try:
                        created, payload = self.public_post(article)
                        row = (key, created, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), "pending", None, now)
                    except (ValueError, TypeError, OverflowError) as exc:
                        row = (key, None, None, "rejected", str(exc), now)
                self.db.execute("INSERT INTO outbox VALUES (?, ?, ?, ?, ?, ?)", row)
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('bootstrapped', '1')")
        self.last_polled = now

    def body(self, rows):
        return json.dumps({"posts": [json.loads(row[1]) for row in rows],
                           "session_id": self.session_id}, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")

    def send(self, rows):
        self.check_parent()
        response = self.http.post(self.engine + "/api/posts", data=self.body(rows),
                                  headers={"Content-Type": "application/json"}, timeout=(2, 3))
        if response.status_code == 409:
            raise SessionChanged("demo session changed; restart collector with a new session and state file")
        if response.status_code == 400:
            if len(rows) > 1:
                # Isolate invalid immutable IDs without losing the remaining batch.
                for row in rows:
                    self.send([row])
            else:
                with self.db:
                    self.db.execute("UPDATE outbox SET state='rejected', error=? WHERE id=?",
                                    (response.text[:500], rows[0][0]))
            return
        response.raise_for_status()
        with self.db:
            self.db.executemany("UPDATE outbox SET state='sent', error=NULL WHERE id=?", [(r[0],) for r in rows])
        self.last_delivered = datetime.now(timezone.utc).isoformat()

    def deliver(self):
        # One bounded batch per poll keeps collection progressing during outages/backlogs.
        rows = self.db.execute("SELECT id, payload FROM outbox WHERE state='pending' ORDER BY created_at, id LIMIT 100").fetchall()
        batch = []
        for row in rows:
            if len(self.body([row])) > 3_800_000:
                with self.db:
                    self.db.execute("UPDATE outbox SET state='rejected', error='post exceeds request limit' WHERE id=?", (row[0],))
                continue
            if len(self.body(batch + [row])) > 3_800_000:
                break
            batch.append(row)
        if batch:
            self.send(batch)

    def verify_session(self):
        response = self.http.get(self.engine + "/api/session", timeout=(2, 3))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("session"), dict) or not payload["session"].get("id"):
            raise requests.RequestException("engine returned an invalid session response")
        if payload["session"]["id"] != self.session_id:
            raise SessionChanged("demo session changed; collector stopped")

    def write_status(self, stopped=False):
        counts = dict(self.db.execute("SELECT state, COUNT(*) FROM outbox GROUP BY state").fetchall())
        result = {"source_url": self.source, "engine_url": self.engine, "session_id": self.session_id,
                  "status": "stopped" if stopped else ("error" if self.error else "running"),
                  "baseline_ready": self.db.execute("SELECT 1 FROM metadata WHERE key='bootstrapped'").fetchone() is not None,
                  "last_polled_at": self.last_polled, "last_delivered_at": self.last_delivered,
                  "updated_at": datetime.now(timezone.utc).isoformat(), "error": self.error,
                  "status_write_error": None,
                  "seen": sum(counts.values()), **{key: counts.get(key, 0) for key in ("baseline", "sent", "pending", "rejected")}}
        if self.status:
            temporary = None
            try:
                self.status.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False,
                                                 dir=self.status.parent, prefix=self.status.name + ".",
                                                 suffix=".tmp") as stream:
                    temporary = Path(stream.name)
                    json.dump(result, stream, ensure_ascii=False)
                # Windows readers/OneDrive can briefly lock the existing target.
                # Never remove that target: keep the previous complete heartbeat.
                for attempt in range(6):
                    try:
                        os.replace(temporary, self.status)
                        break
                    except OSError as exc:
                        sharing_lock = isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in (5, 32, 33)
                        if not sharing_lock or attempt == 5:
                            raise
                        time.sleep(0.05 * (attempt + 1))
            except OSError as exc:
                result["status_write_error"] = str(exc)
                print(f"Status report write failed; collection continues: {exc}", file=sys.stderr, flush=True)
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError as exc:
                        print(f"Status temporary file cleanup failed: {exc}", file=sys.stderr, flush=True)
        return result

    def check_parent(self):
        if self.parent_alive is not None and not self.parent_alive():
            raise ParentExited("parent engine process exited; collector stopped")

    def poll(self, parent_alive=None):
        self.parent_alive = parent_alive
        self.check_parent()
        self.error = None
        try:
            self.verify_session()
        except SessionChanged:
            raise
        except requests.RequestException as exc:
            self.error = str(exc)
        self.check_parent()
        try:
            response = self.http.get(self.source + "/posts", timeout=(2, 3))
            response.raise_for_status()
            self.stage(response.text)
        except requests.RequestException as exc:
            self.error = str(exc)
        self.check_parent()
        try:
            self.deliver()
        except SessionChanged:
            raise
        except requests.RequestException as exc:
            self.error = str(exc)
        return self.write_status()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--status")
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--parent-pid", type=int, help="stop when the supervising engine exits")
    args = parser.parse_args(argv)
    if args.poll_seconds <= 0:
        parser.error("poll interval must be positive")
    if args.parent_pid is not None and args.parent_pid <= 0:
        parser.error("parent PID must be positive")
    collector = Collector(args.source, args.engine, args.session_id, args.state, args.status)
    watcher = None
    try:
        if args.parent_pid is not None:
            watcher = ParentWatcher(args.parent_pid)
        while True:
            result = collector.poll(watcher.alive if watcher else None)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if args.once:
                return 0
            time.sleep(args.poll_seconds)
    except SessionChanged as exc:
        collector.error = str(exc)
        collector.write_status(stopped=True)
        print(str(exc), flush=True)
        return 3
    except ParentExited as exc:
        collector.error = str(exc)
        collector.write_status(stopped=True)
        print(str(exc), flush=True)
        return 0
    except OSError as exc:
        collector.error = f"cannot monitor parent process: {exc}"
        collector.write_status(stopped=True)
        print(collector.error, flush=True)
        return 2
    except KeyboardInterrupt:
        collector.write_status(stopped=True)
        return 0
    finally:
        if watcher:
            watcher.close()
        collector.close()


if __name__ == "__main__":
    raise SystemExit(main())
