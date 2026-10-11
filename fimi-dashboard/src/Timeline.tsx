import { useEffect, useRef } from 'react'
import { init, use as registerCharts } from 'echarts/core'
import type { EChartsType } from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, AriaComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

registerCharts([BarChart, LineChart, GridComponent, TooltipComponent, AriaComponent, CanvasRenderer])
export interface TimelinePoint { time: string; count: number; baseline: number | null }

export default function Timeline({ points }: { points: TimelinePoint[] }) {
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
    chart.current?.setOption({
      animation: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
      animationDuration: 450,
      animationDurationUpdate: 650,
      animationEasingUpdate: 'cubicOut',
      aria: { enabled: true },
      textStyle: { fontFamily: 'sans-serif' },
      grid: { left: 34, right: 12, top: 20, bottom: 25 },
      tooltip: { trigger: 'axis', renderMode: 'richText', backgroundColor: '#172630', borderColor: '#354854', textStyle: { color: '#e4eef2', fontSize: 11 } },
      xAxis: { type: 'category', data: points.map(point => new Date(point.time).toLocaleTimeString('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hour12: false })), axisLine: { lineStyle: { color: '#24323d' } }, axisTick: { show: false }, axisLabel: { color: '#7f929f', fontSize: 10, hideOverlap: true } },
      yAxis: { type: 'value', minInterval: 1, splitNumber: 3, axisLabel: { color: '#718592', fontSize: 10 }, splitLine: { lineStyle: { color: '#1d2a34', type: 'dashed' } } },
      series: [
        { name: '게시물', type: 'bar', data: points.map(point => point.count), barMaxWidth: 27, itemStyle: { color: '#bec7d0', borderRadius: [3, 3, 0, 0] }, emphasis: { itemStyle: { color: '#f1f1f1' } } },
        { name: '직전 6시간 평균', type: 'line', data: points.map(point => point.baseline), connectNulls: false, symbol: 'none', lineStyle: { width: 1.5, color: '#c8aa6b', type: 'dashed' }, itemStyle: { color: '#c8aa6b' } },
      ],
    }, false)
  }, [points])
  return <div className="timeline-chart" ref={host} role="img" aria-label={`시간별 게시물 수. ${points.length}개 시간대. 한국 표준시 기준.`} />
}
