"""VEIL 사이트와 ANTI_FIMI 실시간 수집을 함께 실행합니다."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
import webbrowser

from launcher_utils import (ROOT, RUNTIME, LaunchError, active_web, ensure_python,
                            fetch_json, finish, launch_lock, process_env, read_json)

INFO = RUNTIME / 'connected-instance.json'
STOP = RUNTIME / 'connected.stop'


class ChildProcesses:
    """A Windows Job owns only the processes created by this launcher and their children."""
    def __init__(self):
        self.children = []
        self.job = None
        if os.name == 'nt':
            from ctypes import wintypes

            class BasicLimits(ctypes.Structure):
                _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                            ('flags', wintypes.DWORD), ('min_working', ctypes.c_size_t),
                            ('max_working', ctypes.c_size_t), ('process_limit', wintypes.DWORD),
                            ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                            ('scheduling', wintypes.DWORD)]

            class ExtendedLimits(ctypes.Structure):
                _fields_ = [('basic', BasicLimits), ('io', ctypes.c_ulonglong * 6),
                            ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                            ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]

            self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
            self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                             ctypes.c_void_p, wintypes.DWORD]
            self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.job = self.kernel.CreateJobObjectW(None, None)
            if not self.job:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.kernel.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                error = ctypes.WinError(ctypes.get_last_error())
                self.kernel.CloseHandle(self.job)
                self.job = None
                raise error

    def start(self, command, cwd, log):
        child = subprocess.Popen([str(part) for part in command], cwd=cwd, env=process_env(),
                                 stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.children.append(child)
        if self.job and not self.kernel.AssignProcessToJobObject(self.job, int(child._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        return child

    def close(self):
        if self.job:
            # Closing this handle also ends Node and the session-bound collector.
            self.kernel.CloseHandle(self.job)
            self.job = None
        else:
            for child in reversed(self.children):
                if child.poll() is None:
                    child.terminate()
        for child in reversed(self.children):
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


def require_free_port(port):
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError as exc:
            raise LaunchError(f'{port} 포트가 사용 중입니다. 기존 서버는 종료하지 않았습니다. 연결 실행 창을 확인하세요.') from exc


def stop_requested(token):
    return read_json(STOP).get('token') == token


def wait_until(check, child, token, description, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stop_requested(token):
            raise KeyboardInterrupt
        if child and child.poll() is not None:
            raise LaunchError(f'{description} 실행이 종료됐습니다. runtime 폴더의 연결 로그를 확인하세요.')
        try:
            value = check()
            if value:
                return value
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    raise LaunchError(f'{description} 준비 시간이 초과됐습니다. runtime 폴더의 연결 로그를 확인하세요.')


def connected_paths(d4d):
    folder = Path(d4d).resolve() if d4d else ROOT.parent
    engine = folder / 'ANTI_FIMI/server.py'
    static = folder / 'fimi-dashboard/dist/index.html'
    if not engine.is_file() or not static.is_file():
        raise LaunchError('D4D 안의 veil-crawler에서 실행하세요. 개발 위치에서는 --d4d D4D폴더를 지정하세요.')
    data = folder / 'ANTI_FIMI_DEMO_DATA'
    data.mkdir(parents=True, exist_ok=True)
    return folder, engine, data / 'ANTI_FIMI_veil_live.sqlite3'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--d4d', help='개발 위치에서 D4D 폴더 지정; 기본값은 상위 폴더')
    parser.add_argument('--site-port', type=int, default=5180)
    parser.add_argument('--engine-port', type=int, default=8788)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--no-pause', action='store_true')
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args(argv)
    if any(not 1 <= port <= 65535 for port in (args.site_port, args.engine_port)):
        parser.error('포트는 1~65535 범위여야 합니다.')
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if args.stop:
        info = read_json(INFO)
        if not info.get('token'):
            print('연결 실행 기록이 없습니다. 종료할 프로세스가 없습니다.')
            return 0
        STOP.write_text(json.dumps({'token': info['token']}), encoding='utf-8')
        print('연결 종료를 요청했습니다. 실행 창이 종료될 때까지 기다리세요.')
        return 0

    token = str(uuid.uuid4())
    children = None
    try:
        with launch_lock('connected'):
            folder, engine_path, db = connected_paths(args.d4d)
            require_free_port(args.engine_port)
            collector_python = ensure_python()
            children = ChildProcesses()
            INFO.write_text(json.dumps({'token': token, 'pid': os.getpid(), 'status': 'starting'}), encoding='utf-8')
            with (RUNTIME / 'connected-web.log').open('a', encoding='utf-8') as web_log, \
                 (RUNTIME / 'connected-engine.log').open('a', encoding='utf-8') as engine_log:
                web_child = None
                web = active_web()
                if not web:
                    require_free_port(args.site_port)
                    web_child = children.start([sys.executable, '-X', 'utf8', '-u', ROOT / 'run_web.py',
                        '--port', args.site_port, '--no-browser', '--no-pause'], ROOT, web_log)
                    web = wait_until(active_web, web_child, token, 'VEIL 사이트', timeout=180)
                source = web['url'].rstrip('/')
                engine_url = f'http://127.0.0.1:{args.engine_port}'
                engine_child = children.start([sys.executable, '-X', 'utf8', '-u', engine_path,
                    '--no-watch', '--veil-source', source, '--veil-crawler', ROOT / 'crawler',
                    '--collector-python', collector_python, '--port', args.engine_port, '--db', db], folder, engine_log)

                def ready():
                    result = fetch_json(engine_url + '/api/dashboard')
                    collector = result.get('feed', {}).get('collector', {})
                    return result if collector.get('baseline_ready') and collector.get('status') == 'running' else None

                dashboard = wait_until(ready, engine_child, token, '탐지 엔진·수집기')
                INFO.write_text(json.dumps({'token': token, 'pid': os.getpid(), 'status': 'running',
                    'site_url': source + '/', 'engine_url': engine_url + '/',
                    'site_reused': web_child is None, 'session_id': dashboard.get('session', {}).get('id')}), encoding='utf-8')
                print(f'연결 완료\n사이트: {source}/\n대시보드: {engine_url}/\n'
                      '사이트에서 시뮬레이션을 시작하세요. 새 시연은 대시보드에서 실행하세요.\n'
                      '종료: STOP_ANTI_FIMI.cmd 또는 이 창에서 Ctrl+C', flush=True)
                if not args.no_browser:
                    webbrowser.open(source + '/')
                    webbrowser.open(engine_url + '/')
                while not stop_requested(token):
                    if engine_child.poll() is not None or (web_child and web_child.poll() is not None):
                        raise LaunchError('연결 프로세스가 종료됐습니다. runtime 폴더의 연결 로그를 확인하세요.')
                    time.sleep(0.25)
            return 0
    except KeyboardInterrupt:
        print('\n연결 실행을 종료합니다.', flush=True)
        return 0
    except (LaunchError, OSError, ValueError) as exc:
        print(f'실행 안내: {exc}', flush=True)
        return 1
    finally:
        if children:
            children.close()
        if read_json(INFO).get('token') == token:
            INFO.unlink(missing_ok=True)
        if stop_requested(token):
            STOP.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(finish(main()))
