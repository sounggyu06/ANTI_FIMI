import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'
import { Expand, Minus, Plus } from 'lucide-react'

export interface GraphNode { id: string; label: string; postCount: number; alertCount: number }
export interface GraphEdge { id: string; source: string; target: string; kind: string; weight: number; observed: boolean }
export type Selection = { kind: 'case' | 'alert' | 'account' | 'edge' | 'narrative'; id: string }

export default function NetworkGraph({ nodes, edges, selection, highlightedNodes, highlightedEdges, onSelect }: {
  nodes: GraphNode[]; edges: GraphEdge[]; selection: Selection; highlightedNodes: string[]; highlightedEdges: string[]; onSelect: (selection: Selection) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const graph = useRef<cytoscape.Core | null>(null)
  const callback = useRef(onSelect)
  const graphKey = JSON.stringify([nodes, edges])
  callback.current = onSelect

  useEffect(() => {
    if (!container.current || !nodes.length) return
    const cy = cytoscape({
      container: container.current,
      elements: [
        ...nodes.map((node, index) => ({ position: { x: 200 + 150 * Math.cos(index * Math.PI * 2 / nodes.length), y: 180 + 150 * Math.sin(index * Math.PI * 2 / nodes.length) }, data: { id: node.id, label: node.label.length > 17 ? `${node.label.slice(0, 15)}…` : node.label, size: 26 + Math.min(node.postCount, 12) * 1.8, alerted: node.alertCount > 0 ? 1 : 0 } })),
        ...edges.map(edge => ({ data: { ...edge, width: Math.min(4, 1.2 + edge.weight * .32) }, classes: edge.observed ? 'observed' : 'inferred' })),
      ],
      style: [
        { selector: 'node', style: { 'background-color': '#282828', 'border-color': '#aab3bc', 'border-width': 1.5, width: 'data(size)', height: 'data(size)', label: 'data(label)', color: '#a9bac7', 'font-size': 10, 'font-family': 'sans-serif', 'text-valign': 'bottom', 'text-margin-y': 9, 'text-background-color': '#101010', 'text-background-opacity': .85, 'text-background-padding': '3px', 'overlay-opacity': 0 } },
        { selector: 'node[alerted = 1]', style: { 'background-color': '#393222', 'border-color': '#dcbf82', 'border-width': 2 } },
        { selector: 'edge', style: { width: 'data(width)', 'curve-style': 'bezier', 'line-color': '#77816e', opacity: .5, 'overlay-opacity': 0 } },
        { selector: 'edge.inferred', style: { 'line-style': 'dashed', 'line-dash-pattern': [5, 5], 'line-color': '#bd9a58' } },
        { selector: 'edge.observed', style: { 'target-arrow-shape': 'triangle', 'target-arrow-color': '#b5c0cc', 'line-color': '#b5c0cc', 'arrow-scale': .8 } },
        { selector: '.dimmed', style: { opacity: .15 } },
        { selector: 'node.highlighted', style: { opacity: 1, 'border-width': 3, 'border-color': '#f1f1f1', 'background-color': '#494949', color: '#fff' } },
        { selector: 'edge.highlighted', style: { opacity: .95, 'line-color': '#d5bd82', 'target-arrow-color': '#d6dce2', width: 3 } },
      ],
      layout: { name: nodes.length <= 2 ? 'circle' : 'cose', animate: false, randomize: false, padding: 60, nodeRepulsion: () => 13000, idealEdgeLength: () => 105, componentSpacing: 110, nodeOverlap: 30 },
      minZoom: .2, maxZoom: 3, wheelSensitivity: .2,
    })
    graph.current = cy
    cy.on('tap', 'node', event => callback.current({ kind: 'account', id: event.target.id() }))
    cy.on('tap', 'edge', event => callback.current({ kind: 'edge', id: event.target.id() }))
    let lastWidth = container.current.clientWidth
    const resize = new ResizeObserver(() => {
      const width = container.current?.clientWidth ?? lastWidth
      cy.resize()
      if (width > 0 && width !== lastWidth) {
        lastWidth = width
        cy.fit(undefined, 55)
      }
    })
    resize.observe(container.current)
    return () => { resize.disconnect(); cy.destroy(); graph.current = null }
    // The graph signature preserves positions during unchanged polling snapshots.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphKey])

  useEffect(() => {
    const cy = graph.current
    if (!cy) return
    cy.elements().removeClass('dimmed highlighted')
    if (selection.kind === 'case') return
    cy.elements().addClass('dimmed')
    for (const id of highlightedNodes) cy.getElementById(id).removeClass('dimmed').addClass('highlighted')
    for (const id of highlightedEdges) cy.getElementById(id).removeClass('dimmed').addClass('highlighted')
  }, [selection, highlightedNodes, highlightedEdges, graphKey])

  return <div className="network-shell">
    {!nodes.length ? <div className="chart-empty">이 사건에 연결된 계정이 없습니다.</div> : <div data-testid="network-canvas" className="network-canvas" ref={container} role="img" aria-label={`선택 사건의 계정 ${nodes.length}개, 관계 ${edges.length}개. 아래 계정 버튼으로도 탐색할 수 있습니다.`} />}
    <div className="graph-tools">
      <button title="확대" aria-label="네트워크 확대" onClick={() => graph.current?.zoom(graph.current.zoom() * 1.2)}><Plus size={15} /></button>
      <button title="축소" aria-label="네트워크 축소" onClick={() => graph.current?.zoom(graph.current.zoom() / 1.2)}><Minus size={15} /></button>
      <button title="전체 보기" aria-label="네트워크 전체 보기" onClick={() => graph.current?.fit(undefined, 55)}><Expand size={14} /></button>
    </div>
    <div className="graph-legend"><span><i className="legend-line observed" />원문 참조 →</span><span><i className="legend-line inferred" />공동 공유 · 추론</span></div>
  </div>
}
