"""사이트 주소와 HTML 구조가 바뀌면 이 파일만 수정하세요."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent
START_URL = "http://127.0.0.1:5173/posts"  # 기존 VEIL 시뮬레이터의 현재 게시물 HTML
USER_AGENT = "VeilLocalCrawler/1.0 (owned-site testing)"
TIMEOUT = 10  # requests의 연결/읽기 timeout, 초 단위
RETRIES = 2  # 최초 요청 실패 후 추가 시도 횟수
RETRY_BACKOFF = 0.5
MAX_RETRY_WAIT = 30  # Retry-After가 이보다 길면 요청을 중단합니다.
REQUEST_DELAY = 0.2

# query: ?page=1,2,3 / next: 다음 페이지 링크 / none: 시작 페이지만
PAGINATION_MODE = "none"  # VEIL /posts는 현재 피드를 한 응답에 제공합니다.
PAGE_PARAMETER = "page"
START_PAGE = 1
MAX_PAGES = 10
ALLOW_CROSS_ORIGIN_PAGINATION = False
DEDUPLICATE_BY_ID = True

SELECTORS = {
    "post": "article.post",
    "author_id": None,
    "comment": None,
    "text": ".post-content",
    "created_at": "time.post-time",
    "like_count": ".like-count",
    "retweet_count": None,
    "next_page": "a.next-page",
}
# None은 선택한 요소의 텍스트를 읽습니다. 필요한 경우 속성명을 지정합니다.
ATTRIBUTES = {
    "author_id": "data-author-id",
    "comment": "data-comment",
    "text": None,
    "created_at": "datetime",
    "like_count": None,
    "retweet_count": "data-reposts",
    "next_page": "href",
}
POST_ID_ATTRIBUTES = ("data-post-id", "id")  # 중복 제거용, JSONL에는 저장 안 함
REMOVE_TEXT_SELECTORS = ("script", "style", "template")
TEXT_BREAK_SELECTORS = ("br", "p", "div", "li", "h1", "h2", "h3", "blockquote")
DEFAULT_TIMEZONE = "Asia/Seoul"  # 시간대 없는 작성 시각에만 적용
OUTPUT_PATH = PROJECT_ROOT / "output" / "raw_posts.jsonl"
LOG_PATH = PROJECT_ROOT / "logs" / "crawler.log"


def timestamped_output_path(now=None):
    """실행 시각(KST)을 넣어 매번 별도 결과 파일을 만듭니다."""
    current = (now or datetime.now(ZoneInfo("Asia/Seoul"))).astimezone(ZoneInfo("Asia/Seoul"))
    stamp = current.strftime("%Y%m%d_%H%M%S_%f")
    return OUTPUT_PATH.with_name(f"{OUTPUT_PATH.stem}_{stamp}{OUTPUT_PATH.suffix}")
