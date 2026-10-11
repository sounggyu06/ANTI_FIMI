"""원시 추출 값과 최종 JSONL 데이터 모델."""
from dataclasses import dataclass


@dataclass
class RawPost:
    """HTML에서 읽은 값. 숫자와 날짜는 정규화 전 문자열입니다."""
    author_id: str = ""
    comment: str = ""
    created_at: str | None = None
    text: str = ""
    retweet_count: str = ""
    like_count: str = ""
    post_id: str | None = None


@dataclass
class Post:
    """최종 파일에는 요청한 6개 필드만 기록합니다."""
    author_id: str = ""
    comment: str = "false"  # JSON boolean이 아니라 요청한 문자열입니다.
    created_at: str | None = None
    text: str = ""
    retweet_count: int = 0
    like_count: int = 0
