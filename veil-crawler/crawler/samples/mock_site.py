"""테스트 HTML 두 페이지를 제공하는 로컬 웹 서버. Ctrl+C로 종료하세요."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SAMPLES = Path(__file__).resolve().parent


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parts = urlsplit(self.path)
        if parts.path in ("/", "/posts"):
            value = parse_qs(parts.query).get("page", ["1"])[0]
            try:
                number = int(value)
            except ValueError:
                self.send_error(400, "Invalid page")
                return
            filename = SAMPLES / f"page{number}.html"
            body = filename.read_bytes() if number in (1, 2) else b"<!doctype html><html><body><p>End of feed</p></body></html>"
            content_type = "text/html; charset=utf-8"
        elif parts.path.startswith("/images/"):
            # 크롤러는 사진 파일을 요청하지 않습니다. 이 SVG는 사람이 볼 때의 예시입니다.
            body = b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100" fill="#438dc4"/><text x="20" y="55" fill="white">Sample image</text></svg>'
            content_type = "image/svg+xml"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Mock SNS: http://127.0.0.1:{args.port}/posts?page=1", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
