"""라이브 DOM 조회 도구 — 자가치유(self-healing)용.

발행 중 셀렉터가 깨지면, claude 가 이 도구로 **살아있는 네이버 화면의 DOM** 을 직접 조회해
(앱 안 WebContentsView 에 CDP 로 붙어) 어느 셀렉터가 깨졌는지 진단하고 새 셀렉터 후보를 받는다.
추측(트레이스백) 대신 실측으로 config/selectors.yaml 을 고치게 한다.

앱(Electron) 안에서 돌면 VOICEPRINT_CDP_ENDPOINT 로 임베드 화면에 붙고,
밖에서 돌면 browser_context 가 persistent context 를 띄운다(이 경우 --editor 로 에디터 이동).

사용:
  python main.py inspect-dom                      # 현재 페이지의 write/login 셀렉터 건강검진
  python main.py inspect-dom --section write       # 특정 섹션만
  python main.py inspect-dom --selector '<css>'     # 셀렉터 하나 매칭 수/상세
  python main.py inspect-dom --text '발행'           # 보이는 텍스트로 요소 찾기
  python main.py inspect-dom --list buttons         # 상호작용 요소 나열(buttons/inputs/editable/links)
  python main.py inspect-dom --html '<css>'          # 첫 매칭 outerHTML
  python main.py inspect-dom --editor                # 먼저 에디터(postwrite)로 이동 후 검진
  python main.py inspect-dom --goto '<url>'          # 임의 URL 이동 후 검진
"""
from __future__ import annotations

from ..config import load_config, load_selectors
from ..utils.browser import browser_context

# evaluate 안에서 공용으로 쓰는 헬퍼(요소 정보 + '견고한 셀렉터' 제안).
# 네이버 클래스 해시(save_btn__m9KHH)는 빌드마다 바뀌므로 프로젝트 컨벤션대로 [class*="prefix"] 제안.
_HELPERS = r"""
  function clsStr(el){ var c = el.getAttribute && el.getAttribute('class'); return c || ''; }
  function suggest(el){
    var tag = el.tagName.toLowerCase();
    if (el.id && !/[0-9a-f]{6,}/i.test(el.id)) return '#'+el.id;
    var toks = clsStr(el).split(/\s+/).filter(Boolean);
    for (var i=0;i<toks.length;i++){
      var base = toks[i].replace(/(_{1,3}|--).*$/,'');   // __hash / ___hash / --hash 제거
      if (base && base.length>=4 && base!==toks[i]) return tag+'[class*="'+base+'"]';
    }
    for (var j=0;j<toks.length;j++){
      if (toks[j].length>=4 && !/[0-9a-f]{6,}/i.test(toks[j])) return tag+'.'+toks[j];
    }
    var al = el.getAttribute && el.getAttribute('aria-label');
    if (al) return tag+'[aria-label="'+al+'"]';
    return tag;
  }
  function info(el){
    var t = (el.innerText || el.textContent || '').trim().replace(/\s+/g,' ').slice(0,60);
    var attrs = {};
    if (el.attributes) for (var i=0;i<el.attributes.length;i++){
      var a = el.attributes[i];
      if (a.name.indexOf('data-')===0 || ['role','aria-label','placeholder','type','contenteditable','title'].indexOf(a.name)>=0)
        attrs[a.name] = a.value;
    }
    return { tag: el.tagName.toLowerCase(), id: el.id||'', cls: clsStr(el).slice(0,150), text: t, attrs: attrs, suggest: suggest(el) };
  }
"""

_JS_LIST = "(arg) => {" + _HELPERS + r"""
  var sel = {
    buttons: 'button, [role="button"]',
    inputs: 'input, textarea',
    editable: '[contenteditable="true"], [contenteditable=""]',
    links: 'a[href]',
    interactive: 'button, [role="button"], input, textarea, a[href], [contenteditable="true"], [contenteditable=""]'
  }[arg.kind] || arg.kind;
  var els = Array.prototype.slice.call(document.querySelectorAll(sel));
  var out = [];
  for (var i=0;i<els.length && out.length<arg.cap;i++){
    var el = els[i];
    var r = el.getClientRects(); if (!r || !r.length) continue;   // 보이는 것만
    out.push(info(el));
  }
  return { total: els.length, items: out };
}"""

_JS_TEXT = "(arg) => {" + _HELPERS + r"""
  var all = Array.prototype.slice.call(document.querySelectorAll('button,a,span,div,label,input,textarea,h1,h2,h3,li'));
  var needle = arg.needle, out = [];
  for (var i=0;i<all.length && out.length<arg.cap;i++){
    var el = all[i];
    var own = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').trim();
    if (!own || own.indexOf(needle)<0) continue;
    if (own.length>80) continue;                                  // 큰 컨테이너 제외(잎 노드 우선)
    var r = el.getClientRects(); if (!r || !r.length) continue;
    out.push(info(el));
  }
  return { items: out };
}"""

_NON_SELECTOR_HINTS = ("url", "_url", "_api")


def _looks_like_selector(key: str, val) -> bool:
    if not isinstance(val, str) or not val:
        return False
    if val.startswith("http") or "{blog_id}" in val or "{" in val:
        return False
    if any(key == h or key.endswith(h) for h in _NON_SELECTOR_HINTS):
        return False
    if key == "main_frame":
        return False
    return True


def _blog_id(cfg, override: str | None) -> str:
    if override:
        return override
    try:
        pub = cfg.section("publish")
        if pub.get("blog_id"):
            return pub["blog_id"]
    except Exception:
        pass
    try:
        eng = cfg.section("engage")
        if eng.get("my_blog_id"):
            return eng["my_blog_id"]
    except Exception:
        pass
    return getattr(cfg, "naver_id", "") or "default"


def _health(page, sel: dict, sections: list[str]) -> None:
    print("--- selector health (sections: %s) ---" % ", ".join(sections))
    any_miss = False
    for section in sections:
        block = sel.get(section) or {}
        for key, val in block.items():
            if not _looks_like_selector(key, val):
                continue
            label = f"{section}.{key}"
            try:
                n = page.locator(val).count()
            except Exception as e:  # 유효하지 않은 셀렉터
                print(f"[ERR    ] {label:<26} {val}   ({type(e).__name__})")
                continue
            if n > 0:
                print(f"[OK  x{n:<2}] {label:<26} {val}")
            else:
                any_miss = True
                print(f"[MISS   ] {label:<26} {val}")
    if any_miss:
        print("\nHINT: [MISS] 는 네이버가 바꾼 것. --text '<버튼글자>' 또는 --list buttons/editable 로")
        print("      새 요소를 찾고, 제안된 suggest 셀렉터로 config/selectors.yaml 을 고친 뒤 다시 발행하세요.")
    else:
        print("\n모든 셀렉터 매칭됨 — DOM 셀렉터 문제는 아닐 가능성(네트워크/로그인/타이밍 확인).")


def _print_items(items: list[dict]) -> None:
    if not items:
        print("(없음)")
        return
    for it in items:
        attrs = " ".join(f'{k}="{v}"' for k, v in (it.get("attrs") or {}).items())
        line = f'- {it["tag"]:<8} suggest={it["suggest"]}'
        if it.get("text"):
            line += f'  text="{it["text"]}"'
        if attrs:
            line += f'  [{attrs}]'
        if it.get("cls"):
            line += f'  class="{it["cls"]}"'
        print(line)


def run_inspect_dom(cfg, *, selector=None, text=None, list_kind=None, html=None,
                    section=None, editor=False, goto=None, blog_id=None) -> None:
    sel = load_selectors()
    bid = _blog_id(cfg, blog_id)

    with browser_context(cfg, profile=bid) as (_ctx, page):
        if goto:
            page.goto(goto)
        elif editor:
            page.goto(sel["write"]["url"].format(blog_id=bid))

        try:
            print(f"URL: {page.url}")
            print(f"TITLE: {page.title()}")
        except Exception:
            pass

        if selector:
            try:
                n = page.locator(selector).count()
            except Exception as e:
                print(f"[ERR] '{selector}' 는 유효한 셀렉터가 아닙니다 ({type(e).__name__}: {e})")
                return
            print(f"\n--- selector '{selector}' → {n} matches ---")
            if n:
                items = page.locator(selector).evaluate_all(
                    "(els) => {" + _HELPERS + " return els.slice(0,8).map(info); }")
                _print_items(items)
            else:
                print("매칭 0 — 깨진 셀렉터. --text / --list 로 대체 후보를 찾으세요.")
            return

        if text:
            print(f"\n--- elements containing text '{text}' ---")
            res = page.evaluate(_JS_TEXT, {"needle": text, "cap": 40})
            _print_items(res.get("items", []))
            return

        if list_kind:
            print(f"\n--- list: {list_kind} ---")
            res = page.evaluate(_JS_LIST, {"kind": list_kind, "cap": 80})
            print(f"(보이는 것 {len(res.get('items', []))} / 전체 {res.get('total', 0)})")
            _print_items(res.get("items", []))
            return

        if html:
            loc = page.locator(html)
            if loc.count() == 0:
                print(f"\n'{html}' 매칭 없음.")
                return
            outer = loc.first.evaluate("(el) => el.outerHTML")
            print(f"\n--- outerHTML of '{html}' (first, 3000자) ---")
            print(outer[:3000])
            return

        # 기본: 셀렉터 건강검진
        sections = [section] if section else ["write", "login"]
        _health(page, sel, sections)
