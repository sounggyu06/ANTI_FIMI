import { useState } from 'react'
import type { PlaybookStatus, Post, ResponsePlan, ScenarioType } from './types'

const phaseName: Record<string, string> = { detect: '근거 보존', verify: '사실 확인', trace: '확산 추적', respond: '대응·인계', integrate: '평가·종료' }
const ownerName = (value: string) => value.replace(/DOMAIN_OWNER/g, '업무 담당자').replace(/ANALYST/g, '분석관').replace(/REVIEWER/g, '검토 책임자')
const authorityName: Record<string, string> = { internal_review: '내부 검토', human_selected_external_action_not_automatic: '권한 있는 담당자가 외부 조치 여부 결정 · 자동 실행 없음' }
const contextName: Record<string, string> = { question: '질문 표현', denial: '반박·부인 표현', quoted: '인용·전언 표현' }
type TermHit = { post_id: string; matched_terms: string[][]; context_markers: string[] }
function termHits(plan: ResponsePlan): TermHit[] {
  const matches = plan.observations.matches as { observations: { term_hits?: TermHit[] } }[] | undefined
  return matches?.flatMap(match => match.observations.term_hits ?? []) ?? []
}

export function WorkbookStatus({ status, onApplied }: { status?: PlaybookStatus; onApplied: () => Promise<void> }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function reload() {
    setBusy(true); setError(null)
    try {
      const response = await fetch('/api/playbook/reload', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', signal: AbortSignal.timeout(20000) })
      if (!response.ok) throw new Error(`운용표 재읽기 오류 (${response.status})`)
      await onApplied()
    } catch (caught) { setError(caught instanceof Error ? caught.message : '운용표를 다시 읽지 못했습니다.') }
    finally { setBusy(false) }
  }
  return <div className={`playbook-status ${status?.status === 'error' || error ? 'invalid' : ''}`} data-testid="playbook-status">
    <span>{status?.status === 'ready' ? `운용표 ${status.scenario_count}개 유형 · 운용표 규칙 ${status.effective_enabled_rule_count ?? status.enabled_rule_count}개 · 문구 검토 규칙 ${status.review_rule_count ?? 0}개` : status?.error ?? '운용표 미적용'}</span>
    {Boolean(status?.disabled_rule_ids?.length) && <span title={status?.disabled_rule_ids?.join(' · ')}>다국어 의미 규칙 중지</span>}
    {status?.workbook_hash && <code title={status.workbook_hash}>기준 {status.workbook_hash.slice(0, 10)}</code>}
    <button disabled={busy} onClick={() => void reload()}>{busy ? '재평가 중…' : '운용표 재읽기'}</button>
    {status?.review_error && <span role="alert">{status.review_error}</span>}
    {error && <span role="alert">{error}</span>}
  </div>
}

export default function ResponsePlans({ plans = [], posts }: { plans?: ResponsePlan[]; posts: Post[] }) {
  if (!plans.length) return null
  const indexed = new Map([...posts, ...plans.flatMap(p => p.evidence_posts ?? [])].map(p => [p.id, p]))
  return <section className="response-panel panel" data-testid="response-plans">
    <div className="panel-heading"><h2>대응 절차 <span className="subtle-number">{plans.length}</span></h2><span className="response-caution">후보 연결 · 외부 조치 자동 실행 없음</span></div>
    {plans.map((plan, index) => <details className="response-plan" key={plan.id} open={index === 0}>
      <summary><strong>ID {plan.scenario_id} · {plan.observable_label ?? plan.title}</strong><span>후보 · 위험도 미평가</span></summary>
      <p className="response-reason">{plan.reason}</p>
      {plan.cross_case && <p>다른 이슈에도 걸친 후보입니다. 아래에 전체 근거를 표시합니다.</p>}
      <p>관측: {plan.evidence_level === 'combined' ? '관련 표현과 반복 행동 경보의 게시물 중첩' : plan.evidence_level === 'behavior_observation' ? '반복 행동' : '관련 표현'} · 선전 여부 미검증</p>
      {Boolean(plan.missing_checks?.length) && <div className="response-verification"><b>추가 확인 자료</b><ul>{plan.missing_checks?.map(check => <li key={check}>{check}</li>)}</ul></div>}
      <div className="response-verification"><b>우선 확인</b><p>{plan.next_verification}</p></div>
      <details className="response-evidence"><summary>매칭 근거 게시물 {plan.evidence_post_ids.length}개</summary>
        {plan.evidence_post_ids.map(pid => <article key={pid}><code>{pid}</code>{indexed.get(pid) && <p>{indexed.get(pid)?.text}</p>}{termHits(plan).filter(hit => hit.post_id === pid).map((hit, hitIndex) => <p key={hitIndex}>일치 문구: {hit.matched_terms.flat().join(' · ')}{hit.context_markers.length > 0 && <> / 표현 단서: {hit.context_markers.map(marker => contextName[marker] ?? marker).join(' · ')} (입장 판정 아님)</>}</p>)}</article>)}
        <details><summary>규칙 원시 근거</summary><pre>{JSON.stringify(plan.observations, null, 2)}</pre></details>
      </details>
      <ol className="response-steps">{plan.actions.map(step => <li key={step.order}>
        <details open={step.order <= 2}><summary><b>{step.order}. {phaseName[step.phase] ?? step.phase}</b><span>{ownerName(step.owner)}</span></summary>
          <p>{step.action}</p><dl>
            <div><dt>착수 조건</dt><dd>{step.precondition}</dd></div>
            <div><dt>산출물</dt><dd>{step.output}</dd></div>
            <div><dt>완료 확인</dt><dd>{step.done_when}</dd></div>
            <div><dt>권한 경계</dt><dd>{authorityName[step.authority] ?? step.authority}</dd></div>
          </dl>
        </details>
      </li>)}</ol>
      <details className="response-provenance"><summary>적용 기준</summary><p>규칙 {plan.rule_id} · 분석 기준 {plan.as_of}</p><p>운용표 <code>{plan.workbook_hash}</code></p>{plan.review_rules_hash && <p>문구 규칙 <code>{plan.review_rules_hash}</code></p>}<p>유형의 참고 잠재등급: {plan.potential_risk}. 현재 사건의 위험도·허위성·의도는 평가하지 않았습니다. 각 단계는 착수 조건과 권한 확인 후 담당자가 수행합니다.</p></details>
    </details>)}
  </section>
}

export function ScenarioCatalog({ catalog, candidates }: { catalog: ScenarioType[]; candidates: ResponsePlan[] }) {
  const matched = new Map(candidates.map(plan => [plan.scenario_id, plan]))
  const [sid, setSid] = useState<string | null>(null)
  const selected = candidates.find(plan => plan.scenario_id === sid)
  if (!catalog.length) return null
  return <section className="scenario-catalog" data-testid="scenario-catalog">
    <details><summary>시나리오 검토 · {candidates.length}개 유형 후보 / 운용표 {catalog.length}개 유형</summary>
      <p>후보는 선전·허위·위조의 확정 판정이 아닙니다. 질문·반박도 관련 표현으로 연결될 수 있습니다.</p>
      <div className="scenario-candidate-shortcuts">{candidates.map(plan => <button key={plan.id} onClick={() => setSid(sid === plan.scenario_id ? null : plan.scenario_id)}>ID {plan.scenario_id} · {plan.observable_label ?? plan.title} · 근거 {plan.evidence_post_ids.length}개</button>)}</div>
      <div className="scenario-types">{catalog.map(item => <div className="scenario-type" key={item.scenario_id}>
        <strong>ID {item.scenario_id} · {item.title}</strong>
        <span>{matched.has(item.scenario_id) ? `검토 후보 · 근거 ${matched.get(item.scenario_id)?.evidence_post_ids.length}개` : item.match_mode === 'manual' ? '추가 자료·수동 확인' : '관측 후보 없음'}</span>
        <details><summary>{item.match_mode === 'behavior' ? '행동 관측 규칙' : item.match_mode === 'text_review' ? '관련 문구 검토 규칙' : '외부 검증 필요'}</summary><p>{item.observable_label}</p><p>필요 근거: {item.required_evidence.join(' · ')}</p><p>다음 확인: {item.next_verification}</p><ul>{item.missing_inputs.map(check => <li key={check}>{check}</li>)}</ul>
        {!matched.has(item.scenario_id) && <ol>{item.actions.map(step => <li key={step.order}>{step.action}</li>)}</ol>}</details>
        {matched.has(item.scenario_id) && <button onClick={() => setSid(sid === item.scenario_id ? null : item.scenario_id)}>근거·대응 절차 보기</button>}
      </div>)}</div>
      {selected && <ResponsePlans plans={[selected]} posts={selected.evidence_posts ?? []} />}
    </details>
  </section>
}
