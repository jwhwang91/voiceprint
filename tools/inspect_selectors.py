"""셀렉터 점검 도구.

네이버 각 화면의 DOM 을 떠서 data/_inspect/ 에 저장하고, 셀렉터 후보를 자동으로 추려준다.
이 산출물을 Claude Code 가 읽고 config/selectors.yaml 을 정확히 채운다.

사용:
    python tools/inspect_selectors.py login-check
    python tools/inspect_selectors.py list  --id <blog_id>
    python tools/inspect_selectors.py view  --url <글 URL>
    python tools/inspect_selectors.py write --id <blog_id>

브라우저가 뜨면(로그인 안 돼 있으면) 직접 로그인 후 터미널에서 Enter.
세션은 data/auth/<id>/ 에 저장되어 다음부터 로그인 생략.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Windows 콘솔(cp949)에서 특수문자 출력 시 죽지 않도록
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blog_automation.config import load_config, load_selectors  # noqa: E402
from blog_automation.utils.browser import browser_context        # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "_inspect"

# 셀렉터 후보 추출 시 주목할 키워드(클래스/속성에 포함되면 후보로)
KEYWORDS = [
    "title", "subject", "publish", "save", "submit", "btn", "image", "img",
    "photo", "upload", "editor", "se-", "tag", "content", "write", "list",
    "post", "category", "confirm", "login", "logout",
]

JS_CANDIDATES = """
() => {
  const kws = %KEYWORDS%;
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('button, a, input, [contenteditable], [class*="se-"]')) {
    const cls = (el.className && el.className.toString) ? el.className.toString() : '';
    const id = el.id || '';
    const hay = (cls + ' ' + id + ' ' + (el.getAttribute('aria-label')||'')).toLowerCase();
    if (!kws.some(k => hay.includes(k))) continue;
    const sig = el.tagName + '|' + id + '|' + cls;
    if (seen.has(sig)) continue;
    seen.add(sig);
    out.push({
      tag: el.tagName.toLowerCase(),
      id: id,
      cls: cls,
      type: el.getAttribute('type') || '',
      aria: el.getAttribute('aria-label') || '',
      editable: el.getAttribute('contenteditable') || '',
      text: (el.innerText || el.value || '').trim().slice(0, 40),
    });
  }
  return out;
}
"""


def _dump(name: str, html: str, candidates: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.html").write_text(html, encoding="utf-8")
    lines = [f"# 셀렉터 후보: {name}", ""]
    for c in candidates:
        sel = f"#{c['id']}" if c["id"] else (
            "." + ".".join(c["cls"].split()) if c["cls"] else c["tag"])
        lines.append(
            f"{c['tag']:14} sel={sel:55} "
            f"type={c['type']:8} editable={c['editable']:5} "
            f"aria='{c['aria']}' text='{c['text']}'")
    (OUT / f"{name}.candidates.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n저장됨: {OUT / (name + '.html')}")
    print(f"저장됨: {OUT / (name + '.candidates.txt')}  (후보 {len(candidates)}개)")
    print("→ 이 두 파일을 Claude Code 에게 'selectors.yaml 채워줘' 라고 하면 됩니다.\n")


def _candidates(scope):
    js = JS_CANDIDATES.replace("%KEYWORDS%", str(KEYWORDS))
    try:
        return scope.evaluate(js)
    except Exception as e:  # noqa: BLE001
        print(f"[경고] 후보 추출 실패: {e}")
        return []


def _enter_frame_if_any(page):
    """#mainFrame 이 있으면 frame, 없으면 page 반환."""
    el = page.query_selector("#mainFrame")
    if el:
        fr = el.content_frame()
        if fr:
            print("  (#mainFrame iframe 진입)")
            return fr
    return page


# 모든 inspect 명령이 같은 세션(로그인)을 공유하도록 고정 프로필 사용
PROFILE = "naver"


def _is_logged_in(page) -> bool:
    """네이버 홈에 '로그아웃' 버튼이 있으면 로그인된 상태로 판단."""
    page.goto("https://www.naver.com")
    page.wait_for_timeout(1500)
    return page.locator('[class*="btn_logout"]').count() > 0


def _ensure_login(cfg, page) -> None:
    """세션이 있으면 재사용, 없으면 .env 계정으로 자동 로그인(캡차 시 직접 처리)."""
    if _is_logged_in(page):
        print(">> 이미 로그인됨 (세션 재사용).")
        return
    sel = load_selectors()["login"]
    if cfg.naver_id and cfg.naver_pw and not cfg.naver_id.startswith("여기에"):
        print(">> .env 계정으로 자동 로그인 시도...")
        page.goto(sel["url"]); page.wait_for_timeout(1500)
        page.fill(sel["id_input"], cfg.naver_id)
        page.fill(sel["pw_input"], cfg.naver_pw)
        page.wait_for_timeout(400)
        try:
            page.click(sel["submit_button"])
        except Exception:  # noqa: BLE001
            page.keyboard.press("Enter")
        page.wait_for_timeout(3000)
    else:
        print(">> .env 에 계정이 없습니다. 브라우저에서 직접 로그인하세요.")
        page.goto(sel["url"])
    # 캡차/추가인증이 뜨면 사람이 처리할 수 있도록 한 번 대기
    if not _is_logged_in(page):
        print(">> 로그인 미완료(캡차/2단계 인증일 수 있음). 브라우저에서 완료 후 Enter...")
        input(">> 로그인 완료되면 Enter...")
    else:
        print(">> 로그인 성공.")


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login-check")
    pl = sub.add_parser("list");  pl.add_argument("--id", required=True)
    pv = sub.add_parser("view");  pv.add_argument("--url", required=True)
    pw = sub.add_parser("write"); pw.add_argument("--id", required=True)
    pd = sub.add_parser("dump", help="임의 URL DOM 덤프(댓글 셀렉터 등 확인용)")
    pd.add_argument("--url", required=True)
    pd.add_argument("--name", required=True, help="저장 파일명")
    args = p.parse_args()

    cfg = load_config()
    sel = load_selectors()

    with browser_context(cfg, profile=PROFILE) as (ctx, page):
        if args.cmd == "login-check":
            # 1) (로그아웃 상태면) 로그인 폼 셀렉터 확보
            page.goto(sel["login"]["url"]); page.wait_for_timeout(2000)
            if page.locator("#id").count():
                print("로그인 폼 감지 — 폼 셀렉터 덤프.")
                _dump("login_page", page.content(), _candidates(page))
            # 2) 자동 로그인(.env) 후 로그인된 홈 화면 덤프
            _ensure_login(cfg, page)
            page.goto("https://www.naver.com"); page.wait_for_timeout(1500)
            _dump("login_home", page.content(), _candidates(page))
            return 0

        _ensure_login(cfg, page)

        if args.cmd == "list":
            url = sel["blog"]["manage_url"].format(blog_id=args.id)
            print(f"이동: {url}")
            page.goto(url); page.wait_for_timeout(3000)
            scope = _enter_frame_if_any(page)
            _dump("post_list", scope.content(), _candidates(scope))

        elif args.cmd == "view":
            print(f"이동: {args.url}")
            page.goto(args.url); page.wait_for_timeout(3000)
            scope = _enter_frame_if_any(page)
            _dump("post_view", scope.content(), _candidates(scope))

        elif args.cmd == "dump":
            print(f"이동: {args.url}")
            page.goto(args.url); page.wait_for_timeout(4000)
            print(">> 댓글 영역이 보이도록 스크롤/펼친 뒤 Enter (필요시).")
            input(">> 준비되면 Enter...")
            scope = _enter_frame_if_any(page)
            _dump(args.name, scope.content(), _candidates(scope))

        elif args.cmd == "write":
            url = sel["write"]["url"].format(blog_id=args.id)
            print(f"이동: {url}")
            page.goto(url); page.wait_for_timeout(4000)
            # '작성 중인 글 불러오기' 팝업이 뜰 수 있음 — 사용자가 닫게 안내
            print(">> 에디터에 '이전 글 불러오기' 등 팝업이 뜨면 닫아주세요.")
            input(">> 에디터가 빈 새 글 상태가 되면 Enter...")
            scope = _enter_frame_if_any(page)
            _dump("write_editor", scope.content(), _candidates(scope))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
