"""requests로 HTML을 요청합니다. 일시적 오류에만 제한적으로 재시도합니다."""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests


class FetchError(Exception):
    """요청에 실패한 페이지를 main에 알립니다."""


@dataclass
class FetchedPage:
    url: str
    html: str


class Fetcher:
    def __init__(self, user_agent: str, timeout: float, retries: int = 2,
                 backoff: float = 0.5, max_retry_wait: float = 30):
        self.session = requests.Session()
        # 암묵적인 .netrc 인증이나 시스템 프록시를 사용하지 않습니다.
        self.session.trust_env = False
        self.session.headers.update({"User-Agent": user_agent})
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.max_retry_wait = max_retry_wait
        self.logger = logging.getLogger("crawler.fetcher")

    def _wait_seconds(self, response, attempt: int) -> float:
        """Retry-After가 있으면 우선 적용합니다. 긴 대기는 요청을 중단합니다."""
        delay = self.backoff * 2 ** attempt
        value = response.headers.get("Retry-After") if response is not None else None
        if value:
            try:
                delay = max(0.0, float(value))
            except ValueError:
                try:
                    target = parsedate_to_datetime(value)
                    if target.tzinfo is None:
                        target = target.replace(tzinfo=timezone.utc)
                    delay = max(0.0, (target - datetime.now(timezone.utc)).total_seconds())
                except (ValueError, TypeError, OverflowError):
                    pass
        if delay > self.max_retry_wait:
            raise FetchError("서버가 긴 대기를 요청하여 추가 재시도를 중단했습니다.")
        return delay

    def fetch(self, url: str) -> FetchedPage:
        """GET만 사용하며 인증 실패, 403 등은 재시도하지 않습니다."""
        for attempt in range(self.retries + 1):
            response = None
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                if not response.encoding or response.encoding.lower() == "iso-8859-1":
                    response.encoding = response.apparent_encoding or "utf-8"
                return FetchedPage(url=response.url, html=response.text)
            except requests.RequestException as error:
                status = response.status_code if response is not None else None
                retryable = isinstance(error, (requests.Timeout, requests.ConnectionError)) or status in (429, 500, 502, 503, 504)
                if not retryable or attempt == self.retries:
                    raise FetchError(f"페이지 요청 실패: {url} ({type(error).__name__}, HTTP {status})") from error
                delay = self._wait_seconds(response, attempt)
                self.logger.warning("요청 실패 후 재시도 %s/%s: %s, %.1f초 대기", attempt + 1, self.retries, url, delay)
                time.sleep(delay)
            finally:
                if response is not None:
                    response.close()
        raise FetchError("페이지를 가져오지 못했습니다.")

    def close(self):
        self.session.close()
