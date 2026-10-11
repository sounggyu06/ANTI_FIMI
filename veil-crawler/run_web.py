"""웹만 실행: 필요한 준비를 자동 처리하고 브라우저를 엽니다."""
import argparse
import json
import subprocess
import sys
import time
import uuid
import webbrowser

from launcher_utils import (ROOT, RUNTIME, WEB_INFO, LaunchError, active_web, available_port,
                            ensure_node, ensure_build, fetch_json, finish, launch_lock, process_env, read_json)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=5173)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--no-pause', action='store_true')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    server = None
    session_id = None
    try:
        existing = active_web()
        if existing:
            print("이미 실행 중인 웹을 엽니다.")
            if not args.no_browser:
                webbrowser.open(existing["url"])
            return 0
        with launch_lock("web"):
            node, npm = ensure_node()
            ensure_build(npm)
            port = available_port(args.port)
            session_id = str(uuid.uuid4())
            url = f"http://127.0.0.1:{port}/"
            # 웹 런타임을 프로젝트별로 분리하여 다른 실행 중인 시뮬레이터를 초기화하지 않습니다.
            env = process_env()
            env.update(PORT=str(port), VEIL_SESSION_ID=session_id,
                       VEIL_DATA_DIR=str(RUNTIME / "web-data"),
                       VEIL_ARCHIVE_DIR=env.get("VEIL_ARCHIVE_DIR") or str(RUNTIME / "archive"),
                       X_BEARER_TOKEN="")
            log_path = RUNTIME / "web.log"
            with log_path.open("a", encoding="utf-8") as log:
                server = subprocess.Popen([node, "server.mjs"], cwd=ROOT / "veil-social", env=env,
                                          stdout=log, stderr=subprocess.STDOUT,
                                          creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                try:
                    for _ in range(300):
                        if server.poll() is not None:
                            raise LaunchError(f"웹 실행에 실패했습니다. {log_path}을 확인하세요.")
                        try:
                            if fetch_json(url + "api/health").get("sessionId") == session_id:
                                break
                        except (OSError, ValueError):
                            pass
                        time.sleep(0.1)
                    else:
                        raise LaunchError("웹 서버가 준비되지 않았습니다. 다시 실행하세요.")
                    WEB_INFO.write_text(json.dumps({"url": url, "port": port, "pid": server.pid,
                                                   "session_id": session_id, 'project_root': str(ROOT.resolve())}), encoding="utf-8")
                    print(f"웹 실행 완료: {url}\n시나리오는 시작 버튼을 눌러야 시작합니다.\n이 창은 켜두세요. 종료하려면 Ctrl+C를 누르세요.", flush=True)
                    if not args.no_browser:
                        webbrowser.open(url)
                    server.wait()
                    return 0 if server.returncode == 0 else 1
                finally:
                    if server.poll() is None:
                        server.terminate()
                        try:
                            server.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            server.kill()
                            server.wait()
                    if read_json(WEB_INFO).get("session_id") == session_id:
                        WEB_INFO.unlink(missing_ok=True)
    except KeyboardInterrupt:
        print("\n웹을 종료했습니다.")
        return 0
    except (LaunchError, OSError, ValueError) as error:
        print(f"실행 안내: {error}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(finish(main()))
