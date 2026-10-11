import { ChevronDown } from 'lucide-react'
import type { AIClaim, AICluster, EventCase, FusionStatus, Pipeline } from './types'

const count = (value: number) => value.toLocaleString('ko-KR')
const aiLabels: Record<string, string> = { PRO: '명제 지지', CON: '명제 반박', QUESTION: '질문', NEUTRAL: '중립 전달', UNKNOWN: '판단 보류' }
export const aiStanceLabel = (stance: string) => aiLabels[stance] ?? stance
const fusionLabels: Record<FusionStatus, string> = { pending: '군집 대기', partial: '군집 일부 수신', enriched: '군집 수신' }
const scoreLabels: Record<string, string> = { temporal_tightness: '공유 시각 밀집도', recurrence: '공유 반복성', resource_diversity: '공유 자료 다양성', popularity_damping: '대중적 자료 보정', activity_damping: '다량 활동 보정', observed_reciprocity: '관측 상호 참조', observed_internal_fraction: '조사망 내부 참조 비율', reference_resolution_fraction: '원문 연결 확인 비율', graph_support: '관계망 연결 근거', repeated_pair_density: '반복 공유 연결 밀도', synchronization_ratio: '시간 동조 비율', repeated_url_count: '반복 공유 URL 수', shared_url_diversity: '공유 URL 다양성', pair_density: '계정 쌍 연결 밀도', repetition: '반복성', synchrony: '시간 동조', url_diversity: 'URL 다양성', account_count: '관련 계정', episode_count: '독립 공유 횟수', ai_context: 'AI 맥락' }

export function PipelineStatus({ pipeline }: { pipeline: Pipeline }) {
  return <div className="pipeline-status" data-testid="pipeline-status" aria-label="분석 처리 상태">
    <span>행동 집계 <b>{count(pipeline.behavior_post_count)}</b><small> · {pipeline.behavior_window_hours}h</small>{pipeline.behavior_pending_count > 0 && <em>대기 {count(pipeline.behavior_pending_count)}</em>}</span>
    {pipeline.mode === 'no-ai' ? <span>이슈 <b>{count(pipeline.issue_count ?? 0)}</b><small> · AI 미사용</small></span> : <span data-testid="ai-status" title="배정·미배정 결과를 받은 게시물 수">군집 수신 <b>{count(pipeline.ai_received_count)}</b><small> / {count(pipeline.raw_post_count)}</small>{pipeline.ai_pending_count > 0 && <em>대기 {count(pipeline.ai_pending_count)}</em>}</span>}
  </div>
}

export function ClusterCard({ cluster }: { cluster: AICluster }) {
  return <article className="ai-claim-card"><strong>{cluster.label}</strong><code>{cluster.source_cluster_id}</code><code>{cluster.cluster_id}</code>{typeof cluster.membership_strength === 'number' && <span>군집 소속도 {cluster.membership_strength.toFixed(3)}</span>}</article>
}

export function ClaimCard({ claim }: { claim: AIClaim }) {
  return <article className="ai-claim-card"><span className={`stance-tag ai-stance ${claim.stance}`}>{aiStanceLabel(claim.stance)}</span><p>{claim.claim_text}</p><details><summary>모델 값 · 연결 ID</summary>{typeof claim.confidence === 'number' && Number.isFinite(claim.confidence) && <span>모델 값 {claim.confidence.toFixed(3)} · 확률 보정 미검증</span>}<code>{claim.claim_id}</code>{claim.cluster_id && <code>{claim.cluster_id}</code>}</details></article>
}

export function FusionOverview({ event }: { event: EventCase }) {
  const alert = event.alerts.find(item => item.kind === 'behavior_coordination')
  const context = event.ai_context ?? alert?.ai_context
  const status = event.fusion_status ?? alert?.fusion_status
  const score = event.network_score ?? alert?.network_score
  const components = event.score_components ?? alert?.score_components ?? {}
  return <details className="fusion-overview">
    <summary>행동 지표 상세 {event.analysis_mode !== 'no-ai' && status && <span>{fusionLabels[status]}</span>}<ChevronDown size={13} /></summary>
    <div className="fusion-body">
      <dl className="metrics-detail"><div><dt>규칙 기반 행동 지표</dt><dd>{typeof score === 'number' ? `${score.toFixed(1)}점` : '미산출'}</dd></div><div><dt>세부 행동 신호</dt><dd>{count(event.child_alert_ids?.length ?? 0)}개</dd></div>{Object.entries(components).map(([key, value]) => <div key={key}><dt>{scoreLabels[key] ?? key}</dt><dd>{value === null ? '미산출' : Number.isInteger(value) ? value : value.toFixed(3)}</dd></div>)}</dl>
      {event.analysis_mode !== 'no-ai' && <div className="fusion-context"><h3>연결 군집 <span>{context ? `${count(context.analyzed_post_count)} / ${count(context.total_post_count)}개 근거 수신` : '대기'}</span></h3>{context && <>
        {Object.keys(context.stance_counts).length > 0 && <div className="stance-counts">{Object.entries(context.stance_counts).map(([stance, value]) => <span className={`stance-tag ai-stance ${stance}`} key={stance}>{aiStanceLabel(stance)} {count(value)}</span>)}</div>}
        {(context.clusters?.length ?? 0) > 0 && <div className="fusion-claims">{context.clusters!.map(cluster => <ClusterCard key={cluster.cluster_id} cluster={cluster} />)}</div>}
        {context.claims.length > 0 && <div className="fusion-claims">{context.claims.map((claim, i) => <ClaimCard key={`${claim.claim_id}-${claim.stance}-${i}`} claim={claim} />)}</div>}
        {Boolean(context.unassigned_post_count) && <p>미배정 근거 {context.unassigned_post_count}개</p>}
      </>}</div>}
    </div>
  </details>
}
