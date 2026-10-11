import assert from 'node:assert/strict'
import test from 'node:test'
import { createLiveTracker, entityKey, mergeNotices, NOTICE_LIMIT, observeSnapshot, resolveNoticeTarget } from '../src/liveAlertState.ts'

const observedAt = '2026-10-10T15:10:00Z'
const alert = (id = 'signal-1', priority = 'review_medium', extra = {}) => ({
  id, priority, kind: 'behavior_coordination', account_ids: ['a', 'b'], label: '반복 행동', summary: '근거 검토',
  reason_codes: [], reason_labels: [], evidence_post_ids: ['p1'], metrics: {}, ...extra,
})
const event = (alerts = [], extra = {}) => ({ id: 'case-1', title: '사건', post_count: 1, account_count: 2,
  alert_count: alerts.length, priority: 'review_medium', alerts, ...extra })
const snapshot = (investigations = [], cases = []) => ({ snapshot_id: Math.random().toString(), investigations, cases })

test('issue folders share one early notice and navigation prefers its current issue', () => {
  const tracker = createLiveTracker()
  observeSnapshot(tracker, snapshot(), observedAt)
  const early = alert('early-1', 'review_medium', { kind: 'resource_burst' })
  const data = { ...snapshot([], [event([early], { id: 'raw-material' })]),
    issue_cases: [event([early], { id: 'ISSUE_FRONTLINE' }), event([early], { id: 'ISSUE_ECONOMY' })] }
  const notices = observeSnapshot(tracker, data, observedAt).notices
  assert.equal(notices.length, 1)
  assert.equal(resolveNoticeTarget(data, notices[0]).eventId, 'ISSUE_FRONTLINE')
  data.issue_cases = []
  assert.equal(observeSnapshot(tracker, data, observedAt).notices.length, 0)
  assert.equal(resolveNoticeTarget(data, notices[0]).eventId, 'raw-material')
})

test('first successful snapshot establishes a quiet baseline; timestamp-only refresh remains quiet', () => {
  const tracker = createLiveTracker()
  const data = snapshot([event([alert()])])
  assert.equal(observeSnapshot(tracker, data, observedAt).notices.length, 0)
  assert.equal(observeSnapshot(tracker, { ...data, snapshot_id: 'later' }, observedAt).notices.length, 0)
})
test('one new behavior is notified once even when also present in a content case', () => {
  const tracker = createLiveTracker()
  observeSnapshot(tracker, snapshot(), observedAt)
  const data = snapshot([event([alert()])], [event([alert()], { id: 'content-case' })])
  assert.equal(observeSnapshot(tracker, data, observedAt).notices.length, 1)
  assert.equal(observeSnapshot(tracker, data, observedAt).notices.length, 0)
})
test('hour rollover, account order and parent reassignment retain identity and current navigation', () => {
  const tracker = createLiveTracker()
  observeSnapshot(tracker, snapshot(), observedAt)
  const notice = observeSnapshot(tracker, snapshot([event([alert()])]), observedAt).notices[0]
  const next = snapshot([event([alert('rolled-id', 'review_medium', { account_ids: ['b', 'a'] })], { id: 'merged-parent' })])
  assert.equal(observeSnapshot(tracker, next, observedAt).notices.length, 0)
  assert.deepEqual(resolveNoticeTarget(next, notice), { workspace: 'behavior', eventId: 'merged-parent', alertId: 'rolled-id' })
  assert.equal(resolveNoticeTarget(snapshot(), notice), undefined)
})
test('escalation is alerted once; down/up priority oscillation does not repeat the session maximum', () => {
  const tracker = createLiveTracker()
  observeSnapshot(tracker, snapshot([event([alert()])]), observedAt)
  const high = snapshot([event([alert('new-id', 'review_high')])])
  assert.equal(observeSnapshot(tracker, high, observedAt).notices[0].kind, 'escalated')
  observeSnapshot(tracker, snapshot([event([alert()])]), observedAt)
  assert.equal(observeSnapshot(tracker, high, observedAt).notices.length, 0)
})
test('signal disappearance and reappearance does not manufacture a new notification', () => {
  const tracker = createLiveTracker()
  const data = snapshot([event([alert()])])
  observeSnapshot(tracker, data, observedAt)
  observeSnapshot(tracker, snapshot(), observedAt)
  assert.equal(observeSnapshot(tracker, data, observedAt).notices.length, 0)
})
test('a new hourly diffusion window is a distinct signal', () => {
  const tracker = createLiveTracker()
  const spike = hour => alert(hour, 'review_medium', { kind: 'hourly_diffusion_spike', metrics: { '시간': hour } })
  observeSnapshot(tracker, snapshot([], [event([spike('10:00')])]), observedAt)
  assert.equal(observeSnapshot(tracker, snapshot([], [event([spike('11:00')])]), observedAt).notices.length, 1)
})
test('repeated co-share IDs rolling within the same event do not trigger duplicate alarms', () => {
  const tracker = createLiveTracker()
  const shared = id => alert(id, 'review_high', { kind: 'repeated_url_coshare' })
  observeSnapshot(tracker, snapshot([], [event([shared('a')])]), observedAt)
  assert.equal(observeSnapshot(tracker, snapshot([], [event([shared('b')])]), observedAt).notices.length, 0)
})
test('display history is bounded without erasing semantic deduplication', () => {
  const tracker = createLiveTracker()
  observeSnapshot(tracker, snapshot(), observedAt)
  let history = []
  for (let i = 0; i < 40; i++) {
    const data = snapshot([event([alert(`s${i}`, 'review_medium', { account_ids: [`a${i}`, `b${i}`] })])])
    history = mergeNotices(history, observeSnapshot(tracker, data, observedAt).notices)
  }
  assert.equal(history.length, NOTICE_LIMIT)
  assert.equal(observeSnapshot(tracker, snapshot([event([alert('s0', 'review_medium', { account_ids: ['a0', 'b0'] })])]), observedAt).notices.length, 0)
})
test('only real event changes mark a card; unrelated snapshot timestamps do not', () => {
  const tracker = createLiveTracker()
  observeSnapshot(tracker, snapshot([event()]), observedAt)
  assert.equal(observeSnapshot(tracker, snapshot([event()]), observedAt).changed.size, 0)
  assert.deepEqual([...observeSnapshot(tracker, snapshot([event([], { post_count: 2 })]), observedAt).changed], [entityKey('behavior', 'case-1')])
})

test('early attention stays deduplicated and navigable after a material parent changes', () => {
  const tracker = createLiveTracker()
  observeSnapshot(tracker, snapshot(), observedAt)
  const early = alert('RB_root', 'review_medium', { kind: 'resource_burst', phase: 'active' })
  const notice = observeSnapshot(tracker, snapshot([], [event([early])]), observedAt).notices[0]
  const merged = snapshot([], [event([{ ...early, phase: 'historical' }], { id: 'new-parent' })])
  assert.equal(observeSnapshot(tracker, merged, observedAt).notices.length, 0)
  assert.deepEqual(resolveNoticeTarget(merged, notice), { workspace: 'content', eventId: 'new-parent', alertId: 'RB_root' })
})
