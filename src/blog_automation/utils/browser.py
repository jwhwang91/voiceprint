"""Playwright 브라우저 팩토리.

- 세션(쿠키)을 data/auth/ 에 저장/복원해서 매번 로그인하지 않도록 함(persistent context).
- 네이버 봇 탐지 회피를 위한 최소한의 stealth 설정 포함.
- 데스크톱 앱(Electron) 안에서 돌 때는 VOICEPRINT_CDP_ENDPOINT 가 주어지며, 그 경우
  새 브라우저를 띄우지 않고 앱이 띄운 네이버 화면(WebContentsView)에 CDP 로 붙어 조작한다.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import BrowserContext, Page, sync_playwright

from ..logging_setup import get_logger

log = get_logger()


def safe_goto(page: Page, url: str, *, tries: int = 3, wait_ms: int = 1500, **kwargs) -> None:
    """page.goto 를 ERR_ABORTED 경합에 견고하게 감싼다.

    Electron 임베드 네이버 뷰는 동시 네비게이션이 겹치면(앱이 홈으로 리셋 + 발행기가 goto,
    또는 네이버 throttle) goto 가 net::ERR_ABORTED 로 죽는다 — 대개 일시적이라 재시도하면 된다.
    """
    def _norm(u: str) -> str:
        return (u or "").split("#")[0].split("?")[0].rstrip("/")

    # 이미 목표 URL 에 있으면(앱이 에디터를 띄워둔 채 publish) 같은 URL 로의 재네비게이션은
    # Electron 임베드 뷰에서 net::ERR_ABORTED 로 죽는다 — 굳이 다시 가지 않는다.
    try:
        if _norm(page.url) == _norm(url):
            return
    except Exception:  # noqa: BLE001
        pass

    last = None
    for i in range(tries):
        try:
            page.goto(url, **kwargs)
            return
        except Exception as e:  # noqa: BLE001
            last = e
            msg = str(e)
            if "ERR_ABORTED" in msg or "aborted" in msg.lower():
                # 경합으로 abort 됐어도 실제로는 목표 URL 에 도착해 있을 수 있다 → 도착했으면 성공 취급.
                try:
                    if _norm(page.url) == _norm(url):
                        log.info("goto: ERR_ABORTED 지만 목표 URL 도착 — 성공 취급: %s", url)
                        return
                except Exception:  # noqa: BLE001
                    pass
                log.info("goto 경합(ERR_ABORTED) — 재시도 %d/%d: %s", i + 1, tries, url)
                try:
                    page.wait_for_timeout(wait_ms)
                except Exception:  # noqa: BLE001
                    pass
                continue
            raise
    if last:
        raise last


def _auto_accept_dialogs(context, page) -> None:
    """네이티브 JS 다이얼로그(beforeunload/confirm/alert)를 자동 수락한다.

    Electron 임베드 네이버 뷰(CDP)에서 dirty postwrite 에디터를 떠나며 goto 하면
    onbeforeunload '이 페이지를 떠나시겠습니까?' 네이티브 다이얼로그가 뜬다.
    핸들러가 없으면 Playwright 기본 처리가 'No dialog is showing' 으로 레이스를 일으켜
    Node 드라이버가 uncaught ProtocolError 로 죽었다(발행 통째 실패). 직접 핸들러를
    등록하면 기본 처리를 끄고 우리가 accept 하므로 안전하게 페이지를 떠난다.
    """
    def _accept(d):
        try:
            d.accept()
        except Exception:  # noqa: BLE001
            pass
    for target in (context, page):
        try:
            target.on("dialog", _accept)
        except Exception:  # noqa: BLE001
            pass


_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
"""


def _is_app_or_devtools(url: str) -> bool:
    """앱 UI(file://...index.html) 나 devtools 페이지면 True (네이버 뷰가 아님)."""
    u = url or ""
    return (not u) or u.startswith("file:") or u.startswith("devtools:") \
        or "index.html" in u or "devtools" in u


def _pick_naver_page(browser) -> tuple[BrowserContext, Page]:
    """CDP 로 붙은 브라우저에서 앱이 띄운 '네이버 화면'(WebContentsView)을 고른다.

    ⚠️ 앱의 네이버 뷰는 `persist:naver` 파티션이라 메인 창과 **다른 BrowserContext** 에 산다.
    예전엔 `browser.contexts[0]` 한 곳만 뒤져서, 네이버 뷰를 못 찾으면 `context.new_page()` 로
    엉뚱한(로그인 안 된·창에 안 붙은) **새 탭**을 열어버렸다. 그래서 **모든 컨텍스트**를 순회해
    이미 떠 있는 네이버 뷰를 재사용한다(새 탭을 만들지 않음 → 로그인 1회 유지·자가치유 시 같은 화면 재사용).
    """
    contexts = list(browser.contexts) or [browser.new_context()]
    # 1순위: 네이버를 띄운 페이지(로그인 세션이 살아있는 임베드 뷰).
    for ctx in contexts:
        for p in list(ctx.pages):
            try:
                if "naver.com" in (p.url or ""):
                    return ctx, p
            except Exception:
                continue
    # 2순위: 앱 UI/devtools 가 아닌 실제 콘텐츠 뷰(=임베드 네이버 뷰. 딴 데 가 있어도 재사용 — 곧 goto 함).
    for ctx in contexts:
        for p in list(ctx.pages):
            try:
                if not _is_app_or_devtools(p.url or ""):
                    return ctx, p
            except Exception:
                continue
    # 마지막 수단: 새 탭(임베드 뷰를 못 찾은 CLI 단독 케이스 등). 첫 컨텍스트에 만든다.
    ctx = contexts[0]
    return ctx, ctx.new_page()


@contextmanager
def browser_context(cfg, profile: str = "default") -> Iterator[tuple[BrowserContext, Page]]:
    """(context, page) 를 yield. 앱 안이면 CDP 로 붙고, 아니면 persistent context 를 띄운다."""
    b = cfg.section("browser")
    cdp = os.getenv("VOICEPRINT_CDP_ENDPOINT", "").strip()

    with sync_playwright() as pw:
        if cdp:
            # 앱(Electron)이 띄운 네이버 화면에 붙는다 — 브라우저를 새로 띄우지 않는다.
            browser = pw.chromium.connect_over_cdp(cdp)
            # persist:naver 뷰는 메인 창과 다른 컨텍스트라 모든 컨텍스트를 뒤져 찾는다(새 탭 금지).
            context, page = _pick_naver_page(browser)
            context.set_default_timeout(b.get("timeout_ms", 30000))
            _auto_accept_dialogs(context, page)
            try:
                context.add_init_script(_STEALTH_JS)  # 이후 네비게이션에 적용
            except Exception:
                pass
            try:
                yield context, page
            finally:
                # 브라우저/뷰는 앱이 소유한다 — 닫지 않는다(끊기만 함).
                pass
        else:
            user_data_dir = Path(cfg.auth_dir) / profile
            user_data_dir.mkdir(parents=True, exist_ok=True)
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=b.get("headless", False),
                slow_mo=b.get("slow_mo_ms", 0),
                locale=b.get("locale", "ko-KR"),
                viewport=b.get("viewport", {"width": 1280, "height": 900}),
                user_agent=b.get("user_agent") or None,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context.set_default_timeout(b.get("timeout_ms", 30000))
            context.add_init_script(_STEALTH_JS)
            page = context.pages[0] if context.pages else context.new_page()
            _auto_accept_dialogs(context, page)
            try:
                yield context, page
            finally:
                context.close()
