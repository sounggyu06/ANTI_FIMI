# D4D / ANTI_FIMI

공개 게시물의 자료 연결과 반복 확산 행동을 분석하고, 분석가가 원문 근거와 대응 절차를 검토하는 해커톤 프로토타입입니다. 로컬 소셜 사이트 **VEIL**, 수집기, Python 분석 엔진, React 대시보드로 구성됩니다. 기본 실행은 LLM·외부 AI API·모델 다운로드·API 키 없이 동작합니다.

이 저장소는 **소스 배포본**입니다. 기존 PC의 수집 자료, DB, 시연 이력과 빌드 결과는 포함하지 않습니다. 아래 순서로 화면을 빌드하고 합성 시나리오를 생성해 재현합니다.

## 구현 기능

- VEIL의 공개 `/posts` HTML에서 게시물 ID, 계정 ID, 시각, 본문, 언어, URL 및 인용·재게시·답글 참조를 수집합니다.
- 동일 URL·관측 원본 참조·동일 문구를 자료 묶음으로 연결합니다. 반복 공동 확산 행동은 별도로 분석하고 계정 관계와 근거 게시물을 표시합니다.
- 원문, 조사망, 자료 묶음, 확산 추세, 실시간 알림, 시연별 기록과 새 시연 초기화를 대시보드에서 제공합니다.
- 포함된 Excel 운용표의 대응 절차를 읽고 지원되는 규칙으로 검토 후보를 연결합니다. 외부 조치는 자동 실행하지 않습니다.
- 소스 추적 화면은 관측 자료 안의 참조·시각을 표시합니다. 이미지 검증 화면은 선택 설치한 C2PA SDK로 출처 메타데이터를 검사합니다.
- VEIL에서 합성 전시·재난구호·공동 행동 시나리오를 생성할 수 있습니다. 실제 X 수집 및 외부 AI 군집 입력은 별도 설정이 필요한 선택 기능입니다.

## 한계

자료 묶음은 의미나 입장 분류가 아닙니다. 기본 모드는 허위성, 악성 계정, 봇 여부, 국가 배후, 최초 유포자를 확정하지 않습니다. 행동 점수는 보정된 확률이 아니며 정상 협업도 검토 후보가 될 수 있습니다. 운용표 40개 유형 전체를 자동 탐지하지 않으며, 기본 모드에서는 유형 17·30 후보를 연결하고 외부 AI 의미 군집이 필요한 유형 22는 중지합니다.

확산 추세에는 최소 10분의 이력이 필요합니다. 짧은 시연의 '자료 축적 중' 표시는 정상입니다. 합성 시나리오와 단위 테스트는 동작 검증이며 실전 오탐·미탐률 평가가 아닙니다. C2PA 기록 유무는 AI 생성 여부나 이미지 내용의 진실성을 보장하지 않습니다. SDK 미설치 시 이미지 검증은 사용 불가 상태를 표시합니다.

두 서버는 로컬 접속을 전제로 하며 인증·공개 서비스 운영 기능은 포함하지 않습니다. 대량 운영을 위한 증분 처리, 보존 정책 및 접근 제어는 별도 작업이 필요합니다.

## 아키텍처

```text
VEIL / 합성 시나리오 (Node.js + React, 127.0.0.1:5180)
  → 공개 /posts HTML
  → Python 수집기 (requests + BeautifulSoup)
  → ANTI_FIMI API / SQLite 원문 저장
      ├─ 자료 연결 → 자료 묶음 / 미연결 원문
      ├─ 반복 행동 → 계정 쌍 신호 / 조사망
      └─ 확산 집계 / Excel 대응 절차 / 관측 출처 추적
  → React 대시보드 (Python 서버 제공, 127.0.0.1:8788)
```

| 경로 | 역할 |
| --- | --- |
| `ANTI_FIMI/` | 엔진, API, SQLite 처리, 운용표 연동, 테스트 |
| `fimi-dashboard/` | 분석 대시보드 소스와 의존성 잠금 파일 |
| `veil-crawler/crawler/` | HTML 수집기와 테스트용 HTML 샘플 |
| `veil-crawler/veil-social/` | 로컬 사이트, 합성 시나리오, 선택 X 연동 |
| `ANTI_FIMI_운용표_v1.0.xlsx` | 대응 절차와 매칭 규칙 |
| `START_ANTI_FIMI.cmd` / `STOP_ANTI_FIMI.cmd` | Windows 통합 실행 / 종료 |

## Windows에서 처음 실행

Python **3.12**(Python Launcher 포함), Node.js **22.13 이상**과 npm이 필요합니다. 설치 시 Python Launcher의 `py -3.12`와 `node`, `npm`을 사용할 수 있어야 합니다. 첫 설치에는 인터넷이 필요합니다. 의존성은 저장소의 잠금 파일로 설치합니다.

저장소를 내려받은 최상위 폴더에서 PowerShell을 열고 실행합니다. 폴더 이름이 `D4D`가 아니어도 하위 구조를 유지하면 됩니다.

```powershell
py -3.12 --version
node --version
npm.cmd --version

# Git에는 dist가 없으므로 통합 실행 전에 대시보드를 빌드합니다.
Push-Location .\fimi-dashboard
npm.cmd ci
npm.cmd run build
Pop-Location

.\START_ANTI_FIMI.cmd
```

통합 실행기는 수집기용 가상환경·라이브러리를 설치하고 VEIL 화면을 자동 빌드합니다. 기본 엔진에는 `ANTI_FIMI/requirements.txt`의 의미 모델 패키지를 설치할 필요가 없습니다.

1. 사이트 `http://127.0.0.1:5180/`와 대시보드 `http://127.0.0.1:8788/`가 열리고 수집 준비가 끝날 때까지 기다립니다.
2. 사이트에서 원하는 시나리오를 시작합니다. 처음에는 실제 수집 게시물 없이 시작합니다.
3. 대시보드에서 원문 유입, 자료 묶음과 계정 관계를 확인합니다. 새 시연은 대시보드의 **새 시연**을 사용한 뒤 사이트에서 다시 시작합니다.
4. 종료는 `STOP_ANTI_FIMI.cmd` 또는 실행 창의 Ctrl+C를 사용합니다.

실행 창을 유지하세요. 사용 중인 포트는 강제 종료하지 않으며, 포트 변경·재시작 안내는 [Windows 통합 실행](README_WINDOWS_CONNECTED.md)을 참고하세요. 자료는 실행하면서 `ANTI_FIMI_DEMO_DATA/`, `veil-crawler/runtime/`에 새로 생성되고 Git에서 제외됩니다.

### 짧은 합성 데이터 데모

위 대시보드 빌드 후, 실시간 사이트 연결 없이 49개 합성 게시물을 확인하려면 최상위 폴더에서 실행합니다.

```powershell
py -3.12 .\ANTI_FIMI\make_fusion_demo.py
py -3.12 .\ANTI_FIMI\server.py --no-watch
```

`http://127.0.0.1:8787/`에서 확인합니다. 생성기는 49개 게시물, 계정 쌍 신호 15개, 조사망 1개와 재입력 중복 제거를 자체 검증합니다. 현재 시각의 실시간 사이트 연결 데모와 별도 DB를 사용합니다.

### 선택: 이미지 C2PA 검증

엔진을 실행하는 Python에만 설치한 뒤 서버를 재시작합니다. 이 PC에서 확인한 SDK 버전은 `0.38.0`입니다.

```powershell
py -3.12 -m pip install c2pa-python==0.38.0
```

이미지는 메모리에서 분석하며 DB에 저장하지 않습니다. 이 기능은 딥페이크 탐지기가 아닙니다. 외부 AI·의미 모델과 X API 연동은 각 하위 문서를 참고하세요. 통합 시연 실행기는 X 토큰을 비워 실제 외부 수집을 자동 시작하지 않습니다.

## 테스트

의존성 설치 후 최상위 폴더에서 실행합니다. 수집기 테스트에는 통합 실행기가 만든 가상환경을 사용합니다.

```powershell
py -3.12 -m unittest discover -s tests -v

Push-Location .\ANTI_FIMI
py -3.12 -m unittest discover -s tests -v
Pop-Location

Push-Location .\fimi-dashboard
node --test tests/*.test.mjs
Pop-Location

Push-Location .\veil-crawler
py -3.12 -m unittest discover -s tests -v
Pop-Location

Push-Location .\veil-crawler\crawler
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
Pop-Location

Push-Location .\veil-crawler\veil-social
npm.cmd test
Pop-Location
```

## 저장소에 포함하지 않는 자료

`.env`와 비밀키, 실제 수집 원문·이미지, 익명 ID 대응표, 모든 SQLite DB, 시연 이력, 로그, 런타임, `node_modules`, 가상환경, `dist`, 백업·과거 패치 설치 도구는 제외합니다. 실제 자료는 기존 PC에 보존됩니다. 재현에 필요한 합성 시나리오, 빈 `data/posts.json`, 테스트 샘플, 운용표와 의존성 잠금 파일은 포함합니다. `fixtures/`의 정답 라벨은 합성 시나리오 평가용이며 수집기 입력으로 사용하지 않습니다.

이미지 샘플은 합성 시나리오 자료로 표시되어 있습니다. 별도 라이선스를 부여하지 않으며 제3자 자료의 사용권은 별도 확인이 필요합니다.

## 해커톤 제출 주소

- **저장소 URL**: 업로드한 GitHub 저장소의 주소입니다.
- **데모 URL**: 외부에서 접속해 실행해 볼 수 있는 배포 주소입니다. `localhost`와 `127.0.0.1`은 제출용 공개 데모 URL이 아닙니다.

이 저장소를 업로드하는 것만으로 데모 서버가 배포되지는 않습니다. 화면만 정적 호스팅하면 Python 분석 API와 실시간 수집은 동작하지 않습니다. 공개 데모에는 합성 데이터만 사용하고 서버 접근 범위를 별도로 정해야 합니다.

### 고정 데모 주소: Render 배포

`Dockerfile`과 `render.yaml`은 **49개 합성 게시물 조회 데모**를 배포합니다. 기존 로컬 서버와 별도인 `deploy_demo.py`를 실행하며 매 시작마다 임시 DB를 새로 만듭니다. 실제 수집 원문·DB·토큰은 이미지에 포함하지 않습니다. 공개 화면에서 조사망·자료·출처·대응 절차를 조회하고 C2PA 이미지를 검사할 수 있습니다. 원문 추가·AI 결과 입력·운용표 재읽기·새 시연 초기화 API는 403으로 차단합니다. 실시간 VEIL 시뮬레이션 전체는 위 Windows 통합 실행으로 제공합니다.

1. 확인된 소스를 GitHub 저장소에 업로드합니다.
2. [Render 대시보드](https://dashboard.render.com/)에서 **New → Web Service**를 선택합니다.
3. 저장소와 `main` 브랜치를 선택합니다. 공개 저장소는 **Public Git Repository** 방식으로 URL을 입력할 수 있습니다. 비공개 저장소는 해당 저장소 읽기 권한을 연결해야 합니다.
4. Language/Runtime은 **Docker**, Dockerfile 경로는 `./Dockerfile`, 인스턴스는 **Free**를 선택합니다. 저장소 루트를 사용하며 Build/Start Command는 별도로 덮어쓰지 않습니다.
5. 배포 완료 후 Render가 표시하는 `https://…onrender.com` 주소를 열고 화면과 `/api/health`를 확인합니다. 이때 실제 발급된 주소를 제출 페이지의 **데모 URL**에 넣습니다.

주소는 서비스가 유지되는 동안 고정되지만 [무료 인스턴스](https://render.com/docs/free)는 15분 동안 요청이 없으면 정지하고, 다음 접속 때 재시작에 약 1분 걸릴 수 있습니다. 재시작 시 동일 합성 데이터를 다시 생성합니다. 계정 한도·서비스 중단·콜드 스타트 때문에 무중단 운영을 보장하지 않습니다. 유료 인스턴스 선택은 별도 비용 승인이 필요합니다.

배포용 서버를 로컬에서 먼저 확인하려면 대시보드 빌드 후 `py -3.12 .\deploy_demo.py`를 실행하고 `http://127.0.0.1:8790/`을 엽니다. 로컬 테스트는 기본적으로 외부 인터페이스에 열지 않습니다. Docker에서는 `DEMO_HOST=0.0.0.0`과 호스팅 플랫폼의 `PORT`로 접속을 받습니다.

상세 엔진 설명은 [ANTI_FIMI README](ANTI_FIMI/README.md), 시연 초기화는 [새 시연 안내](ANTI_FIMI/README_NEW_DEMO.md), 선택 AI 입력은 [AI 계약](ANTI_FIMI/AI_CONTRACT.md)을 참고하세요.
