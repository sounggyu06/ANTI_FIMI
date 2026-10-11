"""Own a session-bound local VEIL collector and coordinate source reset."""
import json
from pathlib import Path
import os
import subprocess
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, build_opener


class VeilControl:
    def __init__(self, source, crawler, engine_url, base_db, python=None):
        parts = urlsplit(source)
        if parts.scheme != 'http' or parts.hostname not in ('127.0.0.1', 'localhost', '::1') or parts.username or parts.password or parts.path not in ('', '/') or parts.query or parts.fragment:
            raise ValueError('VEIL source must be a local HTTP origin')
        self.source = source.rstrip('/')
        self.crawler = Path(crawler).resolve()
        self.python = Path(python).resolve() if python else self.crawler / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        if not self.python.is_file() or not (self.crawler / 'live.py').is_file():
            raise ValueError('Windows crawler setup is required before connecting VEIL')
        base = Path(base_db).resolve()
        self.folder = base.parent / (base.stem + '_intake')
        self.folder.mkdir(parents=True, exist_ok=True)
        self.engine_url = engine_url
        self.session_id = None
        self.child = None
        self.failure = None
        self.mutex = threading.RLock()
        self.opener = build_opener(ProxyHandler({}))
        health = self.request('/api/health')
        if health.get('app') != 'veil-social' or not isinstance(health.get('sessionId'), str) or not health['sessionId']:
            raise ValueError('Start this VEIL site with run_web.py before connecting')
        self.site_session = health['sessionId']

    def request(self, path, post=False):
        request = Request(self.source + path, b'{}' if post else None,
            {'Content-Type': 'application/json', 'X-Veil-Client': 'demo'} if post else {})
        with self.opener.open(request, timeout=5) as response:
            return json.load(response)

    def start(self, session_id):
        with self.mutex:
            if self.child and self.child.poll() is None:
                if session_id == self.session_id:
                    return
                raise RuntimeError('Stop the previous collector before changing session')
            self.session_id, self.failure = session_id, None
            self.status_file = self.folder / (session_id + '.status.json')
            # A previous process's readiness is not evidence that the new process is ready.
            self.started = time.time()
            command = [str(self.python), '-X', 'utf8', '-u', str(self.crawler / 'live.py'),
                '--source', self.source, '--engine', self.engine_url, '--session-id', session_id,
                '--state', str(self.folder / (session_id + '.sqlite3')), '--status', str(self.status_file),
                '--parent-pid', str(os.getpid())]
            with (self.folder / (session_id + '.log')).open('a', encoding='utf-8') as log:
                self.child = subprocess.Popen(command, cwd=self.crawler, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

    def stop(self):
        with self.mutex:
            if self.child and self.child.poll() is None:
                self.child.terminate()
                try:
                    self.child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.child.kill()
                    self.child.wait(timeout=5)
            self.child = None

    def prepare_reset(self):
        self.stop()
        try:
            health = self.request('/api/health')
            if health.get('app') != 'veil-social' or health.get('sessionId') != self.site_session:
                raise RuntimeError('VEIL site instance changed; reconnect before resetting')
            self.request('/api/simulation/stop', post=True)
            self.request('/api/simulation/reset', post=True)
        except Exception as exc:
            self.failure = '사이트 초기화 실패: ' + str(exc)
            raise RuntimeError(self.failure) from exc

    def wait_ready(self, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.status()
            if state.get('baseline_ready') and state['status'] == 'running':
                return True
            if self.child is None or self.child.poll() is not None:
                return False
            time.sleep(0.1)
        return False

    def status(self):
        with self.mutex:
            state = {'status': 'starting', 'baseline_ready': False, 'source_url': self.source,
                     'session_id': self.session_id, 'sent': 0, 'pending': 0, 'rejected': 0, 'error': None}
            if self.session_id:
                try:
                    modified = self.status_file.stat().st_mtime
                    if modified >= self.started:
                        saved = json.loads(self.status_file.read_text(encoding='utf-8'))
                        if saved.get('session_id') == self.session_id:
                            state.update(saved)
                            if time.time() - modified > 30:
                                state.update(status='error', baseline_ready=False,
                                    error='수집기 상태 보고가 30초 이상 갱신되지 않았습니다. 수집 로그와 파일 접근 권한을 확인하세요.')
                except (OSError, ValueError):
                    pass
                if state['status'] == 'starting' and time.time() - self.started > 30:
                    state.update(status='error', error='수집기 상태 파일을 확인할 수 없습니다. 수집 로그와 파일 접근 권한을 확인하세요.')
            if self.failure:
                state.update(status='error', error=self.failure)
            elif self.child is None:
                state.update(status='stopped', baseline_ready=False)
            elif self.child.poll() is not None:
                state.update(status='error', baseline_ready=False, error=state.get('error') or '수집기가 종료됐습니다. 새 시연 또는 연결 실행으로 재시작하세요.')
            return state
