"""Public, read-only synthetic demo. Never opens the local project's databases."""
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'ANTI_FIMI'))
from engine import stamp
from make_fusion_demo import BASE, demo_posts
from server import Runtime, RawOnlyEmbedder, make_handler
from datetime import timedelta


def public_handler(runtime, static_dir):
    class PublicHandler(make_handler(runtime, static_dir)):
        timeout = 15

        def do_POST(self):
            if urlsplit(self.path).path == '/api/media/verify':
                return super().do_POST()
            self.close_connection = True
            self.send_json(403, {'error': '공개 합성 데모는 조회 전용입니다. 수집·초기화는 로컬 실행에서 사용할 수 있습니다.'})

    return PublicHandler


def main():
    port = int(os.environ.get('PORT', '8790'))
    host = os.environ.get('DEMO_HOST', '127.0.0.1')
    source_static = ROOT / 'fimi-dashboard/dist'
    if not (source_static / 'index.html').is_file():
        raise SystemExit('먼저 fimi-dashboard에서 npm ci 및 npm run build를 실행하세요.')
    with tempfile.TemporaryDirectory(prefix='anti-fimi-public-') as directory:
        temporary = Path(directory)
        db = temporary / 'synthetic.sqlite3'
        runtime = Runtime(db, RawOnlyEmbedder(db), no_ai=True)
        runtime.ingest(demo_posts(), stamp(BASE + timedelta(hours=6)))
        static = temporary / 'static'
        shutil.copytree(source_static, static)
        index = static / 'index.html'
        banner = ('<div style="background:#17202c;color:#fff;padding:10px;text-align:center;font:14px sans-serif">'
                  '공개 합성 데모 · 49개 가상 게시물 · 조회 및 이미지 C2PA 검증 가능 · 실시간 수집·초기화는 로컬 실행에서 제공</div>')
        index.write_text(index.read_text(encoding='utf-8').replace('<body>', '<body>' + banner, 1), encoding='utf-8')
        with ThreadingHTTPServer((host, port), public_handler(runtime, static)) as server:
            print(f'Public synthetic demo: http://{host}:{server.server_port}', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == '__main__':
    main()
