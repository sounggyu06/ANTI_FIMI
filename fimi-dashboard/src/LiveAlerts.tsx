import { useEffect, useRef, useState } from 'react'
import { ArrowRight, Bell, CheckCheck, X } from 'lucide-react'
import type { DashboardData } from './types'
import { createLiveTracker, mergeNotices, NOTICE_LIMIT, observeSnapshot, resolveNoticeTarget } from './liveAlertState'
import type { LiveNotice, SignalTarget } from './liveAlertState'
import './LiveAlerts.css'

const receivedTime = (value: string) => new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
}).format(new Date(value))
const kindLabel = (notice: LiveNotice) => notice.kind === 'escalated' ? '검토 우선순위 상승' : notice.category === 'early' ? '자료 확산 조기 주의' : '새 행동 경보 후보'

export function useLiveAlerts(data: DashboardData | null) {
  const tracker = useRef(createLiveTracker())
  const [notices, setNotices] = useState<LiveNotice[]>([])
  const [changed, setChanged] = useState(new Set<string>())
  const [toast, setToast] = useState<LiveNotice[] | null>(null)
  const session = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (!data) return
    if (session.current !== data.session?.id) {
      session.current = data.session?.id
      tracker.current = createLiveTracker()
      setNotices([])
      setToast(null)
      setChanged(new Set())
    }
    const result = observeSnapshot(tracker.current, data, new Date().toISOString())
    setChanged(result.changed)
    if (result.notices.length) {
      setNotices(previous => mergeNotices(previous, result.notices))
      setToast(result.notices.slice(0, NOTICE_LIMIT))
    }
  }, [data])
  useEffect(() => {
    if (!changed.size) return
    const timer = window.setTimeout(() => setChanged(new Set()), 2400)
    return () => window.clearTimeout(timer)
  }, [changed])
  return { notices, changed, toast, setToast,
    markAllRead: () => setNotices(previous => previous.map(notice => ({ ...notice, read: true }))),
    markRead: (id: string) => setNotices(previous => previous.map(notice => notice.id === id ? { ...notice, read: true } : notice)),
  }
}

export default function LiveAlerts({ data, live, onNavigate }: { data: DashboardData | null; live: ReturnType<typeof useLiveAlerts>; onNavigate: (target: SignalTarget) => void }) {
  const [open, setOpen] = useState(false)
  const [paused, setPaused] = useState<string | null>(null)
  const [leaving, setLeaving] = useState<string | null>(null)
  const toggle = useRef<HTMLButtonElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const unread = live.notices.filter(notice => !notice.read).length
  const latest = live.toast?.[0]
  const { toast, setToast } = live
  useEffect(() => { if (open) heading.current?.focus() }, [open])
  useEffect(() => {
    if (!toast || paused === toast[0]?.id) return
    const fade = window.setTimeout(() => setLeaving(toast[0].id), 8000)
    const timer = window.setTimeout(() => setToast(null), 8240)
    return () => { window.clearTimeout(fade); window.clearTimeout(timer) }
  }, [toast, setToast, paused])
  const close = () => { setOpen(false); toggle.current?.focus() }
  const openNotice = (notice: LiveNotice) => {
    const target = data && resolveNoticeTarget(data, notice)
    if (!target) return
    live.markRead(notice.id)
    live.setToast(null)
    setOpen(false)
    onNavigate(target)
    toggle.current?.focus()
  }
  return <div className="live-alert-center" onKeyDown={event => { if (event.key === 'Escape') { close(); live.setToast(null) } }}>
    <button ref={toggle} data-testid="live-alert-toggle" className={`live-alert-toggle ${unread ? 'has-unread' : ''}`} aria-label={`실시간 알림, 미확인 ${unread}건`} aria-expanded={open} aria-controls="live-alert-history" onClick={() => setOpen(value => !value)}>
      <Bell key={live.notices[0]?.id ?? 'empty'} size={16} /><span>알림</span><b>{unread}</b>
    </button>
    <span className="live-alert-announcement" role="status" aria-live="polite" aria-atomic="true">{latest ? `${receivedTime(latest.observedAt)} 수신, 경보 변경 ${live.toast!.length}건. ${kindLabel(latest)}. ${latest.title}` : ''}</span>
    {open && <section id="live-alert-history" className="live-alert-history" aria-labelledby="live-alert-heading">
      <div className="live-alert-heading"><h2 ref={heading} tabIndex={-1} id="live-alert-heading">실시간 알림 <span>{live.notices.length}</span></h2><button aria-label="알림창 닫기" onClick={close}><X size={17} /></button></div>
      <div className="live-alert-toolbar"><span>접속 이후 최근 {NOTICE_LIMIT}건 · 수신 시각 KST</span><button disabled={!unread} onClick={live.markAllRead}><CheckCheck size={14} />모두 확인</button></div>
      <div className="live-alert-items">{live.notices.map(notice => {
        const available = data && resolveNoticeTarget(data, notice)
        return <button data-testid="live-notice" key={notice.id} className={`live-notice ${notice.read ? 'read' : 'unread'}`} disabled={!available} onClick={() => openNotice(notice)}>
          <span className="live-notice-meta"><strong>{kindLabel(notice)}</strong><time dateTime={notice.observedAt}>{receivedTime(notice.observedAt)}</time></span>
          <b>{notice.title}</b><span className="live-notice-summary">{notice.summary}</span><small>{available ? <><ArrowRight size={12} />사건·근거 열기</> : '현재 분석 목록에서 제외됨'}</small>
        </button>
      })}{!live.notices.length && <p className="live-alert-empty">새 경보와 우선순위 상승이 발생하면 표시됩니다. 첫 조회의 기존 경보는 제외합니다.</p>}</div>
      <p className="live-alert-footnote">탐지 후보 알림 · 확인 표시는 허위성 판정이 아닙니다.<br />새로고침하면 알림 기록이 초기화됩니다.</p>
    </section>}
    {latest && <aside key={latest.id} data-testid="live-alert-toast" className={`live-alert-toast ${leaving === latest.id ? 'leaving' : ''}`} aria-label="새 경보 알림" onMouseEnter={() => { setLeaving(null); setPaused(latest.id) }} onMouseLeave={() => setPaused(null)} onFocus={() => { setLeaving(null); setPaused(latest.id) }} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setPaused(null) }}>
      <div className="live-toast-heading"><Bell size={17} /><strong>{kindLabel(latest)}</strong><time>{receivedTime(latest.observedAt)} KST 수신</time><button aria-label="팝업 닫기" onClick={() => live.setToast(null)}><X size={16} /></button></div>
      <h3>{latest.title}</h3><p>{latest.summary}</p><div className="live-toast-actions"><span>{live.toast!.length > 1 ? `함께 수신한 변경 ${live.toast!.length}건` : '분석가 검증 필요'}</span><button onClick={() => { live.setToast(null); setOpen(true) }}>알림 목록 <ArrowRight size={13} /></button></div>
    </aside>}
  </div>
}
