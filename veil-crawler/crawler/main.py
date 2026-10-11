"""HTML 수집 → 게시물 추출 → 정규화 → JSONL 저장."""
import argparse
import hashlib
import logging
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import config
from crawler.fetcher import Fetcher, FetchError
from crawler.pagination import next_link, page_url
from crawler.parser import parse_page
from processing.normalizer import normalize_post
from storage.jsonl_writer import JsonlWriter


@dataclass
class Stats:
    pages_crawled: int = 0
    posts_found: int = 0
    warnings: int = 0
    errors: int = 0
    saved_posts: int = 0


class StatsHandler(logging.Handler):
    """이번 실행에서 발생한 경고와 오류만 셉니다."""
    def __init__(self, stats):
        super().__init__()
        self.stats = stats

    def emit(self, record):
        if record.levelno >= logging.ERROR:
            self.stats.errors += 1
        elif record.levelno >= logging.WARNING:
            self.stats.warnings += 1


def setup_logging(stats: Stats):
    config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("crawler")
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    file_handler = RotatingFileHandler(config.LOG_PATH, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(file_handler)
    logger.addHandler(StatsHandler(stats))
    return logger


def arguments(argv=None):
    parser = argparse.ArgumentParser(description="직접 제작한 SNS HTML을 수집하여 JSONL로 저장합니다.")
    parser.add_argument("--url", default=config.START_URL, help="시작 HTML 페이지 주소")
    parser.add_argument("--max-pages", type=int, default=config.MAX_PAGES)
    parser.add_argument("--pagination", choices=("query", "next", "none"), default=config.PAGINATION_MODE)
    parser.add_argument("--output", type=Path, help="저장 경로 (기본: KST 실행 시각을 넣은 JSONL 파일)")
    args = parser.parse_args(argv)
    args.timestamped_output = args.output is None
    if args.timestamped_output:
        args.output = config.timestamped_output_path()
    return args


def validate_settings(args):
    parts = urlsplit(args.url)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.username or parts.password:
        raise ValueError("인증 정보가 없는 HTTP(S) 시작 URL을 지정하세요.")
    if args.max_pages < 1 or config.START_PAGE < 1 or config.TIMEOUT <= 0 or config.RETRIES < 0 or config.REQUEST_DELAY < 0:
        raise ValueError("페이지 수, timeout, retry, 요청 간격 설정을 확인하세요.")
    if not config.SELECTORS.get("post"):
        raise ValueError("SELECTORS['post']는 비어 있을 수 없습니다.")
    probe = BeautifulSoup("", "html.parser")
    for selector in (*config.SELECTORS.values(), *config.REMOVE_TEXT_SELECTORS, *config.TEXT_BREAK_SELECTORS):
        if selector:
            probe.select(selector)  # 잘못된 CSS selector는 수집 전에 발견합니다.
    ZoneInfo(config.DEFAULT_TIMEZONE)


def crawl(args, stats: Stats, logger):
    fetcher = Fetcher(config.USER_AGENT, config.TIMEOUT, config.RETRIES,
                      config.RETRY_BACKOFF, config.MAX_RETRY_WAIT)
    visited_urls, page_hashes, seen_ids = set(), set(), set()
    url = page_url(args.url, config.START_PAGE, config.PAGE_PARAMETER) if args.pagination == "query" else args.url
    try:
        with JsonlWriter(args.output, exclusive=args.timestamped_output) as writer:
            for index in range(args.max_pages):
                if url in visited_urls:
                    logger.warning("페이지 URL이 반복되어 종료합니다: %s", url)
                    break
                visited_urls.add(url)
                logger.info("페이지 수집: %s", url)
                try:
                    page = fetcher.fetch(url)
                except FetchError as error:
                    # 정상 수집된 앞 페이지는 보존합니다. 실패한 페이지 뒤는 시도하지 않습니다.
                    logger.error("%s", error)
                    break
                stats.pages_crawled += 1
                signature = hashlib.sha256(page.html.encode("utf-8")).hexdigest()
                if signature in page_hashes:
                    logger.warning("같은 HTML 페이지가 반복되어 종료합니다: %s", url)
                    break
                page_hashes.add(signature)
                parsed = parse_page(page.html, config.SELECTORS, config.ATTRIBUTES,
                                    config.POST_ID_ATTRIBUTES, config.REMOVE_TEXT_SELECTORS, config.TEXT_BREAK_SELECTORS)
                stats.posts_found += parsed.found
                if not parsed.found:
                    if stats.pages_crawled == 1:
                        logger.warning("HTML에 게시물이 없습니다. selector 또는 서버에서 제공하는 HTML을 확인하세요. requests는 JavaScript를 실행하지 않습니다.")
                    else:
                        logger.info("빈 페이지에 도달하여 종료합니다.")
                    break
                new_posts = 0
                for raw in parsed.posts:
                    if config.DEDUPLICATE_BY_ID and raw.post_id and raw.post_id in seen_ids:
                        logger.info("중복 게시물 제외: %s", raw.post_id)
                        continue
                    try:
                        post = normalize_post(raw, page.url, config.DEFAULT_TIMEZONE)
                    except Exception:
                        logger.exception("게시물 정규화 실패: %s", raw.post_id or "ID 없음")
                        continue
                    # 디스크 저장 오류는 이후 저장도 실패하므로 게시물 오류와 구분하여 종료합니다.
                    writer.write(post)
                    stats.saved_posts += 1
                    new_posts += 1
                    if raw.post_id:
                        seen_ids.add(raw.post_id)
                if config.DEDUPLICATE_BY_ID and parsed.posts and new_posts == 0 and all(raw.post_id and raw.post_id in seen_ids for raw in parsed.posts):
                    logger.warning("새 게시물이 없는 반복 페이지여서 종료합니다.")
                    break
                if args.pagination == "none":
                    break
                if args.pagination == "query":
                    url = page_url(args.url, config.START_PAGE + index + 1, config.PAGE_PARAMETER)
                else:
                    url = next_link(parsed.soup, page.url, config.SELECTORS.get("next_page"),
                                    config.ATTRIBUTES.get("next_page") or "href", config.ALLOW_CROSS_ORIGIN_PAGINATION)
                    if url is None:
                        break
                if index + 1 < args.max_pages:
                    time.sleep(config.REQUEST_DELAY)
    finally:
        fetcher.close()


def print_summary(stats: Stats, output: Path):
    print("\nCrawler finished\n")
    print(f"Pages crawled : {stats.pages_crawled}")
    print(f"Posts found   : {stats.posts_found}")
    print(f"Warnings      : {stats.warnings}")
    print(f"Errors        : {stats.errors}")
    print(f"Saved posts   : {stats.saved_posts}")
    try:
        shown = output.resolve().relative_to(config.PROJECT_ROOT)
    except ValueError:
        shown = output.resolve()
    print(f"\nOutput:\n{shown}")


def main(argv=None) -> int:
    args = arguments(argv)
    stats = Stats()
    logger = setup_logging(stats)
    try:
        validate_settings(args)
        crawl(args, stats, logger)
    except KeyboardInterrupt:
        logger.warning("사용자가 중지했습니다. 저장된 게시물은 유지합니다.")
    except Exception:
        logger.exception("크롤러 실행 중 오류가 발생했습니다.")
    finally:
        print_summary(stats, args.output)
        for handler in logger.handlers:
            handler.flush()
    return 1 if stats.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
