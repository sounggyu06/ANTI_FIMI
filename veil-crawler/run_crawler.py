"""크롤러만 실행: 현재 run_web.py 웹의 게시물을 한 번 수집합니다."""
import subprocess

from launcher_utils import ROOT, LaunchError, active_web, ensure_python, finish, launch_lock, process_env


def main():
    try:
        with launch_lock("crawler"):
            info = active_web()
            if not info:
                raise LaunchError("먼저 같은 폴더의 run_web.py를 실행하고 웹 창을 켜두세요.")
            python = ensure_python()
            # 포트가 바뀌어도 웹 실행 파일이 기록한 같은 서버에 연결됩니다.
            url = info["url"] + "posts"
            print(f"현재 웹 게시물을 수집합니다: {url}", flush=True)
            result = subprocess.run([str(python), "main.py", "--url", url, "--pagination", "none"],
                                    cwd=ROOT / "crawler", env=process_env())
            if result.returncode == 0:
                print("크롤링 결과를 위 Output 경로에 저장했습니다.", flush=True)
            return result.returncode
    except KeyboardInterrupt:
        print("\n크롤링을 중지했습니다.")
        return 0
    except (LaunchError, OSError) as error:
        print(f"실행 안내: {error}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(finish(main()))
