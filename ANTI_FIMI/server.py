"""Local ANTI_FIMI API, append-only JSONL intake and built React dashboard hosting."""
import argparse
from contextlib import closing
from datetime import datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import sqlite3
import threading
import uuid
from urllib.parse import unquote, urlsplit, parse_qs

from dashboard import snapshot
from fusion import pending_ai, store_ai_results
from engine import Engine, LexicalDemoEmbedder, SemanticEmbedder, UTC, dumps, hour, parse_time, stamp
from sessions import SessionConflict, active_database, checkpoint_watch, select_database, watch_key

ROOT = Path(__file__).resolve().parent.parent


class RawOnlyEmbedder:
    """Keeps a stored DB identity without loading or executing a model."""
    def __init__(self, db):
        self.identity = "ANTI_FIMI:external-ai-v1"
        if Path(db).exists():
            with closing(sqlite3.connect(db)) as connection:
                row = connection.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
                if row:
                    self.identity = json.loads(row[0])["embedder"]

    def encode(self, texts):
        raise RuntimeError("Raw-only mode never executes embeddings; use external AI results")


class Runtime:
    def __init__(self, db, embedder, watch=None, clock=None, local_preview=False, playbook_path=None, no_ai=False):
        self.base_db, self.embedder = Path(db).resolve(), embedder
        self.db = active_database(self.base_db)
        self.playbook_path = playbook_path
        self.local_preview = local_preview
        self.no_ai = no_ai
        if no_ai and local_preview:
            raise ValueError('no_ai and local_preview cannot be combined')
        self.clock = clock or (lambda: datetime.now(UTC))
        self.watch = Path(watch).resolve() if watch else None
        self.lock, self.stop = threading.RLock(), threading.Event()
        self.lifecycle_lock = threading.Lock()
        self.resetting = False
        self.veil = None
        self.feed = {"status": "watching" if watch else "idle", "error": None, "last_ingested_at": None}
        self.db.parent.mkdir(parents=True, exist_ok=True)
        with Engine(self.db, self.embedder, clock=self.clock, playbook_path=self.playbook_path) as engine:
            previous = engine.conn.execute("SELECT value FROM metadata WHERE key='last_analysis_at'").fetchone()
            mode = engine.conn.execute("SELECT value FROM metadata WHERE key='source_clock_mode'").fetchone()
            self.clock_mode = mode[0] if mode else "replay"
            saved_session = engine.conn.execute("SELECT value FROM metadata WHERE key='demo_session'").fetchone()
            self.session = json.loads(saved_session[0]) if saved_session else {
                'id': 'initial', 'started_at': None, 'requires_session_id': False}
            with engine.conn:
                engine.conn.execute("INSERT OR REPLACE INTO metadata VALUES('pipeline_mode',?)",
                                    ('no-ai' if no_ai else "local-preview" if local_preview else "external-ai",))
            self.analyze(engine, parse_time(previous[0]) if previous else None)
        if self.watch:
            self.watch.parent.mkdir(parents=True, exist_ok=True)
            self.watch.touch(exist_ok=True)

    def analyze(self, engine, cutoff=None):
        return engine.analyze(cutoff) if self.local_preview else engine.analyze_behavior(cutoff)

    def require_session(self, session_id):
        if self.resetting:
            raise RuntimeError('새 시연을 준비 중입니다. 잠시 후 다시 시도하세요.')
        if (self.session['requires_session_id'] or session_id is not None) and session_id != self.session['id']:
            raise SessionConflict('시연이 변경되었습니다. 현재 session_id로 새 수집을 시작하세요. 이전 전송 대기열을 재사용하지 마세요.')

    def new_demo(self, expected_session_id):
        with self.lifecycle_lock:
            with self.lock:
                if expected_session_id != self.session['id']:
                    raise SessionConflict('시연이 이미 변경되었습니다. 화면을 새로고침하세요.')
                self.resetting = True
            try:
                # Stop the child outside the data lock: it may be awaiting an API response.
                if self.veil:
                    self.veil.prepare_reset()
                result = self.rotate_demo(expected_session_id)
            finally:
                with self.lock:
                    self.resetting = False
            if self.veil:
                self.veil.start(self.session['id'])
                self.veil.wait_ready()
                result['dashboard'] = self.dashboard()
            return result

    def rotate_demo(self, expected_session_id):
        with self.lock:
            if expected_session_id != self.session['id']:
                raise SessionConflict('시연이 이미 변경되었습니다. 화면을 새로고침하세요.')
            session = {'id': str(uuid.uuid4()), 'started_at': stamp(self.clock()), 'requires_session_id': True}
            folder = self.base_db.parent / (self.base_db.stem + '_sessions')
            folder.mkdir(parents=True, exist_ok=True)
            candidate = folder / (session['id'] + '.sqlite3')
            with Engine(candidate, self.embedder, clock=self.clock, playbook_path=self.playbook_path) as engine:
                with engine.conn:
                    engine.conn.execute("INSERT OR REPLACE INTO metadata VALUES('pipeline_mode',?)",
                        ('no-ai' if self.no_ai else 'local-preview' if self.local_preview else 'external-ai',))
                    engine.conn.execute("INSERT OR REPLACE INTO metadata VALUES('source_clock_mode','live')")
                    engine.conn.execute("INSERT OR REPLACE INTO metadata VALUES('demo_session',?)", (dumps(session),))
                    engine.conn.execute("INSERT OR REPLACE INTO metadata VALUES('previous_demo_db',?)", (str(self.db),))
                    checkpoint_watch(self.db, engine.conn, self.watch)
                self.analyze(engine, self.clock())
            # Commit selection only after initialization succeeds; the old DB is untouched.
            select_database(self.base_db, session['id'])
            self.db, self.session, self.clock_mode = candidate, session, 'live'
            self.feed.update(status='watching' if self.watch else 'idle', error=None, last_ingested_at=None)
            return {'session': dict(session), 'dashboard': self.dashboard()}

    def ingest(self, posts, source_now=None, session_id=None, *, from_watch=False):
        if not isinstance(posts, list) or not all(isinstance(p, dict) for p in posts):
            raise ValueError("posts must be an array of raw post objects")
        if not posts:
            raise ValueError("posts must not be empty")
        requested_cutoff = parse_time(source_now) if source_now else self.clock()
        with self.lock:
            if self.resetting:
                raise RuntimeError('새 시연을 준비 중입니다. 잠시 후 다시 시도하세요.')
            if not from_watch:
                self.require_session(session_id)
            with Engine(self.db, self.embedder, clock=self.clock, playbook_path=self.playbook_path) as engine:
                analyzed_count = engine.conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
                result = engine.ingest(posts, enrich=self.local_preview)
                previous = engine.conn.execute("SELECT value FROM metadata WHERE key='last_analysis_at'").fetchone()
                cutoff = requested_cutoff
                if previous and analyzed_count:
                    cutoff = max(cutoff, parse_time(previous[0]))
                self.analyze(engine, cutoff)
                self.clock_mode = "replay" if source_now else "live"
                with engine.conn:
                    engine.conn.execute("INSERT OR REPLACE INTO metadata VALUES('source_clock_mode',?)", (self.clock_mode,))
            self.feed["last_ingested_at"] = stamp(self.clock())
            return {**result, 'session_id': self.session['id']}

    def advance_live_clock(self):
        """Finalize an hour even if no new post follows the burst; replay time stays explicit."""
        with self.lock:
            if self.resetting or self.clock_mode != "live":
                return
            with Engine(self.db, self.embedder, clock=self.clock, playbook_path=self.playbook_path) as engine:
                previous = engine.conn.execute("SELECT value FROM metadata WHERE key='last_analysis_at'").fetchone()
                now = self.clock()
                if self.local_preview:
                    pending_ready = engine.conn.execute("""SELECT 1 FROM posts p LEFT JOIN assignments a ON a.post_id=p.id
                        WHERE a.post_id IS NULL AND p.created_at<=? LIMIT 1""", (stamp(now),)).fetchone()
                else:
                    pending_ready = engine.conn.execute("SELECT 1 FROM posts WHERE created_at>? AND created_at<=? LIMIT 1",
                        (previous[0] if previous else "", stamp(now))).fetchone()
                if previous and (hour(now) > hour(parse_time(previous[0])) or pending_ready):
                    self.analyze(engine, now)

    def ai_pending(self, limit=100, after_seq=0):
        if self.no_ai:
            return {'items': [], 'mode': 'no-ai', 'disabled': True}
        with self.lock, Engine(self.db, self.embedder, clock=self.clock, playbook_path=self.playbook_path) as engine:
            return {**pending_ai(engine.conn, limit, after_seq), 'session_id': self.session['id']}

    def receive_ai(self, results, session_id=None):
        if self.no_ai:
            raise ValueError('AI intake disabled in no-ai mode; start with --external-ai to receive AI results')
        with self.lock, Engine(self.db, self.embedder, clock=self.clock, playbook_path=self.playbook_path) as engine:
            self.require_session(session_id)
            result = store_ai_results(engine.conn, results, stamp(self.clock()))
            previous = engine.conn.execute("SELECT value FROM metadata WHERE key='last_analysis_at'").fetchone()
            self.analyze(engine, parse_time(previous[0]) if previous else None)
            return result

    def dashboard(self):
        with self.lock:
            feed = dict(self.feed)
            if self.veil:
                feed['collector'] = self.veil.status()
            return {**snapshot(self.db, feed, observed_now=self.clock()), 'session': dict(self.session)}

    def reload_playbook(self):
        with self.lock, Engine(self.db, self.embedder, clock=self.clock, playbook_path=self.playbook_path) as engine:
            previous = engine.conn.execute("SELECT value FROM metadata WHERE key='last_analysis_at'").fetchone()
            self.analyze(engine, parse_time(previous[0]) if previous else None)
            return {"playbook": json.loads(engine.conn.execute("SELECT value FROM metadata WHERE key='playbook_status'").fetchone()[0])}

    def poll_file(self):
        if not self.watch:
            return
        with self.lock:
            if self.resetting:
                return
            try:
                content = self.watch.read_bytes()
                cursor_key = watch_key(self.watch)
                with closing(sqlite3.connect(self.db)) as connection:
                    row = connection.execute("SELECT value FROM metadata WHERE key=?", (cursor_key,)).fetchone()
                    ignored = {r[0] for r in connection.execute('SELECT id FROM reset_ignored_posts')} if self.session['requires_session_id'] else set()
                cursor = json.loads(row[0]) if row else {"offset": 0, "prefix_sha256": hashlib.sha256(b"").hexdigest()}
                offset = cursor["offset"]
                rewritten = offset > len(content) or hashlib.sha256(content[:offset]).hexdigest() != cursor["prefix_sha256"]
                if rewritten:
                    offset = 0
                elif cursor.get('skip_partial'):
                    boundary = content.find(b'\n', offset)
                    if boundary < 0:
                        return
                    line_start = content.rfind(b'\n', 0, offset) + 1
                    try:
                        old_item = json.loads(content[line_start:boundary].decode('utf-8-sig'))
                        old_id = old_item.get('id') if isinstance(old_item, dict) else None
                    except (ValueError, UnicodeError):
                        old_id = None
                    offset = boundary + 1
                    with closing(sqlite3.connect(self.db)) as connection:
                        if isinstance(old_id, str):
                            connection.execute('INSERT OR IGNORE INTO reset_ignored_posts VALUES(?)', (old_id,))
                            ignored.add(old_id)
                        connection.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (cursor_key,
                            dumps({'offset': offset, 'prefix_sha256': hashlib.sha256(content[:offset]).hexdigest()})))
                        connection.commit()
                complete_end = content.rfind(b"\n") + 1
                if complete_end <= offset:
                    self.feed.update(status="watching", error=None)
                    return
                posts, consumed, error = [], offset, None
                for line in content[offset:complete_end].splitlines(keepends=True):
                    try:
                        if line.strip():
                            item = json.loads(line.decode("utf-8-sig"))
                            if not isinstance(item, dict):
                                raise ValueError("post must be an object")
                            if not isinstance(item.get('id'), str) or item['id'] not in ignored:
                                posts.append(item)
                        consumed += len(line)
                    except (ValueError, UnicodeError) as exc:
                        line_number = content[:consumed].count(b"\n") + 1
                        error = f"JSONL {line_number}번째 줄을 확인하세요: {exc}"
                        break
                if posts:
                    self.ingest(posts, from_watch=True)
                if consumed > offset:
                    saved = dumps({"offset": consumed, "prefix_sha256": hashlib.sha256(content[:consumed]).hexdigest()})
                    with closing(sqlite3.connect(self.db)) as connection:
                        connection.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", (cursor_key, saved))
                        connection.commit()
                self.feed.update(status="error" if error else "watching", error=error)
            except (ValueError, OSError, sqlite3.Error, RuntimeError, KeyError) as exc:
                self.feed.update(status="error", error=str(exc))

    def watch_loop(self):
        while not self.stop.is_set():
            self.poll_file()
            try:
                self.advance_live_clock()
            except (ValueError, sqlite3.Error, RuntimeError) as exc:
                self.feed.update(status="error", error=str(exc))
            self.stop.wait(1)


def make_handler(runtime, static_dir):
    static_dir = Path(static_dir).resolve()

    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status, value):
            body = dumps(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/api/ai/pending":
                try:
                    query = parse_qs(urlsplit(self.path).query)
                    self.send_json(200, runtime.ai_pending(int(query.get("limit", [100])[0]),
                                                          int(query.get("after_seq", [0])[0])))
                except (ValueError, KeyError) as exc:
                    self.send_json(400, {"error": str(exc)})
                return
            if path == "/api/health":
                self.send_json(200, {"project": "ANTI_FIMI", "status": "ok"})
                return
            if path == '/api/session':
                with runtime.lock:
                    self.send_json(200, {'session': dict(runtime.session)})
                return
            if path == "/api/dashboard":
                try:
                    self.send_json(200, runtime.dashboard())
                except (ValueError, sqlite3.Error, KeyError) as exc:
                    self.send_json(503, {"error": "분석 결과를 조회하지 못했습니다.", "detail": str(exc)})
                return
            if path.startswith("/api/"):
                self.send_json(404, {"error": "Unknown API endpoint"})
                return
            candidate = (static_dir / unquote(path).lstrip("/")).resolve()
            if not candidate.is_relative_to(static_dir):
                self.send_error(403)
                return
            if candidate.is_dir():
                candidate = candidate / "index.html"
            if not candidate.is_file() and not Path(path).suffix:
                candidate = static_dir / "index.html"
            if not candidate.is_file():
                self.send_json(404, {"error": "대시보드 빌드가 없습니다. fimi-dashboard에서 빌드를 실행하세요."})
                return
            body = candidate.read_bytes()
            mime = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            path = urlsplit(self.path).path
            # ANTI_FIMI_C2PA_ENDPOINT_V1: isolated, bounded, in-memory image verification
            if path == '/api/media/verify':
                from media_verify import handle_upload
                try:
                    status, outcome = handle_upload(self.headers, self.rfile)
                except Exception:
                    status, outcome = 503, {'status': 'unavailable', 'error': '미디어 검증 요청 처리 중 오류가 발생했습니다.'}
                self.send_json(status, outcome)
                return
            if path not in ("/api/posts", "/api/ai/results", "/api/playbook/reload", '/api/demo/new'):
                self.send_json(404, {"error": "Unknown API endpoint"})
                return
            if self.headers.get_content_type() != "application/json":
                self.send_json(415, {"error": "Content-Type application/json required"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4_000_000:
                    raise ValueError("Request must contain 1..4000000 bytes")
                payload = json.loads(self.rfile.read(length))
                posts = payload.get("posts") if isinstance(payload, dict) else payload
                source_now = payload.get("source_now") if isinstance(payload, dict) else None
                if path == '/api/demo/new':
                    if self.headers.get('X-ANTI-FIMI-Client') != 'dashboard':
                        raise ValueError('X-ANTI-FIMI-Client: dashboard required')
                    if not isinstance(payload, dict):
                        raise ValueError('New demonstration request must be an object')
                    result = runtime.new_demo(payload.get('session_id'))
                elif path == "/api/playbook/reload":
                    if not isinstance(payload, dict):
                        raise ValueError("Reload request must be an object")
                    result = runtime.reload_playbook()
                elif path == "/api/ai/results":
                    if not isinstance(payload, dict):
                        raise ValueError("AI request must be an object with results")
                    result = runtime.receive_ai(payload.get("results"), payload.get('session_id'))
                else:
                    result = runtime.ingest(posts, source_now, payload.get('session_id') if isinstance(payload, dict) else None)
                self.send_json(200, {**result, "snapshot_id": runtime.dashboard()["snapshot_id"]})
            except SessionConflict as exc:
                self.send_json(409, {'error': str(exc)})
            except (ValueError, KeyError, UnicodeError) as exc:
                self.send_json(400, {"error": str(exc)})
            except (sqlite3.Error, RuntimeError, OSError) as exc:
                self.send_json(503, {"error": str(exc)})

        def log_message(self, fmt, *args):
            # Polling is intentionally quiet; errors remain visible in API/feed state.
            if len(args) > 1 and str(args[1]).startswith("5"):
                super().log_message(fmt, *args)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(ROOT / "ANTI_FIMI_DEMO_DATA" / "ANTI_FIMI_fusion_demo.sqlite3"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--local-preview", action="store_true", help="Explicitly enable legacy local embedding preview")
    mode.add_argument("--external-ai", action="store_true", help="Enable external AI intake; default is model-free resource/behavior analysis")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--embedder", choices=("lexical-demo", "semantic"), default="lexical-demo")
    parser.add_argument("--watch", default=str(ROOT / "ANTI_FIMI_DEMO_DATA" / "posts" / "live_posts.jsonl"))
    parser.add_argument("--no-watch", action="store_true")
    parser.add_argument("--static", default=str(ROOT / "fimi-dashboard" / "dist"))
    parser.add_argument("--playbook", help="Operational XLSX; defaults to D4D/ANTI_FIMI_운용표_v1.0.xlsx")
    parser.add_argument('--veil-source', help='Local VEIL origin; enables session-bound continuous collection')
    parser.add_argument('--veil-crawler', help='Path to the Windows-ready VEIL crawler folder')
    parser.add_argument('--collector-python', help='Optional Windows collector python.exe')
    args = parser.parse_args()
    if args.local_preview:
        embedder = LexicalDemoEmbedder() if args.embedder == "lexical-demo" else SemanticEmbedder()
    else:
        embedder = RawOnlyEmbedder(args.db)
    runtime = Runtime(args.db, embedder, None if args.no_watch else args.watch, local_preview=args.local_preview,
                      playbook_path=args.playbook, no_ai=not (args.external_ai or args.local_preview))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(runtime, args.static))
    if args.veil_source:
        from veil_control import VeilControl
        try:
            if not args.veil_crawler or not args.no_watch:
                parser.error('--veil-source requires --veil-crawler and --no-watch')
            runtime.veil = VeilControl(args.veil_source, args.veil_crawler,
                f'http://127.0.0.1:{server.server_port}', args.db, args.collector_python)
            runtime.veil.start(runtime.session['id'])
        except Exception:
            server.server_close()
            raise
    watcher = threading.Thread(target=runtime.watch_loop, daemon=True)
    watcher.start()
    print(f"ANTI_FIMI: http://127.0.0.1:{args.port} (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.stop.set()
        if runtime.veil:
            runtime.veil.stop()
        server.server_close()


if __name__ == "__main__":
    main()
