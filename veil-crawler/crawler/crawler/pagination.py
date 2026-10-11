"""번호형 페이지와 다음 페이지 링크를 처리합니다."""
import logging
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


def page_url(start_url: str, number: int, parameter: str = "page") -> str:
    """다른 query 값을 보존하며 page 값만 변경합니다."""
    parts = urlsplit(start_url)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != parameter]
    query.append((parameter, str(number)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def next_link(soup, current_url: str, selector: str | None, attribute: str = "href",
              allow_cross_origin: bool = False) -> str | None:
    if not selector:
        return None
    element = soup.select_one(selector)
    value = element.get(attribute) if element else None
    if not value:
        return None
    try:
        target = urljoin(current_url, str(value))
        parts, current = urlsplit(target), urlsplit(current_url)
    except ValueError:
        logging.getLogger("crawler.pagination").warning("다음 페이지 URL 형식이 잘못되어 종료합니다.")
        return None
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        logging.getLogger("crawler.pagination").warning("유효하지 않은 다음 페이지 링크를 제외했습니다.")
        return None
    if not allow_cross_origin and (parts.scheme, parts.netloc.lower()) != (current.scheme, current.netloc.lower()):
        logging.getLogger("crawler.pagination").warning("다른 출처의 다음 페이지 링크를 제외했습니다.")
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
