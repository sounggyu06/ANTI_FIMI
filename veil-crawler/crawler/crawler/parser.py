"""HTML selector를 인자로 받아 게시물별 데이터를 추출합니다."""
import logging
from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from models.post import RawPost


@dataclass
class ParsedPage:
    soup: BeautifulSoup
    found: int
    posts: list[RawPost] = field(default_factory=list)


def element_text(element, remove_selectors, break_selectors) -> str:
    """본문의 태그를 제거하되 HTML 원본을 변경하지 않습니다."""
    if element is None:
        return ""
    fragment = BeautifulSoup(str(element), "html.parser")
    for selector in remove_selectors:
        for unwanted in fragment.select(selector):
            unwanted.decompose()
    for selector in break_selectors:
        for block in fragment.select(selector):
            block.insert_before("\n")
            block.insert_after("\n")
    # Inline 태그 양옆은 이어 붙이고, 문단/줄바꿈만 공백 정리 대상이 됩니다.
    return fragment.get_text("", strip=False).strip()


def read_field(article, key, selectors, attributes, remove_selectors, break_selectors) -> str:
    selector = selectors.get(key)
    attribute = attributes.get(key)
    element = article.select_one(selector) if selector else (article if attribute else None)
    if element is None:
        return ""
    if attribute:
        value = element.get(attribute)
        if value is not None:
            return str(value)
        # datetime 속성이 없는 time 요소는 화면의 시각 텍스트를 사용합니다.
        if key != "created_at":
            return ""
    return element_text(element, remove_selectors, break_selectors)


def parse_article(article, selectors, attributes, id_attributes, remove_selectors, break_selectors=()) -> RawPost:
    """누락된 값은 기본값으로 남깁니다. 분석·판정은 하지 않습니다."""
    values = {key: read_field(article, key, selectors, attributes, remove_selectors, break_selectors)
              for key in ("author_id", "comment", "created_at", "text", "retweet_count", "like_count")}
    post_id = next((str(article.get(name)) for name in id_attributes if article.get(name)), None)
    return RawPost(**values, post_id=post_id)


def parse_page(html: str, selectors: dict, attributes: dict,
               id_attributes=(), remove_selectors=(), break_selectors=()) -> ParsedPage:
    """한 게시물의 파싱 오류는 기록하고 다른 게시물을 계속 처리합니다."""
    logger = logging.getLogger("crawler.parser")
    soup = BeautifulSoup(html, "html.parser")
    articles = soup.select(selectors["post"])
    result = ParsedPage(soup=soup, found=len(articles))
    for index, article in enumerate(articles, start=1):
        try:
            result.posts.append(parse_article(article, selectors, attributes, id_attributes, remove_selectors, break_selectors))
        except Exception:
            logger.exception("게시물 %s 파싱 실패: 다음 게시물을 계속 처리합니다.", index)
    return result
