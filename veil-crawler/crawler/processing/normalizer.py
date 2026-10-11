"""계정 ID·댓글 여부·본문·작성 시각·반응 수를 정리합니다. 내용 판정은 하지 않습니다."""
import logging
import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from models.post import Post, RawPost

logger = logging.getLogger("crawler.normalizer")


def clean_text(value) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def parse_count(value, field_name="좋아요") -> int:
    """153, 1,253, 1.2K, 2.3K, 1M을 정수로 변환합니다."""
    text = unicodedata.normalize("NFKC", clean_text(value))
    if not text:
        return 0
    text = re.sub(r"\s+", "", text).replace(",", "")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([KMB만억]?)\+?", text, re.IGNORECASE)
    if not match:
        logger.warning("%s 수를 해석할 수 없어 0 사용: %r", field_name, value)
        return 0
    multipliers = {"": 1, "K": 1000, "M": 1000000, "B": 1000000000, "만": 10000, "억": 100000000}
    try:
        return int(Decimal(match.group(1)) * multipliers[match.group(2).upper()])
    except (ValueError, InvalidOperation, OverflowError):
        logger.warning("%s 수 변환 실패, 0 사용: %r", field_name, value)
        return 0


def parse_like_count(value) -> int:
    return parse_count(value, "좋아요")


def normalize_comment(value) -> str:
    """댓글 여부를 요청한 문자열 true/false로 기록합니다."""
    text = clean_text(value).lower()
    if text in ("", "false", "0"):
        return "false"
    if text in ("true", "1"):
        return "true"
    logger.warning("댓글 여부를 해석할 수 없어 문자열 false 사용: %r", value)
    return "false"


def normalize_time(value, default_timezone: str = "Asia/Seoul") -> str | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        # 날짜만 있으면 시각을 임의로 만들어 넣지 않습니다.
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        timestamp = None
        for format_string in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y.%m.%d %H:%M"):
            try:
                timestamp = datetime.strptime(text, format_string)
                break
            except ValueError:
                continue
        if timestamp is None:
            logger.warning("작성 시각을 해석할 수 없어 null 사용: %r", value)
            return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=ZoneInfo(default_timezone))
    return timestamp.isoformat()


def normalize_post(raw: RawPost, page_url: str, default_timezone: str = "Asia/Seoul") -> Post:
    """출력 순서와 자료형을 고정합니다. page_url은 기존 호출 계약을 유지합니다."""
    post = Post(
        author_id=clean_text(raw.author_id),
        comment=normalize_comment(raw.comment),
        created_at=normalize_time(raw.created_at, default_timezone),
        text=clean_text(raw.text),
        retweet_count=parse_count(raw.retweet_count, "재게시"),
        like_count=parse_like_count(raw.like_count),
    )
    if not post.author_id:
        logger.warning("계정 ID 누락: 빈 문자열 사용 (게시물 %s)", raw.post_id or "ID 없음")
    return post
