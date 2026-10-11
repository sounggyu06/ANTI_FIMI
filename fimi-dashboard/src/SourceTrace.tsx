import { useMemo } from 'react'
import { ArrowRight, Clock3, GitBranch, Info, Link2 } from 'lucide-react'
import type { SourceTrace } from './types'
import './SourceTrace.css'

const fmtTime = (value: string) => {
  const time = new Date(value)
  return Number.isNaN(time.getTime()) ? value : new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit', hour: '2-digit',
    minute: '2-digit', second: '2-digit', hour12: false,
  }).format(time) + ' KST'
}

const relName: Record<string, string> = { quotes: '인용', reposts: '재공유', replies_to: '답글' }

export default function SourceTracePanel({ trace, onAccount }: { trace?: SourceTrace; onAccount?: (id: string) => void }) {
  const graph = useMemo(() => {
    if (!trace?.nodes.length) return null
    const levels = new Map<number, typeof trace.nodes>()
    for (const item of trace.nodes) {
      const list = levels.get(item.depth) ?? []
      list.push(item)
      levels.set(item.depth, list)
    }
    const chosen = [...levels.entries()].sort((a, b) => a[0] - b[0])
      .slice(0, 12).flatMap(([, nodes]) => nodes.slice(0, 5))
    const coord = new Map(chosen.map((node) => {
      const row = (levels.get(node.depth) ?? []).indexOf(node)
      const count = Math.min(5, (levels.get(node.depth) ?? []).length)
      return [node.post_id, {
        x: 92 + node.depth * 166,
        y: 185 + (row - (count - 1) / 2) * 61,
      }] as const
    }))
    const width = Math.max(560, (Math.max(...chosen.map(node => node.depth)) + 1) * 166 + 160)
    return { chosen, coord, width }
  }, [trace])

  if (!trace || !trace.earliest_observed) return null
  const chronological = trace.earliest_observed
  const root = trace.leading_root
  return <section className="source-trace panel" data-testid="source-trace">
    <div className="panel-heading"><div><h2><GitBranch size={16} />최초 관측 · 확산 경로</h2></div></div>
    <div className="source-trace-summary">
      <div className="source-trace-card">
        <small><Clock3 size={12} />해당 이슈에서 가장 먼저 관측된 게시물</small>
        <strong>{chronological.account_id}</strong>
        <span>{fmtTime(chronological.created_at)}</span>
        <code>{chronological.post_id}</code>
      </div>
      <div className="source-trace-card">
        <small><GitBranch size={12} />관측된 참조 경로의 주요 시작점</small>
        {root ? <>
          <strong>{root.account_id}</strong>
          <span>{fmtTime(root.created_at)}</span>
          <span>후속 연결 게시물 {root.reachable_posts}개 · {root.observed_depth}단계</span>
          {(root.upstream_not_collected || root.upstream_outside_scope) && <em>상위 출처가 이슈 범위 밖이거나 미수집되었습니다.</em>}
        </> : <strong>확인 가능한 참조 시작점 없음</strong>}
      </div>
    </div>
    <div className="source-trace-stats">
      <span>명시적 참조 <b>{trace.observed_edge_count}</b>개</span>
      <span>관계 확인 게시물 <b>{trace.linked_post_count}</b> / {trace.total_posts}</span>
      <span>이슈 밖 참조 <b>{trace.outside_scope_references}</b>개</span>
      <span>미수집 원본 <b>{trace.unavailable_references}</b>개</span>
    </div>
    {graph && trace.claim === 'observed_reference_chain' ? <>
      <div className="source-trace-scroll" aria-label="수집된 인용 및 재공유 방향성 그래프">
        <svg width={graph.width} height={370} viewBox={`0 0 ${graph.width} 370`} role="img" aria-label="원본 게시물에서 후속 게시물로 이어지는 명시적 참조 경로">
          <defs><marker id="source-trace-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M 0 0 L 7 3 L 0 6 z" fill="#7296ad" /></marker></defs>
          {trace.edges.map((edge, i) => {
            const a = graph.coord.get(edge.source)
            const b = graph.coord.get(edge.target)
            if (!a || !b) return null
            return <line key={`${i}-${edge.source}-${edge.target}`} x1={a.x + 56} y1={a.y} x2={b.x - 56} y2={b.y}
              stroke="#7296ad" strokeWidth={1.8} opacity=".8" markerEnd="url(#source-trace-arrow)"><title>{relName[edge.kind] ?? edge.kind}</title></line>
          })}
          {graph.chosen.map(node => {
            const c = graph.coord.get(node.post_id)!
            return <g key={node.post_id} onClick={() => onAccount?.(node.account_id)} role="button" tabIndex={0}
              onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onAccount?.(node.account_id) } }}
              className="source-trace-node" aria-label={`${node.account_id} 계정 근거 확인`}>
              <rect x={c.x - 56} y={c.y - 24} rx="10" width="112" height="48" fill={node.depth === 0 ? '#1e5e89' : '#253748'} stroke="#7296ad" strokeWidth="1" />
              <text x={c.x} y={c.y - 4} textAnchor="middle" fill="#f7fafc" fontSize="11" fontWeight="600">{node.account_id.length > 16 ? node.account_id.slice(0, 15) + '…' : node.account_id}</text>
              <text x={c.x} y={c.y + 12} textAnchor="middle" fill="#cbd5e1" fontSize="10">{node.depth}단계</text>
              <title>{node.account_id} · {node.post_id} · {fmtTime(node.created_at)} · {node.text}</title>
            </g>
          })}
        </svg>
      </div>
      <div className="source-trace-caption"><Link2 size={12} />화살표는 실제 수집된 인용·재공유·답글 원본 참조입니다. 노드를 선택하면 해당 계정의 근거 게시물을 볼 수 있습니다. 많은 경로는 일부만 표시합니다.</div>
    </> : <div className="source-trace-empty">이 이슈에서는 게시물 사이의 명시적인 참조 관계가 확인되지 않았습니다. 최초 관측 시각만으로 전파 방향을 추정하지 않습니다.</div>}
    {trace.root_candidates.length > 1 && <details className="source-trace-roots"><summary>추가 관측 시작점 {trace.root_candidates.length - 1}개 확인 <ArrowRight size={12}/></summary>
      {trace.root_candidates.slice(1).map(item => <p key={item.post_id}><b>{item.account_id}</b> · 연결 게시물 {item.reachable_posts}개 · {fmtTime(item.created_at)}</p>)}
    </details>}
    {trace.time_inconsistent_references > 0 && <p className="source-trace-caution">게시 시각과 모순되는 참조 {trace.time_inconsistent_references}개는 경로에서 제외했습니다.</p>}
    <p className="source-trace-limit"><Info size={12} />{trace.limitations}</p>
  </section>
}
