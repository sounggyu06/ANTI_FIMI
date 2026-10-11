"""두 실행 파일이 사용하는 준비·연결 함수. 별도 라이브러리는 필요 없습니다."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import uuid
from contextlib import contextmanager
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
WEB_INFO = RUNTIME / "web-instance.json"


class LaunchError(Exception):
    pass


def process_env():
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    return env


def run_checked(args, cwd):
    try:
        subprocess.run([str(arg) for arg in args], cwd=cwd, env=process_env(), check=True)
    except subprocess.CalledProcessError as error:
        raise LaunchError("준비 작업에 실패했습니다. 위의 오류를 확인한 뒤 다시 실행하세요.") from error


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fetch_json(url):
    # 로컬 서버 접속에 시스템 프록시를 사용하지 않습니다.
    with build_opener(ProxyHandler({})).open(url, timeout=2) as response:
        return json.load(response)


def active_web():
    info = read_json(WEB_INFO)
    if info.get('project_root') != str(ROOT.resolve()):
        return None
    port = info.get("port")
    if type(port) is not int or not 1 <= port <= 65535 or not info.get("session_id"):
        return None
    try:
        health = fetch_json(f"http://127.0.0.1:{port}/api/health")
        if health.get("app") == "veil-social" and health.get("sessionId") == info["session_id"]:
            return {**info, "url": f"http://127.0.0.1:{port}/"}
    except (OSError, ValueError):
        pass
    return None


def available_port(preferred=5173):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]


def ensure_node():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    node = shutil.which("node", path=process_env()["PATH"])
    if not node:
        raise LaunchError("Node.js 22.13 이상을 먼저 설치하세요. 설치 후 이 파일을 다시 실행하면 됩니다.")
    # npm.cmd는 shell=False로 실행할 수 없습니다. Node로 npm의 실제 JS 진입점을 실행합니다.
    npm_candidates = [Path(node).resolve().parent / "node_modules/npm/bin/npm-cli.js"]
    if os.name == "nt":
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(variable):
                npm_candidates.append(Path(os.environ[variable]) / "nodejs/node_modules/npm/bin/npm-cli.js")
    npm_cli = next((path for path in npm_candidates if path.is_file()), None)
    if npm_cli:
        npm = [node, str(npm_cli)]
    else:
        npm_path = shutil.which("npm", path=process_env()["PATH"])
        if not npm_path or (os.name == "nt" and Path(npm_path).suffix.lower() in (".cmd", ".bat")):
            raise LaunchError("Node.js의 npm 구성요소가 없습니다. Node.js 설치를 복구하세요.")
        npm = [npm_path]
    version = subprocess.check_output([node, "--version"], text=True).strip().lstrip("v")
    if tuple(int(value) for value in version.split(".")[:2]) < (22, 13):
        raise LaunchError("Node.js 버전이 낮습니다. 22.13 이상으로 설치한 후 다시 실행하세요.")
    social = ROOT / "veil-social"
    lock = social / "package-lock.json"
    fingerprint = hashlib.sha256(lock.read_bytes()).hexdigest()
    marker = RUNTIME / "node-dependencies.txt"
    old = marker.read_text().strip() if marker.exists() else None
    ready = all((social / "node_modules" / name).is_file() for name in
                ("vite/bin/vite.js", "react/package.json", "@vitejs/plugin-react/package.json"))
    if not ready or (old is not None and old != fingerprint):
        print("웹 실행에 필요한 항목을 설치합니다. 첫 실행에는 인터넷이 필요합니다.", flush=True)
        run_checked([*npm, "ci", "--cache", RUNTIME / "npm-cache", "--no-audit", "--no-fund"], social)
    marker.write_text(fingerprint)
    return node, npm


def ensure_build(npm):
    social = ROOT / "veil-social"
    digest = hashlib.sha256()
    files = [social / "package-lock.json", social / "vite.config.js", social / "index.html"]
    files += sorted(path for folder in ("src", "public") for path in (social / folder).rglob("*") if path.is_file())
    for path in files:
        digest.update(str(path.relative_to(social)).encode())
        digest.update(path.read_bytes())
    fingerprint = digest.hexdigest()
    marker = RUNTIME / "web-build.txt"
    if not (social / "dist/index.html").is_file() or not marker.exists() or marker.read_text() != fingerprint:
        print("웹 화면을 준비합니다.", flush=True)
        run_checked([*npm, "run", "build", "--", "--configLoader", "native"], social)
        marker.write_text(fingerprint)


def ensure_python():
    if sys.version_info < (3, 10):
        raise LaunchError("Python 3.10 이상으로 이 파일을 실행하세요.")
    crawler = ROOT / "crawler"
    python = crawler / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    config = crawler / '.venv/pyvenv.cfg'
    if python.is_file() and config.is_file():
        settings = dict(line.split('=', 1) for line in config.read_text(encoding='utf-8').splitlines() if '=' in line)
        old_home = settings.get('home', '').strip()
        if old_home and Path(old_home).resolve() != Path(sys.base_prefix).resolve():
            # A copied venv points at the original computer's Python installation.
            backup = crawler / ('.venv.previous-' + uuid.uuid4().hex[:8])
            (crawler / '.venv').rename(backup)
            print('이전 Python 설치 경로를 가진 가상환경을 보존하고 현재 PC용으로 재생성합니다.', flush=True)
    if not python.is_file():
        print("크롤러 실행 환경을 준비합니다.", flush=True)
        run_checked([sys.executable, "-m", "venv", crawler / ".venv"], ROOT)
    probe = 'import requests, bs4, tzdata; from importlib.metadata import version; assert (2,32)<=tuple(map(int,version("requests").split(".")[:2]))<(3,0); assert (4,12)<=tuple(map(int,version("beautifulsoup4").split(".")[:2]))<(5,0)'
    try:
        ready = subprocess.run([str(python), "-c", probe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except OSError as error:
        raise LaunchError('가상환경을 실행할 수 없습니다. crawler/.venv를 폴더 밖으로 옮긴 뒤 다시 실행하세요.') from error
    if not ready:
        print("크롤러에 필요한 항목을 설치합니다. 첫 실행에는 인터넷이 필요합니다.", flush=True)
        run_checked([python, "-m", "pip", "install", "-r", crawler / "requirements.txt"], crawler)
    return python


@contextmanager
def launch_lock(name):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    lock = RUNTIME / (name + ".lock")
    # 파일의 PID는 안내용입니다. 실제 잠금은 OS가 관리하며 비정상 종료 시 자동 해제됩니다.
    # 잠금 파일을 삭제하면 다른 실행이 별도 inode를 잠글 수 있으므로 파일은 유지합니다.
    stream = lock.open("a+b")
    try:
        if lock.stat().st_size == 0:
            stream.write(b" ")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise LaunchError("이미 실행 중입니다. 기존 실행 창을 확인하세요.") from error
        try:
            stream.seek(0)
            stream.truncate()
            stream.write(json.dumps({"pid": os.getpid()}).encode("utf-8"))
            stream.flush()
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        stream.close()


def finish(code):
    # Python Launcher로 실행한 창이 바로 닫혀 결과를 못 읽는 상황을 방지합니다.
    if "--no-pause" not in sys.argv and sys.stdin.isatty():
        try:
            input("Enter를 누르면 이 창을 닫습니다. ")
        except (EOFError, KeyboardInterrupt):
            pass
    return code
