import type { Alert, DashboardData, EventCase } from './types'

export type AlertWorkspace = 'behavior' | 'content'
export interface SignalTarget { workspace: AlertWorkspace; eventId: string; alertId: string }
interface Signal extends SignalTarget { key: string; event: EventCase; alert: Alert }
export interface LiveNotice {
  id: string; signalKey: string; kind: 'new' | 'escalated'; title: string; summary: string;
  priority: string; observedAt: string; read: boolean;
  category?: 'early' | 'behavior';
}
export interface LiveTracker {
  initialized: boolean; seen: Map<string, number>; entities: Map<string, string>;
}
export const NOTICE_LIMIT = 30
export const entityKey = (workspace: AlertWorkspace, id: string) => JSON.stringify([workspace, id])
const rank = (priority: string) => priority === 'review_high' || priority === 'high' ? 2 : priority === 'none' ? 0 : 1
export const createLiveTracker = (): LiveTracker => ({ initialized: false, seen: new Map(), entities: new Map() })

// Behavior IDs roll each hour and may appear in both a network and a content case.
// Track the account pair globally; use its current location when opening history.
function signalKey(workspace: AlertWorkspace, event: EventCase, alert: Alert) {
  const accounts = [...alert.account_ids].sort()
  if (alert.kind === 'resource_burst') return JSON.stringify([alert.kind, alert.id])
  if (alert.kind === 'behavior_coordination') return JSON.stringify([alert.kind, accounts])
  if (alert.kind === 'repeated_url_coshare') return JSON.stringify([workspace, event.id, alert.kind, accounts])
  return JSON.stringify([workspace, event.id, alert.kind, alert.metrics.hour ?? alert.metrics['시간'] ?? alert.id])
}

function collect(data: DashboardData) {
  const signals = new Map<string, Signal>()
  const entities = new Map<string, string>()
  const groups: [AlertWorkspace, EventCase[]][] = [['behavior', data.investigations ?? []], ['content', [...(data.issue_cases ?? []), ...data.cases]]]
  for (const [workspace, events] of groups) for (const event of events) {
    entities.set(entityKey(workspace, event.id), JSON.stringify([
      event.post_count, event.account_count, event.alert_count, event.priority, event.network_score,
    ]))
    for (const alert of event.alerts) {
      const key = signalKey(workspace, event, alert)
      // Prefer the behavior workspace when the same global evidence is also linked to content.
      if (!signals.has(key)) signals.set(key, { key, workspace, eventId: event.id, alertId: alert.id, event, alert })
    }
  }
  return { signals, entities }
}

export function observeSnapshot(tracker: LiveTracker, data: DashboardData, observedAt: string) {
  const { signals, entities } = collect(data)
  const notices: LiveNotice[] = []
  const changed = new Set<string>()
  if (tracker.initialized) for (const [key, value] of entities) {
    if (tracker.entities.get(key) !== value) changed.add(key)
  }
  for (const signal of signals.values()) {
    const previous = tracker.seen.get(signal.key)
    const level = rank(signal.alert.priority)
    if (tracker.initialized && (previous === undefined || level > previous)) {
      notices.push({ id: `${signal.key}:${level}`, signalKey: signal.key,
        category: signal.alert.kind === 'resource_burst' ? 'early' : 'behavior',
        kind: previous === undefined ? 'new' : 'escalated', title: signal.event.title,
        summary: signal.alert.summary, priority: signal.alert.priority, observedAt, read: false })
    }
    // Keep the session maximum even after a signal disappears or its history is dismissed.
    tracker.seen.set(signal.key, Math.max(previous ?? level, level))
  }
  tracker.initialized = true
  tracker.entities = entities
  notices.sort((a, b) => rank(b.priority) - rank(a.priority))
  return { notices, changed }
}

export const mergeNotices = (current: LiveNotice[], incoming: LiveNotice[]) => [...incoming, ...current].slice(0, NOTICE_LIMIT)
export function resolveNoticeTarget(data: DashboardData, notice: LiveNotice): SignalTarget | undefined {
  const signal = collect(data).signals.get(notice.signalKey)
  return signal && { workspace: signal.workspace, eventId: signal.eventId, alertId: signal.alertId }
}
