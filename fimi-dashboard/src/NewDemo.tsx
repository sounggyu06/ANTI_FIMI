import { useRef, useState } from 'react'
import { RotateCcw } from 'lucide-react'
import './NewDemo.css'

export default function NewDemo({ enabled, connected = false, onReset }: { enabled: boolean; connected?: boolean; onReset: () => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function reset() {
    setBusy(true); setError(null)
    try { await onReset(); dialog.current?.close() }
    catch (caught) { setError(caught instanceof Error ? caught.message : '새 시연을 시작하지 못했습니다.') }
    finally { setBusy(false) }
  }
  return <>
    <button className="refresh-button" disabled={!enabled || busy} onClick={() => { setError(null); dialog.current?.showModal() }}><RotateCcw size={14} /><span>새 시연</span></button>
    <dialog ref={dialog} className="new-demo-dialog" aria-labelledby="new-demo-title" onCancel={event => { if (busy) event.preventDefault() }}>
      <h2 id="new-demo-title">빈 상태로 새 시연을 시작합니다</h2>
      <p>게시물·계정·그래프·경보·화면 알림을 초기화합니다. 이전 시연 기록은 별도 저장소에 보존하며 운용표와 탐지 설정은 유지합니다.</p>
      <p>{connected ? '연결된 사이트 시뮬레이션도 중지·초기화하고 수집기를 새 시연 ID로 다시 연결합니다. 수집 준비가 완료되면 사이트에서 시뮬레이션을 시작하세요.' : '사이트 시뮬레이션은 별도로 중지·초기화하세요. 외부 크롤러는 새 시연 ID로 새 수집을 시작해야 합니다.'}</p>
      {error && <p role="alert" className="new-demo-error">{error}</p>}
      <div><button className="refresh-button" disabled={busy} onClick={() => dialog.current?.close()}>취소</button><button className="primary-button" disabled={busy} onClick={() => void reset()}>{busy ? '초기화 중…' : '새 시연 시작'}</button></div>
    </dialog>
  </>
}
