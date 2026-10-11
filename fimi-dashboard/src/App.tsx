import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, ArrowDownRight, ArrowRight, Check, CheckCheck, ChevronDown, CircleDot, Clock3, ExternalLink, FileText, Fingerprint, FolderOpen, Globe2, Info, Layers3, Link2, ListFilter, Network, Radio, RefreshCw, Search, Shield, SlidersHorizontal, Users, X } from 'lucide-react'
import NetworkGraph from './NetworkGraph'
import type { Selection } from './NetworkGraph'
import Timeline from './Timeline'
import type { DashboardData, Edge, EventCase, Post, ResponsePlan } from './types'
import ResponsePlans, { WorkbookStatus, ScenarioCatalog } from './ResponsePlans'
import { aiStanceLabel, ClaimCard, ClusterCard, FusionOverview, PipelineStatus } from './FusionPanels'
import LiveAlerts, { useLiveAlerts } from './LiveAlerts'
import { entityKey } from './liveAlertState'
import type { SignalTarget } from './liveAlertState'
import SourceTracePanel from './SourceTrace' // ANTI_FIMI_SOURCE_TRACE_V1
import SpreadOverview from './SpreadOverview'
import NewDemo from './NewDemo'
import MediaVerify from './MediaVerify' // ANTI_FIMI_C2PA_UI_V1
import './App.css'
import './BlackTheme.css'

const number = (value: number) => value.toLocaleString('ko-KR')
const dateTime = (value: string | null, short = false, seconds = false) => {
  if (!value || Number.isNaN(Date.parse(value))) return '미관측'
  return new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit', ...(short ? {} : { year: 'numeric' }), hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}), hour12: false }).format(new Date(value))
}
const stanceLabels: Record<string, string> = { supports: '주장·지지', support: '주장·지지', asserts: '주장·지지', refuting: '반박', refutes: '반박', refute: '반박', denies: '반박', questions: '질문', question: '질문', reports: '전달', mentions: '언급', unclear: '불명확', uncertain: '질문·인용·불확실', unmarked: '명시 표지 없음', unknown: '미분석' }
const stanceLabel = (hint: string | null) => hint && ['PRO', 'CON', 'QUESTION', 'NEUTRAL', 'UNKNOWN'].includes(hint) ? aiStanceLabel(hint) : hint === '_pending' ? '군집 대기' : hint === '_clustered' ? '군집 배정' : hint === '_received_empty' ? '군집 미배정' : stanceLabels[hint ?? ''] ?? hint ?? '미분석'
const postStances = (post: Post, source: EventCase['source']) => post.ai_status === 'disabled' ? ['unmarked'] : post.ai_status === 'pending' ? ['_pending'] : post.ai_status === 'received' || source === 'ai' ? post.ai_claims?.length ? post.ai_claims.map(claim => claim.stance) : post.ai_clusters?.length ? ['_clustered'] : ['_received_empty'] : source === 'behavior' ? ['_pending'] : [post.stance_hint ?? 'unmarked']
const edgeLabel = (kind: Edge['kind']) => ({ co_share: '반복 공동 공유', quotes: '인용', reposts: '재공유', replies_to: '댓글' }[kind])
const priorityLabel = (priority: string) => priority === 'review_high' || priority === 'high' ? '우선 검토' : priority === 'none' ? '경보 없음' : '검토 필요'
const metricLabels: Record<string, string> = { linked_post_count: '연결 근거 게시물', current_post_count: '현재 60초 게시물', current_account_count: '현재 60초 계정', first_triggered_at: '최초 조건 충족 시각', peak_window_start: '최다 확산창 시작', peak_window_end: '최다 확산창 종료', distinct_resources: '공유 자료 수', median_timing_lag_seconds: '공유 시각차 중앙값(초)', observed_internal_references: '조사망 내부 원문 참조', unresolved_references: '원문 미확인 참조', network_score: '행동 검토 지표', episode_count: '독립 공유 횟수', independent_episodes: '독립 공유 횟수', current_count: '해당 시간 게시물', current_posts: '해당 시간 게시물', baseline_mean: '직전 평균', baseline_counts: '직전 시간대 게시물', baseline_hours: '기준 시간대', fold_change: '평균 대비 배수', ratio: '평균 대비 배수', z_score: '표준화 편차', z: '표준화 편차', window_seconds: '공유 간격 기준(초)', account_count: '관련 계정', post_count: '게시물 수', shared_url: '공유 URL', url: '공유 URL' }



function PostCard({ post, focused, source, testId = 'evidence-post' }: { post: Post; focused?: boolean; source?: EventCase['source']; testId?: string }) {
  const received = post.ai_status === 'received' || (source === 'ai' && post.ai_status !== 'pending')
  const pending = post.ai_status !== 'disabled' && !received && (post.ai_status === 'pending' || source !== 'local_preview')
  const claims = received ? post.ai_claims ?? [] : []
  const clusters = received ? post.ai_clusters ?? [] : []
  return <article data-testid={testId} className={`post-card ${focused ? 'focused' : ''}`}>
    <div className="post-head"><span className="avatar">{post.account_id.replace(/.*:/, '').slice(0, 2).toUpperCase()}</span><div className="post-author"><strong title={post.account_id}>{post.account_id}</strong><time dateTime={post.created_at}>{dateTime(post.created_at, true, true)} KST</time></div>{post.language && <span className="language-tag">{post.language.toUpperCase()}</span>}</div>
    <p className="post-text">{post.text || '(본문 없음)'}</p>
    {post.urls.length > 0 && <div className="post-links">{[...new Set(post.urls)].map(url => /^https?:\/\//i.test(url) ? <a href={url} key={url} target="_blank" rel="noopener noreferrer"><Link2 size={11} /><span>{url}</span><ExternalLink size={10} /></a> : <span key={url}>{url}</span>)}</div>}
    <div className="post-foot"><span className={`stance-tag ${pending ? 'ai-pending' : received ? 'ai-received' : ''}`}>{post.ai_status === 'disabled' ? '입장·허위성 미분석' : pending ? '군집 대기' : received ? clusters.length ? clusters.map(cluster => cluster.source_cluster_id).join(' · ') : claims.length ? '분석 수신' : '군집 미배정' : '로컬 분석'}</span></div>
    <details className="post-provenance"><summary>원문 정보 <ChevronDown size={11} /></summary><code>{post.id}</code>{post.issue_matches?.map(match => <div key={match.rule_id}><span>{match.source === 'direct' ? `이슈 분류 어휘: ${match.matched_terms.join(' · ')}` : `원본 참조로 분류: ${match.target_post_id}`}</span><code>{match.rule_id}</code></div>)}{clusters.map(cluster => <ClusterCard key={cluster.cluster_id} cluster={cluster} />)}{claims.map((claim, i) => <ClaimCard key={`${claim.claim_id}-${claim.stance}-${i}`} claim={claim} />)}</details>
  </article>
}

function Inspector({ event, selection, onSelect }: { event: EventCase; selection: Selection; onSelect: (selection: Selection) => void }) {
  const [query, setQuery] = useState('')
  const [stance, setStance] = useState('all')
  useEffect(() => { setQuery(''); setStance('all') }, [event.id, selection.kind, selection.id])
  const alert = selection.kind === 'alert' ? event.alerts.find(item => item.id === selection.id) : undefined
  const edge = selection.kind === 'edge' ? event.network.edges.find(item => item.id === selection.id) : undefined
  const narrative = selection.kind === 'narrative' ? event.narratives.find(item => item.id === selection.id) : undefined
  const account = selection.kind === 'account' ? event.network.nodes.find(item => item.id === selection.id) : undefined
  const ids = alert?.evidence_post_ids ?? edge?.evidence_post_ids ?? narrative?.evidence_post_ids
  const relatedPosts = (alert?.evidence_posts ?? event.posts).filter(post => ids ? ids.includes(post.id) : account ? post.account_id === account.id : true).sort((a, b) => a.created_at.localeCompare(b.created_at))
  const filtered = relatedPosts.filter(post => (stance === 'all' || postStances(post, event.source ?? 'local_preview').includes(stance)) && `${post.text} ${post.account_id} ${post.id} ${post.urls.join(' ')}`.toLowerCase().includes(query.toLowerCase()))
  const stances = [...new Set(relatedPosts.flatMap(post => postStances(post, event.source ?? 'local_preview')))]
  const urls = [...new Set(relatedPosts.flatMap(post => post.urls))]
  const title = alert ? alert.label : edge ? edgeLabel(edge.kind) : account ? account.label : narrative ? narrative.label : event.source === 'behavior' ? '원문 전체' : '원문 전체'
  return <aside className="inspector panel">
    <div className="panel-heading"><div><h2><Fingerprint size={17} />근거 확인</h2></div><span className="count-badge">{number(relatedPosts.length)}</span></div>
    <div className="inspector-body">
      {selection.kind !== 'case' && <div className="inspect-context"><div className="context-row"><span className="pill outlined">{selection.kind === 'account' ? '선택 계정' : selection.kind === 'alert' ? '선택 경보' : selection.kind === 'edge' ? '선택 관계' : '선택 군집'}</span><button className="text-button" onClick={() => onSelect({ kind: 'case', id: event.id })}>전체 근거 <X size={12} /></button></div><h3>{title}</h3>{alert && <p>{alert.summary}</p>}{alert?.cross_issue && <p>여러 이슈에 걸친 경보입니다. 아래에는 다른 이슈를 포함한 경보 전체 원문 근거를 표시합니다.</p>}
        {edge && <div className="edge-detail"><span>{edge.source}</span>{edge.kind === 'co_share' ? <Link2 size={14} /> : <ArrowRight size={14} />}<span>{edge.target}</span><b>{edge.kind === 'co_share' ? '추론 패턴 · 방향 없음' : '관측 관계 · 방향 있음'}</b></div>}
      </div>}
      {alert && <section className="inspector-section"><h4><CircleDot size={13} />탐지 근거</h4><div className="reason-list">{alert.reason_labels.map((reason, i) => <div key={`${i}-${reason}`}><CheckCheck size={14} /><span>{reason}</span></div>)}</div><dl className="metrics-detail">{Object.entries(alert.metrics).map(([key, value]) => <div key={key}><dt>{metricLabels[key] ?? key}</dt><dd>{Array.isArray(value) ? value.join(' · ') : typeof value === 'number' ? Number.isInteger(value) ? number(value) : value.toFixed(2) : /^\d{4}-\d{2}-\d{2}T/.test(value) ? `${dateTime(value, true, true)} KST` : value}</dd></div>)}</dl>{alert.episodes && alert.episodes.length > 0 && <div className="episode-list"><h5>반복 공유 시각</h5>{alert.episodes.map((episode, i) => <div key={`${episode.start}-${i}`}><span className="episode-no">{String(i + 1).padStart(2, '0')}</span><span>{dateTime(episode.start, true, true)}<small>~ {dateTime(episode.end, true, true)} KST</small></span><span className="pill">{episode.post_ids.length}개</span></div>)}</div>}<details className="technical-details"><summary>경보 ID · reason_codes <ChevronDown size={12} /></summary><p className="mono">{alert.id}</p>{alert.reason_codes.map(code => <code key={code}>{code}</code>)}</details></section>}
      {urls.length > 0 && <details className="inspector-section shared-urls"><summary><Link2 size={13} />공유 URL <span>{urls.length}</span><ChevronDown size={12} /></summary>{urls.slice(0, 6).map(url => /^https?:\/\//i.test(url) ? <a key={url} href={url} target="_blank" rel="noopener noreferrer"><span>{url}</span><ExternalLink size={12} /></a> : <span key={url}>{url}</span>)}{urls.length > 6 && <small>외 {urls.length - 6}개</small>}</details>}
      <section className="inspector-section evidence-section"><h4><FileText size={13} />원문 게시물 <span>{number(filtered.length)} / {number(relatedPosts.length)}</span></h4><div className="search-field compact"><Search size={13} /><input aria-label="근거 게시물 검색" placeholder="본문 · 계정 · URL 검색" value={query} onChange={event => setQuery(event.target.value)} /></div>{stances.length > 1 && <div className="stance-filter"><ListFilter size={12} /><select aria-label="군집 처리 상태 필터" value={stance} onChange={event => setStance(event.target.value)}><option value="all">모든 처리 상태</option>{stances.map(hint => <option value={hint} key={hint}>{stanceLabel(hint)}</option>)}</select></div>}<div className="posts-list">{filtered.map(post => <PostCard key={post.id} post={post} source={event.source ?? 'local_preview'} focused={Boolean(alert)} />)}{filtered.length === 0 && <div className="inline-empty">조건에 맞는 근거 게시물이 없습니다.</div>}</div></section>
    </div>
  </aside>
}

function RelationshipList({ edges, selection, onSelect }: { edges: Edge[]; selection: Selection; onSelect: (selection: Selection) => void }) {
  if (!edges.length) return null
  return <details className="relationship-list"><summary>관계 목록으로 보기 <span>{edges.length}개</span><ChevronDown size={12} /></summary><div>{edges.map(edge => <button data-testid="relation-card" key={edge.id} className={selection.kind === 'edge' && selection.id === edge.id ? 'selected' : ''} onClick={() => onSelect({ kind: 'edge', id: edge.id })}><span>{edge.source} {edge.kind === 'co_share' ? '—' : '→'} {edge.target}</span><small>{edgeLabel(edge.kind)} · {edge.kind === 'co_share' ? '추론 패턴' : '관측 관계'}</small></button>)}</div></details>
}

function EventWorkspace({ event, selection, onSelect }: { event: EventCase; selection: Selection; onSelect: (selection: Selection) => void }) {
  const [view, setView] = useState<'network' | 'narratives'>('network')
  const currentAlert = event.alerts.find(alert => selection.kind === 'alert' && alert.id === selection.id)
  const currentEdge = event.network.edges.find(edge => selection.kind === 'edge' && edge.id === selection.id)
  const currentNarrative = event.narratives.find(item => selection.kind === 'narrative' && item.id === selection.id)
  const highlightedNodes = currentAlert?.account_ids ?? (currentEdge ? [currentEdge.source, currentEdge.target] : selection.kind === 'account' ? [selection.id] : currentNarrative ? [...new Set(event.posts.filter(post => currentNarrative.evidence_post_ids.includes(post.id)).map(post => post.account_id))] : [])
  const highlightedEdges = currentAlert ? event.network.edges.filter(edge => edge.alert_ids.includes(currentAlert.id)).map(edge => edge.id) : currentEdge ? [currentEdge.id] : selection.kind === 'account' ? event.network.edges.filter(edge => edge.source === selection.id || edge.target === selection.id).map(edge => edge.id) : []
  const graphNodes = event.network.nodes.map(node => ({ id: node.id, label: node.label, postCount: node.post_count, alertCount: event.alerts.filter(alert => alert.account_ids.includes(node.id)).length }))
  const graphEdges = event.network.edges.map(edge => ({ id: edge.id, source: edge.source, target: edge.target, kind: edge.kind, weight: edge.weight, observed: edge.kind !== 'co_share' }))
  const coShareCount = event.network.edges.filter(edge => edge.kind === 'co_share').length
  const observedCount = event.network.edges.length - coShareCount
  const partial = event.hourly.some(point => point.partial)
  const behavior = event.source === 'behavior'
  const noAI = event.source === 'resource' || event.source === 'issue' || event.analysis_mode === 'no-ai'
  const localPreview = !event.source || event.source === 'local_preview'
  const aiContext = event.ai_context ?? event.alerts.find(alert => alert.kind === 'behavior_coordination')?.ai_context
  return <>
    <div className="workbench-center">
      <section className="event-heading">
        <div className="event-title-row"><h1>{event.title}</h1><span className={`priority-pill ${event.priority}`}>{priorityLabel(event.priority)}</span></div>
        <div className="event-meta"><span>{behavior ? '행동 조사망' : event.source === 'issue' ? '이슈 분류' : noAI ? '자료 묶음' : localPreview ? '로컬 분석' : 'AI 군집'}</span><span><Users size={12} />계정 {number(event.account_count)}</span><span><FileText size={12} />게시물 {number(event.post_count)}</span>{behavior && !noAI && <span>내용 군집 {aiContext && aiContext.analyzed_post_count > 0 ? number(aiContext.clusters?.length ?? new Set(aiContext.claims.map(claim => claim.cluster_id)).size) : '대기'}</span>}{behavior && typeof event.network_score === 'number' && <span title="규칙 기반 검토 지표. CIB 확률이 아닙니다.">행동 지표 {event.network_score.toFixed(1)}점</span>}{event.languages.length > 0 && <span><Globe2 size={12} />{event.languages.map(language => language.toUpperCase()).join(' · ')}</span>}</div>
        <div className="event-time"><Clock3 size={12} />{dateTime(event.first_seen, true, true)} — {dateTime(event.last_seen, true, true)} KST</div>
      </section>
      <section className="network-panel panel"><div className="panel-heading"><div><h2><Network size={16} />계정 관계</h2></div><div className="view-switch" role="group" aria-label="시각화 선택"><button data-testid="view-tab" aria-pressed={view === 'network'} className={view === 'network' ? 'active' : ''} onClick={() => setView('network')}><Network size={13} />계정</button><button data-testid="view-tab" aria-pressed={view === 'narratives'} className={view === 'narratives' ? 'active' : ''} onClick={() => setView('narratives')}><Layers3 size={13} />{noAI ? '자료 연결' : behavior ? '내용 군집' : localPreview ? '로컬 서사' : '내용 군집'}</button></div></div>
        {view === 'network' ? <>{event.network.edges.length > 0 && <NetworkGraph nodes={graphNodes} edges={graphEdges} selection={selection} highlightedNodes={highlightedNodes} highlightedEdges={highlightedEdges} onSelect={onSelect} />}<div className="network-footer"><span><b>{observedCount}</b> 관측 관계 <i /> <b>{coShareCount}</b> 공동 공유</span></div><div className="account-pills" aria-label="계정 선택">{event.network.nodes.map(node => <button key={node.id} className={selection.kind === 'account' && selection.id === node.id ? 'selected' : ''} onClick={() => onSelect({ kind: 'account', id: node.id })}><span className="tiny-node" />{node.label}<small>{node.post_count}</small></button>)}</div><RelationshipList edges={event.network.edges} selection={selection} onSelect={onSelect} /></> : <div className="narrative-grid">{event.narratives.map((narrative, i) => <button data-testid="narrative-card" className={`narrative-card ${selection.kind === 'narrative' && selection.id === narrative.id ? 'selected' : ''}`} key={narrative.id} onClick={() => onSelect({ kind: 'narrative', id: narrative.id })}><div><span className="narrative-index">{String(i + 1).padStart(2, '0')}</span><span className={`stance-tag ${narrative.stance_hint ?? ''}`}>{narrative.kind === 'resource' ? '자료 연결' : narrative.kind === 'cluster' ? '의미 군집' : stanceLabel(narrative.stance_hint)}</span></div><h3>{narrative.label}</h3><div className="narrative-bottom"><span>{number(narrative.post_count)}개 게시물</span><ArrowRight size={15} /></div></button>)}{event.narratives.length === 0 && <div className="inline-empty">{noAI ? '연결 자료 묶음 없음' : behavior && (!aiContext || aiContext.analyzed_post_count === 0) ? '수신된 군집 없음' : '연결된 군집 없음'}</div>}</div>}
      </section>
      <SourceTracePanel trace={event.source_trace} onAccount={id => onSelect({ kind: 'account', id })} />
      <MediaVerify caseId={event.id} />
      {behavior && <FusionOverview event={event} />}
      <ResponsePlans plans={event.response_plans} posts={event.posts} />
      <section className="timeline-panel panel"><div className="panel-heading"><div><h2><Activity size={16} />시간별 확산</h2></div><div className="timeline-legend"><span><i />게시물</span><span><i className="baseline" />직전 6시간 평균</span></div></div>{event.hourly.length ? <Timeline points={event.hourly} /> : <div className="inline-empty">시간대별 자료가 없습니다.</div>}<div className="chart-note"><Clock3 size={11} />한국 표준시(KST) · {partial ? '진행 중 시간대 포함' : '시간별 집계'}</div></section>
      <section className="alerts-panel panel"><div className="panel-heading"><div><h2><Radio size={16} />{behavior ? '세부 행동 신호' : '검토 경보'} <span className="subtle-number">{event.alert_count}</span></h2></div></div><div className="alert-list">{event.alerts.map(alert => <button data-testid="alert-card" key={alert.id} onClick={() => onSelect({ kind: 'alert', id: alert.id })} className={`alert-row ${selection.kind === 'alert' && selection.id === alert.id ? 'selected' : ''}`}><span className={`alert-symbol ${alert.kind}`}>{alert.kind === 'behavior_coordination' ? <Network size={16} /> : alert.kind === 'repeated_url_coshare' ? <Link2 size={16} /> : <Activity size={16} />}</span><span className="alert-description"><strong>{alert.label}<span className="mini-priority">{alert.kind === 'resource_burst' ? alert.phase === 'active' ? '확산 중' : '발생 이력' : priorityLabel(alert.priority)}</span></strong><span>{alert.summary}</span><small>{alert.account_ids.length}개 계정 · 근거 {alert.evidence_post_ids.length}개</small></span><ArrowDownRight size={17} /></button>)}</div></section>
      <details className="basis-details"><summary><Info size={13} />분석 상세 <ChevronDown size={13} /></summary><p className="mono">{event.id}</p><p>{event.summary}</p><ul>{event.basis.map((basis, i) => <li key={i}>{basis}</li>)}</ul></details>
    </div>
    <Inspector event={event} selection={selection} onSelect={onSelect} />
  </>
}

function UnlinkedPosts({ posts, plans, noAI, alertCases = [], onOpen }: { posts: Post[]; plans?: ResponsePlan[]; noAI: boolean; alertCases?: EventCase[]; onOpen: (event: EventCase) => void }) {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('all')
  const filtered = posts.filter(post => (noAI || status === 'all' || (status === 'received' ? post.ai_status === 'received' : post.ai_status !== 'received')) && `${post.text} ${post.account_id} ${post.id} ${post.urls.join(' ')}`.toLowerCase().includes(query.toLowerCase())).sort((a, b) => b.created_at.localeCompare(a.created_at))
  return <section className="unlinked-workspace panel">
    <ResponsePlans plans={plans} posts={posts} />{alertCases.length > 0 && <section className="inspector-section"><h3>이슈 미분류 경보</h3>{alertCases.map(event => <button className="alert-row" key={event.id} onClick={() => onOpen(event)}>{event.title} · 경보 {event.alert_count}건 <ArrowRight size={14} /></button>)}</section>}
    <div className="panel-heading"><div><h2><FileText size={16} />{noAI ? '이슈 미분류 게시물' : '미배정·대기 게시물'} <span className="subtle-number">{number(posts.length)}</span></h2></div></div>
    <div className="unlinked-controls"><div className="search-field"><Search size={15} /><input aria-label="미연결 게시물 검색" placeholder="원문 · 계정 · URL 검색" value={query} onChange={event => setQuery(event.target.value)} /></div>{!noAI && <select aria-label="미연결 게시물 처리 상태" value={status} onChange={event => setStatus(event.target.value)}><option value="all">모든 처리 상태</option><option value="pending">군집 대기</option><option value="received">수신 · 미배정</option></select>}<span>{number(filtered.length)}개 표시</span></div>
    <div className="unlinked-grid">{filtered.map(post => <PostCard key={post.id} post={post} testId="unlinked-post" />)}</div>
    {!filtered.length && <div className="inline-empty">{posts.length ? '조건에 맞는 게시물이 없습니다.' : '내용 사건에 연결되지 않은 원문이 없습니다.'}</div>}
  </section>
}

type Workspace = 'behavior' | 'content' | 'unlinked'

export default function App() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [caseIds, setCaseIds] = useState<Record<'behavior' | 'content', string | null>>({ behavior: null, content: null })
  const [search, setSearch] = useState('')
  const [onlyAlerts, setOnlyAlerts] = useState(false)
  const [selection, setSelection] = useState<Selection>({ kind: 'case', id: '' })
  const live = useLiveAlerts(data)
  const inFlight = useRef(false)
  const mounted = useRef(true)
  const requestGeneration = useRef(0)
  const resetting = useRef(false)
  const displayedSession = useRef<string | undefined>(undefined)
  const refresh = useCallback(async () => {
    if (inFlight.current || resetting.current) return
    const generation = requestGeneration.current
    inFlight.current = true
    setBusy(true)
    try {
      const response = await fetch('/api/dashboard', { cache: 'no-store', signal: AbortSignal.timeout(12000) })
      if (!response.ok) throw new Error(`조회 서버 응답 오류 (${response.status})`)
      const next = await response.json() as DashboardData
      if (next.schema_version !== '1.0' || !Array.isArray(next.cases) || !next.summary) throw new Error('서버 데이터 형식을 확인해 주세요.')
      if (mounted.current && generation === requestGeneration.current) {
        setCaseIds(previous => ({
          behavior: previous.behavior && next.investigations?.some(event => event.id === previous.behavior) ? previous.behavior : next.investigations?.[0]?.id ?? null,
          content: previous.content && [...(next.issue_cases ?? []), ...next.cases].some(event => event.id === previous.content)
            ? previous.content : (next.pipeline?.mode === 'no-ai' ? next.issue_cases ?? next.cases : next.cases)[0]?.id ?? null,
        }))
        setWorkspace(previous => previous ?? (next.pipeline?.mode === 'no-ai' ? 'content' : next.investigations?.length ? 'behavior' : next.cases.length ? 'content' : next.pipeline ? 'unlinked' : 'content'))
        setData(previous => previous?.session?.id === next.session?.id && previous?.snapshot_id === next.snapshot_id && previous.feed.status === next.feed.status && previous.feed.error === next.feed.error && previous.feed.last_ingested_at === next.feed.last_ingested_at && JSON.stringify(previous.feed.collector) === JSON.stringify(next.feed.collector) ? previous : next)
        setError(null)
      }
    } catch (caught) {
      if (mounted.current && generation === requestGeneration.current) setError(caught instanceof Error && caught.name === 'TimeoutError' ? '서버 응답이 지연되고 있습니다.' : caught instanceof Error ? caught.message : '엔진 서버에 연결할 수 없습니다.')
    } finally { if (generation === requestGeneration.current) { inFlight.current = false; if (mounted.current) setBusy(false) } }
  }, [])
  async function newDemo() {
    if (!data?.session || resetting.current) return
    resetting.current = true
    requestGeneration.current += 1
    inFlight.current = false
    setBusy(true)
    try {
      const response = await fetch('/api/demo/new', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-ANTI-FIMI-Client': 'dashboard' }, body: JSON.stringify({ session_id: data.session.id }), signal: AbortSignal.timeout(30000) })
      const result = await response.json()
      if (!response.ok) throw new Error(result.error ?? `시연 초기화 오류 (${response.status})`)
      if (mounted.current) { setData(result.dashboard as DashboardData); setError(null) }
    } finally {
      resetting.current = false
      if (mounted.current) setBusy(false)
      // Reconcile an ambiguous timeout: the server may have committed the reset.
      void refresh()
    }
  }
  useEffect(() => {
    const next = data?.session?.id
    if (!next || next === displayedSession.current) return
    const previous = displayedSession.current
    displayedSession.current = next
    if (!previous) return
    setCaseIds({ behavior: null, content: null }); setWorkspace(null)
    setSearch(''); setOnlyAlerts(false); setSelection({ kind: 'case', id: '' })
  }, [data?.session?.id])
  useEffect(() => { mounted.current = true; void refresh(); return () => { mounted.current = false } }, [refresh])
  useEffect(() => { if (!autoRefresh) return; const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void refresh() }, 3000); return () => window.clearInterval(timer) }, [autoRefresh, refresh])
  const activeWorkspace = workspace ?? 'behavior'
  const investigations = data?.investigations ?? []
  const noAI = data?.pipeline?.mode === 'no-ai'
  const contentEvents = noAI ? data?.issue_cases ?? data?.cases ?? [] : data?.cases ?? []
  const unlinked = noAI ? data?.issue_unclassified_posts ?? data?.unlinked_posts ?? [] : data?.unlinked_posts ?? []
  const activeEvents = activeWorkspace === 'behavior' ? investigations : activeWorkspace === 'content' ? contentEvents : []
  const selectedCase = [...activeEvents, ...(activeWorkspace === 'content' ? data?.cases ?? [] : [])].find(event => event.id === (activeWorkspace === 'unlinked' ? null : caseIds[activeWorkspace])) ?? activeEvents[0]
  const validSelection = useMemo(() => {
    if (!selectedCase) return { kind: 'case' as const, id: '' }
    const valid = selection.kind === 'case' ? selection.id === selectedCase.id : selection.kind === 'alert' ? selectedCase.alerts.some(alert => alert.id === selection.id) : selection.kind === 'account' ? selectedCase.network.nodes.some(node => node.id === selection.id) : selection.kind === 'edge' ? selectedCase.network.edges.some(edge => edge.id === selection.id) : selectedCase.narratives.some(item => item.id === selection.id)
    return valid ? selection : { kind: 'case' as const, id: selectedCase.id }
  }, [selectedCase, selection])
  const filteredCases = activeEvents.filter(event => (!onlyAlerts || event.alert_count > 0) && `${event.title} ${event.summary} ${event.id}`.toLowerCase().includes(search.toLowerCase()))
  const selectCase = (event: EventCase) => {
    if (activeWorkspace === 'unlinked') return
    setCaseIds(previous => ({ ...previous, [activeWorkspace]: event.id }))
    setSelection({ kind: 'case', id: event.id })
  }
  const changeWorkspace = (next: Workspace) => { setWorkspace(next); setSearch(''); setOnlyAlerts(false); setSelection({ kind: 'case', id: next === 'unlinked' ? '' : caseIds[next] ?? '' }) }
  const openLiveSignal = (target: SignalTarget) => {
    setWorkspace(target.workspace)
    setCaseIds(previous => ({ ...previous, [target.workspace]: target.eventId }))
    setSearch('')
    setOnlyAlerts(false)
    setSelection({ kind: 'alert', id: target.alertId })
  }
  const contentTitle = noAI ? '이슈 현황' : '내용 군집'
  const unlinkedTitle = noAI ? '이슈 미분류 게시물' : '미배정·대기'
  const workspaceTitle = activeWorkspace === 'behavior' ? '행동 조사망' : activeWorkspace === 'content' ? contentTitle : unlinkedTitle
  const pipeline = data?.pipeline
  const collector = data?.feed.collector
  const collectorLabel = collector?.status === 'error' ? '수집 오류' : collector?.status === 'stopped' ? '수집 중지' : collector?.baseline_ready ? 'VEIL 수집 중' : '수집 준비 중'
  return <div className="app-shell">
    <header className="topbar">
      <a className="brand" href="/" aria-label="ANTI_FIMI 홈"><span className="brand-mark"><Shield size={20} /><span /></span><div>ANTI<span>_</span>FIMI</div></a>
      <div className="header-actions"><NewDemo enabled={Boolean(data?.session)} connected={Boolean(collector)} onReset={newDemo} /><LiveAlerts data={data} live={live} onNavigate={openLiveSignal} /><span data-testid="connection-status" className={`connection-state ${error ? 'offline' : data ? 'connected' : ''}`}><i />{error ? '연결 확인 필요' : data ? '엔진 연결됨' : '연결 중'}</span><label className="auto-toggle"><input type="checkbox" checked={autoRefresh} onChange={event => setAutoRefresh(event.target.checked)} /><span />자동 갱신</label><button data-testid="refresh" className="refresh-button" disabled={busy} onClick={() => void refresh()} aria-label="데이터 새로고침"><RefreshCw size={14} className={busy ? 'spin' : ''} /><span>새로고침</span></button></div>
    </header>
    <div className="dashboard-layout">
      <aside className="case-rail">
        <div className="rail-heading"><div><h2><FolderOpen size={17} />{workspaceTitle} <span>{data ? activeWorkspace === 'unlinked' ? unlinked.length : activeEvents.length : '—'}</span></h2></div></div>
        {activeWorkspace !== 'unlinked' ? <><div className="rail-controls"><div className="search-field"><Search size={14} /><input value={search} onChange={event => setSearch(event.target.value)} placeholder={`${workspaceTitle} 검색`} aria-label="사건 검색" />{search && <button onClick={() => setSearch('')} aria-label="사건 검색 지우기"><X size={12} /></button>}</div><button className={`rail-filter ${onlyAlerts ? 'active' : ''}`} onClick={() => setOnlyAlerts(!onlyAlerts)} aria-pressed={onlyAlerts}><SlidersHorizontal size={12} />경보가 있는 항목{onlyAlerts && <Check size={12} />}</button></div>
        <div className="case-list">{filteredCases.map((event, i) => <button data-testid={activeWorkspace === 'behavior' ? 'investigation-card' : 'case-card'} aria-pressed={selectedCase?.id === event.id} key={event.id} className={`case-card ${selectedCase?.id === event.id ? 'selected' : ''} ${live.changed.has(entityKey(activeWorkspace === 'behavior' ? 'behavior' : 'content', event.id)) ? 'live-updated' : ''}`} onClick={() => selectCase(event)}><div className="case-card-top"><span className="case-index">{activeWorkspace === 'behavior' ? 'NET' : 'CASE'} {String(i + 1).padStart(2, '0')}</span><span className={`case-status ${event.priority}`}><i />{priorityLabel(event.priority)}</span></div><h3>{event.title}</h3>{activeWorkspace === 'content' && event.source === 'local_preview' && <span className="case-source preview">로컬 분석</span>}<div key={`${event.post_count}-${event.account_count}-${event.alert_count}`} className={`case-card-counts ${live.changed.has(entityKey(activeWorkspace === 'behavior' ? 'behavior' : 'content', event.id)) ? 'live-count-change' : ''}`}><span><Users size={11} />{event.account_count}</span><span><FileText size={11} />{event.post_count}</span><span className={event.alert_count ? 'has-alert' : ''}><Radio size={11} />{event.alert_count}</span></div><div className="case-card-bottom"><time>{dateTime(event.last_seen, true)}</time><ArrowRight size={13} /></div></button>)}{data && !filteredCases.length && <div className="rail-empty"><Search size={21} /><p>{activeEvents.length ? '조건에 맞는 항목이 없습니다.' : activeWorkspace === 'behavior' ? '탐지 조사망 없음' : noAI ? '분류된 이슈 없음' : '수신된 군집 없음'}</p></div>}</div></> : <div className="raw-queue-summary"><FileText size={23} /><strong>{number(unlinked.length)}<small>개 게시물</small></strong>{noAI ? <p>이슈 어휘·원본 참조로 분류되지 않은 원문입니다. 행동 분석에는 포함됩니다.</p> : <dl><div><dt>군집 대기</dt><dd>{unlinked.filter(post => post.ai_status !== 'received').length}</dd></div><div><dt>수신 · 미배정</dt><dd>{unlinked.filter(post => post.ai_status === 'received').length}</dd></div></dl>}</div>}
      </aside>
      <main className="main-area">
        {data && <div className="console-status" aria-label="전체 분석 현황">
          <span>게시물 <b key={pipeline?.raw_post_count ?? data.summary.post_count} className="live-count-change">{number(pipeline?.raw_post_count ?? data.summary.post_count)}</b></span><span>계정 <b key={pipeline?.raw_account_count ?? data.summary.account_count} className="live-count-change">{number(pipeline?.raw_account_count ?? data.summary.account_count)}</b></span><span>{pipeline ? '행동 신호' : '경보'} <b key={data.global_signals_count ?? data.summary.alert_count} className="live-count-change">{number(data.global_signals_count ?? data.summary.alert_count)}</b></span>{noAI && <span data-testid="early-alert-count">조기 주의 <b>{number(data.early_alerts_count ?? 0)}</b></span>}{pipeline && <PipelineStatus pipeline={pipeline} />}
          <span data-testid="collector-status" role="status">{collector && collectorLabel}</span><details className="collection-details"><summary>수집 정보 <ChevronDown size={12} /></summary><dl><div><dt>수집 상태</dt><dd>{collector ? collectorLabel : data.feed.status === 'watching' ? '파일 감시 중' : data.feed.status === 'error' ? '오류' : '감시 중지'}</dd></div><>{collector && <><div><dt>전송 완료</dt><dd>{number(collector.sent)}개</dd></div><div><dt>전송 대기</dt><dd>{number(collector.pending)}개</dd></div><div><dt>입력 거절</dt><dd>{number(collector.rejected)}개</dd></div></>}</><div><dt>마지막 수집</dt><dd>{dateTime(data.feed.last_ingested_at, false, true)} KST</dd></div><div><dt>분석 기준</dt><dd>{dateTime(pipeline?.behavior_as_of ?? data.analysis_as_of, false, true)} KST</dd></div>{pipeline && <div><dt>행동 집계 구간</dt><dd>{pipeline.behavior_window_hours}시간</dd></div>}<div><dt>군집 출처</dt><dd>{noAI ? '자료·행동 규칙 · AI 미사용' : pipeline?.mode === 'external-ai' ? '외부 AI' : '로컬 분석'}</dd></div></dl></details>
        </div>}
        {data && <WorkbookStatus status={data.playbook} onApplied={refresh} />}
        {data && noAI && <ScenarioCatalog catalog={data.scenario_catalog ?? []} candidates={data.scenario_candidates ?? []} />}
        {(error || data?.feed.error || collector?.error) && <div className="status-banner error" role="alert"><Info size={15} /><span>{error ?? data?.feed.error ?? collector?.error}</span><button onClick={() => void refresh()}>다시 연결 <ArrowRight size={12} /></button></div>}
        {data && <nav className="workspace-tabs" aria-label="조사 작업 영역"><button data-testid="workspace-tab" className={activeWorkspace === 'behavior' ? 'active' : ''} aria-pressed={activeWorkspace === 'behavior'} onClick={() => changeWorkspace('behavior')}><Network size={15} /><span>행동 조사망</span><b>{investigations.length}</b></button><button data-testid="workspace-tab" className={activeWorkspace === 'content' ? 'active' : ''} aria-pressed={activeWorkspace === 'content'} onClick={() => changeWorkspace('content')}><Layers3 size={15} /><span>{contentTitle}</span><b>{contentEvents.length}</b></button><button data-testid="workspace-tab" className={activeWorkspace === 'unlinked' ? 'active' : ''} aria-pressed={activeWorkspace === 'unlinked'} onClick={() => changeWorkspace('unlinked')}><FileText size={15} /><span>{unlinkedTitle}</span><b>{unlinked.length}</b></button></nav>}
        {data && activeWorkspace !== 'unlinked' && selectedCase && <SpreadOverview events={activeEvents} selected={selectedCase} stale={Boolean(error || data.feed.error || collector?.error)} paused={!autoRefresh} replay={data.spread_clock?.mode !== 'live'} onSelect={event => { setSearch(''); setOnlyAlerts(false); selectCase(event) }} />}
        {!data ? <section className="waiting-state"><span className="waiting-orbit"><Fingerprint size={33} /></span><h1>{error ? '엔진 연결 오류' : '데이터 조회 중'}</h1>{error && <button className="primary-button" onClick={() => void refresh()}><RefreshCw size={14} />다시 연결</button>}</section> : (pipeline?.raw_post_count ?? data.summary.post_count) === 0 ? <section className="waiting-state" data-testid="empty-demo"><Radio size={35} /><h1>수집 대기</h1></section> : activeWorkspace === 'unlinked' ? <UnlinkedPosts posts={unlinked} plans={data.playbook_raw_matches} noAI={noAI} alertCases={data.unassigned_alert_cases} onOpen={event => { setWorkspace('content'); setCaseIds(previous => ({ ...previous, content: event.id })); setSelection({ kind: 'case', id: event.id }) }} /> : selectedCase ? <div className="workbench"><EventWorkspace key={selectedCase.id} event={selectedCase} selection={validSelection} onSelect={setSelection} /></div> : <section className="waiting-state"><FolderOpen size={35} /><h1>{activeWorkspace === 'behavior' ? '탐지 조사망 0건' : `${contentTitle} 0개`}</h1><button className="primary-button" onClick={() => changeWorkspace('unlinked')}><FileText size={14} />{unlinkedTitle}</button></section>}
        {data && <details className="limitations"><summary><Info size={13} />분석 범위와 한계 <ChevronDown size={13} /></summary><ul><li>실선 화살표는 작성자 → 참조 원문 작성자 관계이며 실제 전파 경로를 확정하지 않습니다. 점선은 방향 없는 공동 공유 추론입니다.</li><li>{noAI ? '미연결 게시물도 행동 분석에 포함됩니다. 자료 흐름과 동일 원문으로 묶으며 의미·입장 분류는 아닙니다. 하위 근거에는 중복 소속이 남을 수 있습니다.' : '미배정·대기 게시물도 행동 분석에 포함됩니다. AI는 군집 분류만 수행하며 입장·허위성은 미분석입니다.'}</li><li>행동 점수는 규칙 기반 검토 지표이며 공작 확률이 아닙니다.</li>{data.limitations.map((limitation, i) => <li key={i}>{limitation}</li>)}</ul></details>}
      </main>
    </div>
  </div>
}
