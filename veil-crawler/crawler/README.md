# VEIL 시뮬레이터 HTML 크롤러

requests + BeautifulSoup으로 기존 VEIL 시뮬레이션 트위터의 `/posts` HTML을 수집하고 `output/raw_posts_YYYYMMDD_HHMMSS_ffffff.jsonl`에 저장합니다. AI 분석·가짜뉴스 판정·임베딩·브라우저 자동화는 하지 않습니다.

## 이번 배포본의 실제 자료

동봉된 veil-social의 `data/imported-x/`에 사용자가 제공한 JSONL 7개와 사진 파일 69개가 들어 있습니다. 시뮬레이터를 시작하면 같은 원문 ID를 합쳐 113개 실제 게시물이 표시되고, 시나리오 시작 후 가상 글도 추가됩니다. 이 크롤러는 현재 피드 전체를 수집합니다.

사진은 시뮬레이터에서 표시하지만, 요청한 6필드 JSONL에는 이미지 항목을 넣지 않습니다. 원본에 좋아요·재게시·댓글 구분 정보가 없어 출력에서는 기본값 `like_count=0`, `retweet_count=0`, `comment="false"`를 사용합니다. 실제 반응 수가 0이라고 확인한 것이 아닙니다. 원본 파일은 시뮬레이터의 데이터 폴더에 그대로 보존합니다.

## 간편 실행

상위 폴더에서 `run_web.py`를 먼저 실행하고 창을 켜둔 뒤 `run_crawler.py`를 실행하세요. 설치를 자동 처리하고 웹이 선택한 포트를 자동 사용합니다. Windows에서는 `start_web.cmd` → `start_crawler.cmd` 순서로 더블 클릭하면 됩니다. 크롤러는 현재 피드를 한 번 수집하고 실행 시각(KST)을 파일명에 넣어 별도 파일로 저장합니다. 이전 결과는 유지됩니다. 탐지 엔진과의 지속 수집 연결은 상위 `run_connected.py`를 사용합니다.

아래는 실행 파일 없이 개별 설정을 사용하는 수동 실행 방법입니다. 웹이 다른 포트로 실행 중이면 main.py의 --url에 해당 주소의 /posts 경로를 지정하세요.

## 수동 실행 방법

Node.js 22.13 이상과 Python 3.10 이상을 사용합니다. 두 프로그램은 같은 컴퓨터에서 실행하세요.

첫 번째 터미널에서 `veil-social` 폴더로 이동합니다.

```bash
npm ci
npm run build
npm start
```

브라우저에서 http://127.0.0.1:5173/ 를 열고 시나리오 시작을 누릅니다. 서버를 수정했다면 실행 중인 기존 서버를 Ctrl+C로 종료한 뒤 수정본으로 재시작하세요.

두 번째 터미널에서 `crawler` 폴더로 이동합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

설치는 한 번만 하면 됩니다. 다음부터는 `.venv/bin/python main.py`로 수집합니다. Windows에서는 `.venv/bin/python`을 `.venv\Scripts\python.exe`로 바꾸세요.

결과는 `main.py` 위치 기준 `output/raw_posts_YYYYMMDD_HHMMSS_ffffff.jsonl`에 저장됩니다. 한 번 실행할 때 현재 피드 전체를 수집하며 실행 시각(KST)을 파일명에 넣어 이전 파일을 유지합니다. 예: `raw_posts_20261011_021530_123456.jsonl`. 끝의 6자리는 마이크로초입니다. 특정 경로를 지정하려면 다음 옵션을 사용하세요. 명시한 경로가 이미 존재하면 해당 파일은 덮어씁니다.

```bash
.venv/bin/python main.py --output output/run_02.jsonl
```

## JSONL 출력 양식

아래 순서의 **6개 필드만** 저장하며 한 게시물이 한 줄입니다. UTF-8, ensure_ascii=False로 저장합니다.

```jsonl
{"author_id":"user_001","comment":"false","created_at":"2026-10-10T14:00:00+09:00","text":"게시글 본문","retweet_count":3,"like_count":12}
```

| 필드 | 자료형 | 의미 / 누락 시 |
|---|---|---|
| author_id | 문자열 | 공개 익명 계정 ID(authorId/anonymous_user_id). 누락은 "" |
| comment | 문자열 | 댓글/답글 게시물이면 "true", 일반 글/의견 재게시는 "false" |
| created_at | ISO 8601 문자열 또는 null | 작성 시각, 없거나 해석 불가하면 null |
| text | 문자열 | 본문 HTML 태그 제거, 공백·줄바꿈 정리. 누락은 "" |
| retweet_count | 정수 | 해당 게시물의 서버 재게시 수(reposts). 누락은 0 |
| like_count | 정수 | 해당 게시물의 서버 좋아요 수(likes). 누락은 0 |

`comment`는 JSON boolean false가 아니라 **문자열 "false"**입니다. 댓글 수나 진위 판정 값이 아닙니다. 현재 시뮬레이터는 댓글 게시물 생성 기능이 없으므로 생성 글은 "false"입니다. 댓글 수가 많거나 리트윗 원문이 있다는 이유로 "true"로 처리하지 않습니다. 이후 서버가 `comment=true`, `isReply=true`, 또는 `replyTo`를 제공하면 HTML에 "true"로 표현됩니다.

웹이 제공하는 고정 익명 계정 ID를 그대로 저장합니다. 원본 X 작성자 ID는 웹 HTML에 노출하지 않습니다. 숫자형 원래 ID도 문자열로 기록합니다. 예전 출력의 account_name/title/content/images/retweet_original은 포함하지 않습니다. 사진 다운로드도 하지 않습니다.

반응 수의 `1,253`, `1.2K`, `2.3K`, `1M`은 각각 1253, 1200, 2300, 1000000으로 변환합니다. 소문자 k/m, B, 만/억도 지원하며 잘못된 값은 경고 후 0입니다. 원본 작성 시각의 시간대는 유지하고 시간대가 없는 경우 Asia/Seoul을 적용합니다. 날짜만 있으면 날짜 ISO 문자열을 유지합니다.

## 설정과 selector 변경

`config.py`에서 주소·요청·페이지 이동·selector·속성·출력·로그 경로를 바꿉니다. 기본 연결은 다음과 같습니다.

```python
START_URL = "http://127.0.0.1:5173/posts"
PAGINATION_MODE = "none"
```

`/`는 JavaScript로 표시되는 트위터 화면입니다. `/posts`는 **같은 Node 서버, 같은 posts.json**의 현재 피드를 HTML로 보여주는 수집 경로입니다. 새 테스트 사이트를 사용할 필요가 없습니다. 현재 화면용 피드만 수집하며 전체 누적 X DB 내보내기는 시뮬레이터의 기존 export 기능을 사용합니다.

| 대상 | SELECTORS | ATTRIBUTES |
|---|---|---|
| 게시물 | article.post | 해당 없음 |
| author_id | None (게시물 자체) | data-author-id |
| comment | None (게시물 자체) | data-comment |
| created_at | time.post-time | datetime |
| text | .post-content | None (본문 텍스트) |
| retweet_count | None (게시물 자체) | data-reposts |
| like_count | .like-count | None (요소 텍스트) |
| 다음 페이지 | a.next-page | href |

예를 들어 다른 사이트가 `.writer-id` 텍스트와 `.retweet-count` 요소를 제공한다면:

```python
SELECTORS["author_id"] = ".writer-id"
ATTRIBUTES["author_id"] = None
SELECTORS["retweet_count"] = ".retweet-count"
ATTRIBUTES["retweet_count"] = None
```

parser.py에 selector를 하드코딩하지 않습니다. 게시물 ID는 `POST_ID_ATTRIBUTES`에서 읽어 실행 중 중복을 제거하며 최종 JSONL에는 추가하지 않습니다.

```bash
.venv/bin/python main.py --url "http://127.0.0.1:5173/posts" --pagination none
.venv/bin/python main.py --max-pages 1
```

`query`는 page 번호, `next`는 다음 HTML 링크, `none`은 현재 한 응답을 수집합니다. 기본 VEIL은 전체 피드를 한 응답에서 읽으므로 none을 사용합니다. requests는 JavaScript, 무한 스크롤, 로그인·CAPTCHA·차단 우회를 수행하지 않습니다.

## 프로젝트 구조와 역할

```text
crawler/
├── main.py                   실행 제어·통계
├── config.py                 연결·selector·출력 설정
├── crawler/
│   ├── fetcher.py             HTTP 요청·timeout·제한된 retry
│   ├── parser.py              HTML 필드 추출
│   └── pagination.py          페이지 이동
├── processing/normalizer.py   ID·댓글 여부·본문·시각·반응 수 정리
├── storage/jsonl_writer.py    UTF-8 한 게시물당 한 줄 저장
├── models/post.py             RawPost / 최종 6필드 Post dataclass
├── output/raw_posts_YYYYMMDD_HHMMSS_ffffff.jsonl     수집 결과
├── logs/crawler.log           실행 로그
├── samples/                  선택형 단위 검증 사이트
├── tests/test_crawler.py      자동 테스트
├── requirements.txt
├── README.md
└── VALIDATION.md
```

## 오류 처리와 검증

계정 ID 누락, 잘못된 날짜·숫자·댓글 여부는 로그에 경고를 남기고 기본값을 저장합니다. 게시물 하나의 파싱·정규화 오류는 해당 게시물만 제외하고 다음 게시물로 진행합니다. 페이지 요청이나 파일 저장이 최종 실패하면 실행을 중단합니다.

`logs/crawler.log`에 상세 오류를 저장하고 실행 후 페이지 수·발견 수·경고·오류·저장 수를 출력합니다. 정상 또는 경고만 있는 실행은 종료 코드 0, 오류가 있는 실행은 1입니다. 연결·timeout·429·서버 오류에만 제한된 retry를 적용하며 Retry-After를 존중합니다.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

샘플 사이트 검증을 원하는 경우 첫 터미널에서 `.venv/bin/python samples/mock_site.py`, 다른 터미널에서 아래 명령을 실행합니다. 기본 사용 대상은 기존 VEIL 서버입니다.

```bash
.venv/bin/python main.py --url "http://127.0.0.1:8765/posts?page=1" --pagination query
```
