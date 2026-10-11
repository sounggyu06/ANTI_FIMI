# ANTI_FIMI AI 군집 수신 계약

AI 담당 범위는 **다국어 의미 기반 게시물 군집화**입니다. 명제 추출, 입장 분류, GPT 요약, 공작 판정은 필수가 아닙니다. 사이트 원문은 행동 엔진과 AI가 공유하며, 행동 탐지는 AI 결과와 독립적으로 실행됩니다.

## 원문 받기

`GET /api/ai/pending?limit=100&after_seq=0`

각 items 항목은 seq, post_id, raw_sha256, raw를 제공합니다. 받은 post_id와 raw_sha256을 그대로 돌려보내세요. 해시 생성·군집 배정 외 판정은 AI 모듈에서 수행할 필요가 없습니다. next_after_seq로 다음 페이지를 요청하고 다음 폴링 주기에는 0부터 미완료 글을 다시 확인합니다.

## 군집 결과 보내기

`POST /api/ai/results`, `Content-Type: application/json`

```json
{
  "results": [{
    "post_id": "site-post-001",
    "raw_sha256": "원문 조회 API가 제공한 값",
    "model_version": "실제 군집 모델/설정 버전",
    "scope_id": "군집 ID가 유효한 실행 또는 지속 세션 ID",
    "revision": 1,
    "cluster_id": "content_0003"
  }]
}
```

**AI가 계산할 핵심 값은 게시물별 cluster_id입니다.** 나머지 필드는 원문 연결·재시도·버전 관리를 위한 정보입니다. 이미 받은 JSONL/ZIP에는 원문 해시와 실행 ID를 붙이는 어댑터가 제공됩니다.

- cluster_id: 비어 있지 않은 문자열. 미배정이면 null입니다. 미배정도 결과 수신 완료로 기록하고 원문은 보존합니다.
- cluster_label: 선택 문자열. 없으면 실제 군집 ID를 제목에 표시합니다. 프로그램이 내용 요약을 만들지 않습니다.
- membership_strength: 선택 숫자0~1/null. 군집 소속도이며 악성 확률이나 입장 신뢰도가 아닙니다. 모델이 제공하지 않으면 생략하세요.
- model_version/scope_id가 다른 같은 군집 ID는 서로 다른 군집입니다. 지속 스트림에서는 ID 범위를 팀 내에서 합의하세요.
- revision은 게시물별 양의 정수입니다. 같은 revision+동일 결과는 중복 처리하고, 같은 revision의 다른 결과나 낮은 revision은 거부합니다. 재분류는 revision을 높여 새 cluster_id 또는 null을 보냅니다.
- 원문 ID/해시 불일치와 잘못된 필드는 배열 전체를 원자적으로 거부합니다. 원문은 먼저 저장되어야 합니다.

## 우리 엔진의 처리

군집별 게시물·계정·시간별 게시량과 반복 행동 근거를 연결합니다. 같은 계정들의 여러 군집 가담도 전역 행동 분석에서 확인합니다. 군집 확산 경보는 주장과 반박을 포함할 수 있는 **군집 전체 게시량**이며, 주장 확산·허위성·공작을 확정하지 않습니다. 입장을 추측해서 만들지 않습니다.

기존 claims/stance 형태는 저장 데이터와의 호환을 위해 선택 지원하지만 AI 팀원의 요구사항이 아닙니다. cluster_id와 legacy claims를 같은 결과 객체에 동시에 넣지는 않습니다.

## 팀원 ZIP

성공한 실행의 전달용 ZIP은 다음 **두 파일만** 포함합니다. ZIP의 최상위 폴더명은 `ANTI_FIMI`입니다.

```text
ANTI_FIMI/
  manifest.json
  posts.jsonl
```

`posts.jsonl`은 미분류를 포함한 전체 게시물입니다. 각 줄에 원문 `post_id`, `author_id`, 시간대가 있는 `created_at`, `text`, `content_cluster_id`가 필요합니다. 군집 ID가 없으면 명시적으로 `null`을 넣습니다. 키 누락을 미분류로 간주하지 않습니다. 원문에 존재하는 URL·참조·메타데이터는 보존하세요. `content_assignment.membership_strength`는 선택 값이며 유한한 0~1 또는 null입니다.

`manifest.json` 예시:

```json
{
  "schema_version": 1,
  "bundle_format": "ANTI_FIMI_CLUSTER_INPUT_V1",
  "run_id": "고유한-실행-ID",
  "status": "complete",
  "stages": {"clustering": "complete"},
  "cluster_id_scope": "run_id + cluster_id",
  "post_count": 116,
  "embedding": {"model_name": "BAAI/bge-m3"},
  "cluster_counts": {"content": 17, "unassigned": 29},
  "posts_sha256": "posts.jsonl 파일의 실제 바이트 SHA-256"
}
```

숫자는 이번 자료의 예시이므로 매 실행마다 실제 집계로 바꾸세요. 군집 수는 null을 제외한 고유 ID 수입니다. `posts_sha256`은 저장을 마친 파일에서 계산합니다. `input_sha256`을 추가한다면 과거 원본 스냅샷의 출처 정보이며, 전달된 게시물 파일 검증에는 사용하지 않습니다. 해시는 파일 손상·변경 확인용이며 발신자 인증은 아닙니다. `created_at`, `generated_post_id_scope`는 출처 정보로 선택 보존합니다.

전달에서 제외: `embeddings.npy`, `behavior_features.npy`, `author_features.npz`, `embedding_rows.npy`, `feature_schema.json`, `accounts.jsonl`, `account_clusters.json`, `coordination_edges.jsonl`, `input.jsonl`, `posts_base.jsonl`, `clustering_result.json`, `content_clusters.json`, `unassigned.jsonl`, `narratives.json`, 군집별 `cluster.json`/`posts.jsonl`/`analysis.json`/`narrative.md` 및 해당 폴더. 벡터는 AI 내부 파일이고, 행동 특징·계정 관계는 우리 엔진이 계산합니다. 미분류 글은 루트 posts.jsonl에 남기므로 별도 unassigned 파일이 필요 없습니다. GPT 요약·판정은 필수 입력이 아닙니다.

`analysis_errors.json`은 오류가 없는 성공 실행에서만 전달에서 제외합니다. 불완전 실행이나 비어 있지 않은 오류 파일은 정리 도구가 거부합니다. AI 측의 원본·학습·재현 파일은 내부 보관하고 전달물에서만 제외하세요.

기존 전체 ZIP을 두 파일로 정리하고 수신하는 방법(D4D에서 실행):

```powershell
py -3.12 .\ANTI_FIMI\pack_ai_bundle.py --input "기존 전체 ZIP 경로" --output .\ANTI_FIMI_DEMO_DATA\ai_inbox\ANTI_FIMI_AI_INPUT.zip
py -3.12 .\ANTI_FIMI\import_team_raw.py --input .\ANTI_FIMI_DEMO_DATA\ai_inbox\ANTI_FIMI_AI_INPUT.zip
```

정리 도구는 원본 ZIP을 수정하지 않고 posts.jsonl의 바이트·ID·군집 배정을 그대로 보존합니다. 따라서 이번 기존 자료의 내부 `narrative_annotations` 등도 남지만 분석 입력으로 사용하지 않습니다. 이미 저장된 같은 ID의 원문 필드를 지우거나 바꾸면 원문 불변성 검증에 걸립니다. 새 게시물은 필요한 원문 필드와 군집 배정만 전달하면 됩니다.

수신기는 새 posts 해시와 건수·고유 ID·군집 수·미분류 수를 검사합니다. 기존 전체 ZIP도 input 해시 검증을 유지하여 읽습니다. 기존 GPT 파일은 있다면 참고본으로만 보관하며 없어도 동작합니다. 이번 정리본은 116개 원문, 17개 군집의 배정87개, 미배정29개를 포함합니다.
