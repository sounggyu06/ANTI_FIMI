"""현재 저장 데이터와 12개 재현 가능한 시나리오의 시간 품질 보고서를 생성합니다."""
import subprocess
from launcher_utils import ROOT, LaunchError, ensure_node, finish, process_env, launch_lock


def main():
    try:
        with launch_lock('time-report'):
            node, _ = ensure_node()
            args = [node, 'report-temporal.mjs']
            data = ROOT / 'runtime' / 'web-data'
            if (data / 'posts.json').is_file():
                args += ['--runtime-dir', str(data)]
            return subprocess.run(args, cwd=ROOT / 'veil-social', env=process_env()).returncode
    except (LaunchError, OSError) as error:
        print(f'실행 안내: {error}')
        return 1


if __name__ == '__main__':
    raise SystemExit(finish(main()))
