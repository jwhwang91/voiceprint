"""HTML 스냅샷 민감정보 제거(sanitize_html_snapshot) 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blog_automation.seo.html_sanitizer import sanitize_html_snapshot  # noqa: E402


def test_redacts_password_input_value():
    html = '<input type="password" name="pw" value="hunter2secret">'
    out = sanitize_html_snapshot(html)
    assert "hunter2secret" not in out
    assert "[REDACTED]" in out
    # 구조는 보존
    assert 'type="password"' in out
    assert 'name="pw"' in out


def test_redacts_email():
    html = '<span>contact me at john.doe@example.com please</span>'
    out = sanitize_html_snapshot(html)
    assert "john.doe@example.com" not in out
    assert "[REDACTED]" in out


def test_redacts_kr_phone():
    html = '<p>연락처 010-1234-5678 입니다</p>'
    out = sanitize_html_snapshot(html)
    assert "010-1234-5678" not in out
    assert "[REDACTED]" in out


def test_redacts_access_token_value():
    html = 'access_token=abc123DEF456ghi789 in the body'
    out = sanitize_html_snapshot(html)
    assert "abc123DEF456ghi789" not in out
    assert "[REDACTED]" in out


def test_redacts_set_cookie_header():
    html = 'Set-Cookie: session=verysecretcookievalue; Path=/; HttpOnly'
    out = sanitize_html_snapshot(html)
    assert "verysecretcookievalue" not in out
    assert "[REDACTED]" in out


def test_redacts_nid_aut_cookie_token():
    html = 'NID_AUT=Zm9vYmFyTOKEN123abc; Domain=.naver.com'
    out = sanitize_html_snapshot(html)
    assert "Zm9vYmFyTOKEN123abc" not in out
    assert "[REDACTED]" in out


def test_empty_input_returns_empty_string():
    assert sanitize_html_snapshot("") == ""


def test_none_input_returns_empty_string():
    assert sanitize_html_snapshot(None) == ""


def test_ordinary_markup_preserved():
    html = '<div class="x">hello world</div>'
    out = sanitize_html_snapshot(html)
    assert out == html
    assert '<div class="x">' in out
    assert "[REDACTED]" not in out
