# ANTI_FIMI React 대시보드

사건 후보를 선택하고 해당 사건의 계정 관계·잠정 서사·시간별 확산·경보 근거를 조사하는 화면입니다. React/TypeScript, Cytoscape, ECharts를 사용하며 표시 수치는 `/api/dashboard`의 실제 분석 결과입니다.

## 통합 실행

D4D에서 `py -3.12 .\ANTI_FIMI\server.py`를 실행하고 http://127.0.0.1:8787 을 여세요. 기본 서버는 이 폴더의 `dist/`와 엔진 API를 함께 제공합니다. 새 원시 게시물은 `/api/posts` 또는 형제 폴더의 `ANTI_FIMI_DEMO_DATA/posts/live_posts.jsonl`에서 받습니다. 입력 계약과 한계는 `../ANTI_FIMI/README.md`에 있습니다.

## 개발

```powershell
npm ci
npm run dev
```

API 서버를 함께 실행해야 합니다. 개발 프록시는 127.0.0.1:8787 로 연결합니다. 소스 변경 후 `npm run build` 또는 D4D에서 `powershell -ExecutionPolicy Bypass -File .\ANTI_FIMI\build_dashboard.ps1`로 타입 확인과 빌드를 실행하세요.

화면은 3초마다 조회하고 선택한 사건·근거를 유지합니다. 실패 시 오류와 마지막 성공 결과를 표시하며 가짜 데이터로 대체하지 않습니다. 수집 파일 감시 상태와 화면 조회 연결 상태는 별도로 표시합니다. 동일 공유 패턴은 무방향 점선, 제공된 인용·재공유·댓글 참조는 방향선입니다. 경보·사건 후보만으로 공작·허위성·국가 배후를 확정하지 않습니다.
