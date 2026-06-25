"""HTML 스냅샷 민감정보 제거.

DOM self-healing/크롤러 실패 진단을 위해 HTML 을 저장할 때, 저장 전 반드시 이 함수를 거쳐
쿠키/토큰/세션ID/이메일/전화번호/비밀번호/광고계정 등 민감정보를 [REDACTED] 로 치환한다.
구조(태그/클래스)는 살려 self-healing 분석에 쓸 수 있게 하되, 값만 가린다.

원칙: 의심스러우면 가린다(과제거가 과노출보다 안전). Claude 에게 넘어가는 스냅샷에도 동일 적용.
"""
from __future__ import annotations

import re

_RED = "[REDACTED]"

# (패턴, 치환) 목록. 순서대로 적용한다. 대부분 캡처그룹 1을 살리고 값만 가린다.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # ── 비밀번호 input 의 value ──
    (re.compile(r'(<input\b[^>]*\btype\s*=\s*["\']password["\'][^>]*\bvalue\s*=\s*["\'])[^"\']*(["\'])',
                re.IGNORECASE), r"\1" + _RED + r"\2"),
    # ── name/id 가 민감해 보이는 input 의 value (password/token/secret/session/csrf/otp) ──
    (re.compile(r'(<input\b[^>]*\b(?:name|id)\s*=\s*["\'][^"\']*'
                r'(?:password|passwd|pwd|token|secret|session|csrf|otp|license|customer)[^"\']*["\'][^>]*'
                r'\bvalue\s*=\s*["\'])[^"\']*(["\'])', re.IGNORECASE), r"\1" + _RED + r"\2"),
    # ── <script> 블록 통째 비우기(토큰/세션/광고계정이 인라인 JS 에 박히는 경우) ──
    (re.compile(r"(<script\b[^>]*>).*?(</script>)", re.IGNORECASE | re.DOTALL), r"\1" + _RED + r"\2"),
    # ── Authorization / Bearer ──
    (re.compile(r'((?:authorization|bearer)\s*[:=]\s*["\']?)[A-Za-z0-9._\-+/=]+',
                re.IGNORECASE), r"\1" + _RED),
    # ── 토큰류 key=value (access_token, refresh_token, csrf, api_key, secret, session, jsessionid 등) ──
    (re.compile(r'((?:access[_-]?token|refresh[_-]?token|id[_-]?token|csrf[_-]?token|'
                r'api[_-]?key|client[_-]?secret|secret[_-]?key|access[_-]?license|'
                r'customer[_-]?id|session[_-]?id|sessionid|jsessionid|nid_aut|nid_ses|nid_jkl)'
                r'["\']?\s*[:=]\s*["\']?)[A-Za-z0-9._\-+/=%]+', re.IGNORECASE), r"\1" + _RED),
    # ── URL 쿼리스트링의 일반 토큰류 (?token= ?code= ?key= ?auth= ?sig= 등; href/redirect URL) ──
    #    qualified 토큰(access_token 등)은 위에서 잡지만, 로그인/캡차 redirect 의 bare 파라미터는 여기서.
    (re.compile(r'([?&](?:token|key|code|auth|secret|sig|signature|otp|state|ticket|session)=)'
                r'[^&"\'\s<>]+', re.IGNORECASE), r"\1" + _RED),
    # ── Set-Cookie / Cookie 헤더 ──
    (re.compile(r'((?:set-)?cookie\s*[:=]\s*).+', re.IGNORECASE), r"\1" + _RED),
    # ── data-* 에 박힌 토큰/세션 ──
    (re.compile(r'(\bdata-[\w-]*(?:token|secret|session|auth)[\w-]*\s*=\s*["\'])[^"\']*(["\'])',
                re.IGNORECASE), r"\1" + _RED + r"\2"),
    # ── 이메일 ──
    (re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'), _RED),
    # ── 한국 전화번호 (010-1234-5678 / 02-123-4567 / +82 등) ──
    (re.compile(r'(?<!\d)(?:\+?82[-\s]?)?0?1[016789][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)'), _RED),
    (re.compile(r'(?<!\d)0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)'), _RED),
    # ── 주민등록번호 형태 ──
    (re.compile(r'(?<!\d)\d{6}[-\s]?[1-4]\d{6}(?!\d)'), _RED),
    # ── 네이버 광고계정/customer id 라벨 근처 숫자 ──
    (re.compile(r'(customer[_\s-]?id\D{0,8})\d{4,}', re.IGNORECASE), r"\1" + _RED),
]

# 쿠키/세션 이름이 들어간 meta/hidden value 도 한 번 더 훑는다.
_HIDDEN_SENSITIVE = re.compile(
    r'(<(?:meta|input)\b[^>]*\b(?:name|id|property)\s*=\s*["\'][^"\']*'
    r'(?:csrf|token|secret|session|auth)[^"\']*["\'][^>]*\bvalue\s*=\s*["\'])[^"\']*(["\'])',
    re.IGNORECASE)


def sanitize_html_snapshot(html: str | None) -> str:
    """HTML 문자열에서 민감정보를 [REDACTED] 로 치환해 반환. 입력이 falsy 면 빈 문자열."""
    if not html:
        return html or ""
    out = html
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    out = _HIDDEN_SENSITIVE.sub(r"\1" + _RED + r"\2", out)
    return out
