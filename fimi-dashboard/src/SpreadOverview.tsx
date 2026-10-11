import { useEffect, useRef } from 'react'
import { Activity, ArrowRight, Clock3, Minus, TrendingDown, TrendingUp } from 'lucide-react'
import { init, use as registerCharts } from 'echarts/core'
import type { EChartsType } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { AriaComponent, GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EventCase, SpreadMetrics } from './types'
import './SpreadOverview.css'

registerCharts([LineChart, AriaComponent, GridComponent, TooltipComponent, CanvasRenderer])
const states = {
  insufficient: { label: '자료 축적 중', Icon: Clock3, note: '비교할 과거 자료가 부족합니다.' },
  low_volume: { label: '관측 소량', Icon: Minus, note: '게시량 또는 참여 계정이 적어 변화 판단을 보류합니다.' },
  steady: { label: '확산 유지', Icon: ArrowRight, note: '직전 구간 대비 뚜렷한 가속·둔화가 관측되지 않았습니다.' },
  accelerating: { label: '확산 가속', Icon: TrendingUp, note: '게시량이 증가하고 참여 계정 범위가 유지·확대됐습니다.' },
  surging: { label: '확산 급증', Icon: TrendingUp, note: '여러 계정의 게시량이 빠르게 늘어 우선 확인이 필요합니다.' },
  declining: { label: '확산 둔화', Icon: TrendingDown, note: '관측 게시량이 줄었습니다. 기존 위해의 해소를 뜻하지 않습니다.' },
}
const kst = (value: string) => new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hour12: false,
}).format(new Date(value))
const bucketLabel = (seconds: number) => seconds < 60 ? `${seconds}초` : seconds < 3600 ? `${seconds / 60}분` : `${seconds / 3600}시간`
const graphTime = (value: string, seconds: number, span: number) => new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul', ...(span >= 86400 ? { month: '2-digit', day: '2-digit' } : {}), hour: '2-digit', minute: '2-digit', ...(seconds < 60 ? { second: '2-digit' } : {}), hour12: false,
}).format(new Date(value))

function FlowChart({ metrics }: { metrics: SpreadMetrics }) {
  const host = useRef<HTMLDivElement>(null)
  const chart = useRef<EChartsType | null>(null)
  useEffect(() => {
    if (!host.current) return
    chart.current = init(host.current, null, { renderer: 'canvas' })
    const resize = new ResizeObserver(() => chart.current?.resize())
    resize.observe(host.current)
    return () => { resize.disconnect(); chart.current?.dispose(); chart.current = null }
  }, [])
  useEffect(() => {
    const seconds = metrics.bucket_seconds ?? 60
    const unit = bucketLabel(seconds)
    chart.current?.setOption({
      animation: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
      animationDuration: 400, animationDurationUpdate: 650, animationEasingUpdate: 'cubicOut',
      aria: { enabled: true }, grid: { top: 12, right: 8, bottom: 23, left: 28, containLabel: true },
      tooltip: { trigger: 'axis', renderMode: 'richText', backgroundColor: '#181818', borderColor: '#444', textStyle: { color: '#eee', fontSize: 11 } },
      xAxis: { type: 'category', boundaryGap: true, data: metrics.history.map(point => graphTime(point.time, seconds, metrics.history_span_seconds ?? 0) + (point.partial ? ' *' : '')),
        axisLine: { lineStyle: { color: '#31414c' } }, axisTick: { show: false }, axisLabel: { color: '#91a6b4', fontSize: 9, hideOverlap: true, interval: Math.max(0, Math.ceil(metrics.history.length / 6) - 1) } },
      yAxis: { type: 'value', min: 0, minInterval: 1, axisLabel: { show: true, color: '#91a6b4', fontSize: 9 }, splitNumber: 2, splitLine: { lineStyle: { color: '#23313b', type: 'dashed' } } },
      series: [
        { id: 'posts', name: `${unit} 구간 게시물`, type: 'line', symbol: 'circle', symbolSize: 5, showSymbol: true, connectNulls: false,
          data: metrics.history.map(point => point.observed || point.within_observed_range ? point.post_count : null),
          lineStyle: { color: '#bec7d0', width: 2 }, itemStyle: { color: '#bec7d0' }, areaStyle: { color: '#bec7d0', opacity: .08 } },
        { id: 'accounts', name: `${unit} 구간 참여 계정`, type: 'line', symbol: 'circle', symbolSize: 4, showSymbol: true, connectNulls: false,
          data: metrics.history.map(point => point.observed || point.within_observed_range ? point.account_count : null),
          lineStyle: { color: '#dcbf82', width: 1.5, type: 'dashed' }, itemStyle: { color: '#dcbf82' } },
      ],
    })
  }, [metrics])
  return <div className="spread-flow-chart" ref={host} role="img" data-testid="adaptive-spread-chart" aria-label={`선택 항목의 ${bucketLabel(metrics.bucket_seconds ?? 60)} 구간 확산 흐름. 첫 게시물부터 표시하며 부분 구간을 포함합니다.`} />
}

export default function SpreadOverview({ events, selected, onSelect, stale, paused, replay }: {
  events: EventCase[]; selected: EventCase; onSelect: (event: EventCase) => void; stale: boolean;
  paused: boolean; replay: boolean;
}) {
  const metrics = selected.spread
  const state = metrics ? states[metrics.state] : null
  const Icon = stale || paused ? Clock3 : state?.Icon ?? Clock3
  const ranked = [...events].sort((a, b) =>
    Number(b.priority === 'review_high') - Number(a.priority === 'review_high') ||
    Number(b.priority === 'review_medium') - Number(a.priority === 'review_medium') ||
    (b.spread?.current_account_count ?? 0) - (a.spread?.current_account_count ?? 0) ||
    (b.spread?.current_post_count ?? 0) - (a.spread?.current_post_count ?? 0) || a.id.localeCompare(b.id),
  ).slice(0, 5)
  const maximum = Math.max(1, ...ranked.map(event => event.spread?.current_account_count ?? 0))
  return <section className={`spread-overview panel ${stale ? 'stale' : ''}`} aria-label="확산 흐름과 검토 목록">
    <div className="spread-selected">
      <div className="spread-heading"><h2><Activity size={15} />선택 사건 확산</h2><span>{replay ? '자료 시각 재생 · ' : '실시간 · '}{metrics ? `${new Date(metrics.as_of).toLocaleDateString('ko-KR', { timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit' })} ${kst(metrics.as_of)} KST` : '집계 대기'}</span></div>
      <div className={`spread-state ${stale || paused ? 'insufficient' : metrics?.state ?? 'insufficient'}`} data-testid="spread-state"><Icon size={24} /><div><strong>{stale ? '갱신 확인 필요' : paused ? '자동 갱신 중지' : state?.label ?? '집계 대기'}</strong><p>{stale || paused ? '마지막 성공 자료를 표시합니다.' : state?.note ?? '확산 지표가 수신되면 표시됩니다.'}</p></div></div>
      <div className="spread-state-band" aria-hidden="true">{(['declining', 'steady', 'accelerating', 'surging'] as const).map(value => <span key={value} className={!stale && !paused && metrics?.state === value ? `active ${value}` : ''}>{states[value].label.replace('확산 ', '')}</span>)}</div>
      {metrics && <><FlowChart metrics={metrics} /><div className="spread-flow-legend"><span><i />구간 게시물</span><span><i className="accounts" />구간 참여 계정</span><small data-testid="graph-bucket-label">{bucketLabel(metrics.bucket_seconds ?? 60)} 단위 · 첫 관측부터 · 부분 구간 포함</small></div></>}
    </div>
    <div className="spread-ranking"><div className="spread-heading"><h2>검토 목록</h2><span>현재 작업 영역</span></div>
      <p className="spread-ranking-rule">기존 경보 우선 · 같은 등급은 최근 5분 참여 계정 순</p>
      {ranked.map((event, index) => <button data-testid="spread-rank" className={`spread-rank ${selected.id === event.id ? 'selected' : ''}`} key={event.id} onClick={() => onSelect(event)} title={`최근 5분 관측 계정 ${event.spread?.current_account_count ?? 0}개. 위해 등급과 별도.`}>
        <span className="spread-rank-label"><i>{index + 1}</i><b>{event.title}</b><small>{event.priority === 'review_high' ? '우선 검토' : event.priority === 'review_medium' ? '검토 필요' : '경보 없음'}</small></span>
        <span className="spread-rank-track"><span className={stale ? 'insufficient' : event.spread?.state ?? 'insufficient'} style={{ width: `${(event.spread?.current_account_count ?? 0) / maximum * 100}%` }} /></span>
      </button>)}
      <p className="spread-ranking-note">막대 길이: 최근 참여 계정의 상대 규모<br />목록 밖 사건도 계속 분석됩니다.</p>
    </div>
    <details className="spread-method"><summary>표시 기준·한계</summary><p>그래프는 첫 관측부터 표시하고 기간이 늘면 집계 간격을 조정합니다. *는 부분 구간이며 집계 시간이 짧아 완전한 구간과 직접 비교하면 안 됩니다. 확산 상태와 검토 목록은 별도로 최근 5분과 직전 5분을 비교합니다. 자체 관측 규칙이며 위해 등급·공작 확률이 아닙니다. 지연 수집에 따라 과거 값이 바뀔 수 있고 수집의 연속성·완전성은 미확인입니다.</p></details>
  </section>
}
