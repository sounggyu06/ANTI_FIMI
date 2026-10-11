import { useEffect, useState } from 'react'
import { FileImage, ShieldCheck, ShieldAlert, Info, UploadCloud, ExternalLink } from 'lucide-react'
import './MediaVerify.css'

type Result = {
  status: 'trusted' | 'valid_untrusted' | 'invalid' | 'missing' | 'unavailable' | 'rejected'
  label?: string
  explanation?: string
  error?: string
  sha256?: string
  bytes?: number
  mime?: string
  manifest_count?: number
  active_manifest?: string
  claim_generator?: string | null
  signer?: string | null
  validation_state?: string | null
  ai_record?: 'recorded' | 'not_recorded' | 'unknown'
  ai_actions?: string[]
  validation_codes?: { code: string; detail: string; success: boolean }[]
}

const MAX_BYTES = 6_000_000
const TYPES = ['image/jpeg', 'image/png', 'image/webp']
const labels: Record<Result['status'], string> = {
  trusted: '서명자 신뢰 확인', valid_untrusted: '서명자 신뢰 미확인', invalid: '검증 실패',
  missing: 'C2PA 정보 없음', unavailable: '분석 불가', rejected: '요청 거절',
}

/** Analyst-initiated C2PA check, independent of FIMI/CIB scoring; no uploads stored. */
export default function MediaVerify({ caseId }: { caseId: string }) {
  const [result, setResult] = useState<Result | null>(null)
  const [filename, setFilename] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { setResult(null); setFilename(''); setError('') }, [caseId])

  async function inspect(file?: File) {
    if (!file) return
    setResult(null); setError(''); setFilename(file.name)
    if (!TYPES.includes(file.type) || file.size > MAX_BYTES || file.size <= 0) {
      setError('JPG·PNG·WebP 파일만 허용하며 크기는 최대 6MB입니다.'); return
    }
    setPending(true)
    try {
      const response = await fetch('/api/media/verify', {
        method: 'POST', headers: { 'Content-Type': file.type, 'X-ANTI-FIMI-Client': 'dashboard' },
        body: file, cache: 'no-store',
      })
      const json = await response.json() as Result
      setResult(json)
      if (!response.ok) setError(json.error ?? '검증 요청에 실패했습니다.')
    } catch {
      setError('C2PA 검증 API 연결에 실패했습니다. 서버가 실행 중인지 확인하세요.')
    } finally {
      setPending(false)
    }
  }

  return <section className="media-verify panel" data-testid="media-verify">
    <div className="panel-heading"><div><h2><ShieldCheck size={16} />미디어 출처 검증 · C2PA</h2></div><span className="media-mode">분석가 수동 검토</span></div>
    <div className="media-verify-body">
      <p className="media-caption">현재 사건 <code>{caseId}</code>에 대해 이미지 원본의 출처 이력을 확인합니다. 결과는 이 화면에만 표시되며 DB에 저장되지 않습니다.</p>
      <label className="media-upload"><UploadCloud size={16} />{pending ? '검증 중…' : '이미지 선택 · JPG / PNG / WebP'}
        <input aria-label="C2PA 검증할 이미지" type="file" accept="image/jpeg,image/png,image/webp" disabled={pending}
          onChange={event => { const file = event.target.files?.[0]; void inspect(file); event.target.value = '' }} />
      </label>
      {filename && <div className="media-file"><FileImage size={13}/>{filename}</div>}
      {error && <div className="media-error" role="alert"><ShieldAlert size={15}/>{error}</div>}
      {result && <div className={`media-result media-result-${result.status}`} role="status">
        <strong>{labels[result.status]}</strong>
        {result.explanation && <p>{result.explanation}</p>}
        {result.sha256 && <dl><div><dt>파일 SHA-256</dt><dd><code title={result.sha256}>{result.sha256}</code></dd></div>
          {result.manifest_count !== undefined && <div><dt>매니페스트</dt><dd>{result.manifest_count}개</dd></div>}
          {result.claim_generator && <div><dt>기록 생성 도구</dt><dd>{result.claim_generator}</dd></div>}
          {result.signer && <div><dt>서명 인증서 발급자</dt><dd>{result.signer}</dd></div>}
          <div><dt>AI 생성 관련 기록</dt><dd>{result.ai_record === 'recorded' ? '명시적 기록 있음' : result.ai_record === 'not_recorded' ? '관련 기록 확인되지 않음' : '판단 불가'}</dd></div>
        </dl>}
        {result.ai_actions && result.ai_actions.length > 0 && <div className="media-ai-actions">{result.ai_actions.map((a, i) => <code key={`${a}-${i}`}>{a}</code>)}</div>}
        {result.validation_codes && result.validation_codes.length > 0 && <details><summary>검증 진단 {result.validation_codes.length}개</summary><ul>{result.validation_codes.map((item, i) => <li key={i}><code>{item.code}</code>{item.detail && <> — {item.detail}</>}</li>)}</ul></details>}
      </div>}
      <p className="media-limit"><Info size={13} />C2PA 정보가 없다는 것이 AI 생성 또는 조작의 증거는 아닙니다. 서명 검증은 콘텐츠 내용의 진실성을 보증하지 않습니다.</p>
      <a className="media-external" href="https://verify.contentauthenticity.org/" target="_blank" rel="noopener noreferrer">외부 Content Credentials Verify <ExternalLink size={12}/></a>
    </div>
  </section>
}
