"""Opt-in local C2PA image provenance verification; independent from ANTI_FIMI detection.

Uploads are kept in memory only, not persisted or tied to CIB probabilities.
Install the optional official c2pa Python SDK (`py -m pip install c2pa-python`).
"""
from __future__ import annotations

import hashlib
from io import BytesIO
import json
from typing import Any

MAX_IMAGE_BYTES = 6_000_000
_ALLOWED_MIMES = {'image/jpeg', 'image/png', 'image/webp'}


def identify_image(data: bytes) -> str | None:
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


def _text(value: Any, limit: int = 150) -> str | None:
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ('name', 'title', 'issuer', 'id'):
            if value.get(key):
                return _text(value[key], limit)
    return None


def _status_details(report: dict) -> list[dict[str, str | bool]]:
    entries = report.get('validation_status') or []
    # Newer schemas also expose validation_results.activeManifest.*
    results = report.get('validation_results') or {}
    if isinstance(results, dict):
        active = results.get('activeManifest') or {}
        if isinstance(active, dict):
            for arr in active.values():
                if isinstance(arr, list):
                    entries = (entries if isinstance(entries, list) else []) + arr
    output, seen = [], set()
    if not isinstance(entries, list):
        return output
    for item in entries:
        if not isinstance(item, dict):
            continue
        code = _text(item.get('code'), 110)
        if not code or code in seen:
            continue
        seen.add(code)
        output.append({'code': code, 'detail': _text(item.get('explanation'), 200) or '',
                       'success': item.get('success') is True})
        if len(output) >= 20:
            break
    return output


def _ai_actions(manifest: dict) -> list[str]:
    """Only explicit C2PA digitalSourceType assertions count as AI-related records."""
    findings: list[str] = []
    known = {'trainedalgorithmicmedia', 'trainedalgorithmicdata',
             'compositewithtrainedalgorithmicmedia', 'algorithmicmedia'}
    for assertion in manifest.get('assertions', []):
        if not isinstance(assertion, dict) or not str(assertion.get('label', '')).startswith('c2pa.actions'):
            continue
        data = assertion.get('data') or {}
        if not isinstance(data, dict):
            continue
        for action in data.get('actions', []):
            if not isinstance(action, dict):
                continue
            src = action.get('digitalSourceType') or action.get('digital_source_type')
            if not isinstance(src, str):
                continue
            src_type = src.rsplit('/', 1)[-1].split('#')[-1].lower()
            if src_type in known:
                findings.append(f"{_text(action.get('action'), 60) or '작업'}: {src_type}")
    return findings[:10]


def interpret_report(report: dict, digest: str, size: int, mime: str) -> dict:
    """Do not equate 'no validation error' with trusted signer or authentic content."""
    manifests = report.get('manifests')
    label = report.get('active_manifest')
    if not isinstance(manifests, dict) or not isinstance(label, str) or label not in manifests:
        return {'status': 'missing', 'label': 'C2PA 기록 없음', 'sha256': digest,
                'bytes': size, 'mime': mime, 'ai_record': 'unknown', 'ai_actions': [],
                'explanation': '파일에서 검증 가능한 활성 C2PA 기록을 찾지 못했습니다. AI 생성 여부는 판단할 수 없습니다.'}
    manifest = manifests[label] if isinstance(manifests[label], dict) else {}
    codes = _status_details(report)
    state = str(report.get('validation_state') or '').lower()
    failed_code = any(item['success'] is False and item['code'].lower().startswith(
        ('assertion.', 'claim.', 'ingredient.', 'signingcredential.', 'algorithm.', 'timeStamp.'.lower(),
         'general.', 'manifest.', 'assertiondata.')) for item in codes)
    # A validation_status entry generally denotes a validation problem; success:true is informational.
    has_error = failed_code or any(not entry['success'] for entry in codes)
    if state == 'invalid' or has_error:
        status, label_ko = 'invalid', 'C2PA 검증 실패'
    elif state == 'trusted':
        status, label_ko = 'trusted', 'C2PA 유효 · 서명자 신뢰 확인'
    else:
        status, label_ko = 'valid_untrusted', 'C2PA 오류 미보고 · 서명자 신뢰 미확인'
    actions = _ai_actions(manifest)
    sig = manifest.get('signature_info') if isinstance(manifest.get('signature_info'), dict) else {}
    return {
        'status': status, 'label': label_ko, 'sha256': digest, 'bytes': size, 'mime': mime,
        'active_manifest': _text(label, 180), 'manifest_count': len(manifests),
        'validation_state': report.get('validation_state') if state in ('trusted', 'valid', 'invalid') else None,
        'validation_codes': codes, 'claim_generator': _text(manifest.get('claim_generator'), 180),
        'signer': _text(sig.get('issuer'), 180) or _text(sig.get('name'), 180),
        'ai_record': 'recorded' if actions else 'not_recorded', 'ai_actions': actions,
        'explanation': ('서명·기록 검증 오류가 보고됐습니다. 기록의 진위 확인이 필요합니다.' if status == 'invalid'
                        else 'C2PA 기록의 유효성을 검사했습니다. 이미지 내용의 진실성이나 AI 생성 여부 전부를 보증하지 않습니다.'),
    }


def verify_bytes(data: bytes, mime: str, *, sdk=None) -> tuple[int, dict]:
    size, digest = len(data), hashlib.sha256(data).hexdigest()
    base = {'sha256': digest, 'bytes': size, 'mime': mime}
    if size > MAX_IMAGE_BYTES or size == 0:
        return 413, {'status': 'rejected', 'error': '이미지 크기는 1바이트부터 6MB까지만 허용합니다.'}
    actual_mime = identify_image(data)
    if actual_mime not in _ALLOWED_MIMES or actual_mime != mime:
        return 415, {'status': 'rejected', 'error': 'JPG·PNG·WebP 이미지만 지원하며 실제 파일 형식과 요청 형식이 일치해야 합니다.'}
    if sdk is None:
        try:
            import c2pa as sdk
        except ImportError:
            return 503, {'status': 'unavailable', 'error': 'C2PA SDK가 설치되지 않았습니다. py -m pip install c2pa-python', **base}
    try:
        # Official SDK Reader from media stream; no files written to disk.
        with sdk.Reader(mime, BytesIO(data)) as reader:
            parsed = json.loads(reader.json())
        if not isinstance(parsed, dict):
            raise ValueError('C2PA report is not an object')
        return 200, interpret_report(parsed, digest, size, mime)
    except Exception as exc:
        err = str(exc)
        if 'manifestnotfound' in err.replace(' ', '').lower() or 'no manifest' in err.lower():
            return 200, {'status': 'missing', 'label': 'C2PA 기록 없음', 'ai_record': 'unknown',
                         'ai_actions': [], 'explanation': '검증 가능한 C2PA 메타데이터가 존재하지 않습니다.', **base}
        return 200, {'status': 'unavailable', 'label': 'C2PA 분석 불가', 'ai_record': 'unknown',
                     'ai_actions': [], 'explanation': '파일을 분석하지 못했습니다. 지원 범위 또는 파일 손상을 확인하세요.',
                     'error_code': type(exc).__name__[:80], **base}


def handle_upload(headers, stream) -> tuple[int, dict]:
    if headers.get('Transfer-Encoding'):
        return 400, {'status': 'rejected', 'error': 'Chunked upload is not supported.'}
    try:
        length = int(headers.get('Content-Length', ''))
    except (TypeError, ValueError):
        return 411, {'status': 'rejected', 'error': 'Content-Length가 필요합니다.'}
    if length <= 0 or length > MAX_IMAGE_BYTES:
        return 413, {'status': 'rejected', 'error': '파일 크기는 최대 6MB입니다.'}
    mime = headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
    if mime not in _ALLOWED_MIMES:
        return 415, {'status': 'rejected', 'error': 'JPG, PNG 또는 WebP만 선택하세요.'}
    contents = stream.read(length)
    if len(contents) != length:
        return 400, {'status': 'rejected', 'error': '업로드 데이터가 불완전합니다.'}
    return verify_bytes(contents, mime)
