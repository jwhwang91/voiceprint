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

_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
"""


def _pick_naver_page(context: BrowserContext) -> Page:
    """CDP 로 붙은 컨텍스트에서 '네이버 화면' 페이지를 고른다.

    앱 UI(file://...index.html)나 devtools 가 아닌, 네이버를 띄운 WebContentsView 를 찾는다.
    """
    pages = list(context.pages)
    for p in pages:
        try:
            if "naver.com" in (p.url or ""):
                return p
        except Exception:
            continue
    # 아직 네이버로 안 간 빈 뷰라도 앱 UI 가 아니면 그걸 쓴다(곧 publish 가 goto 함).
    for p in pages:
        u = p.url or ""
        if not u.startswith("file:") and "index.html" not in u and "devtools" not in u:
            return p
    return context.new_page()


@contextmanager
def browser_context(cfg, profile: str = "default") -> Iterator[tuple[BrowserContext, Page]]:
    """(context, page) 를 yield. 앱 안이면 CDP 로 붙고, 아니면 persistent context 를 띄운다."""
    b = cfg.section("browser")
    cdp = os.getenv("VOICEPRINT_CDP_ENDPOINT", "").strip()

    with sync_playwright() as pw:
        if cdp:
            # 앱(Electron)이 띄운 네이버 화면에 붙는다 — 브라우저를 새로 띄우지 않는다.
            browser = pw.chromium.connect_over_cdp(cdp)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            context.set_default_timeout(b.get("timeout_ms", 30000))
            try:
                context.add_init_script(_STEALTH_JS)  # 이후 네비게이션에 적용
            except Exception:
                pass
            page = _pick_naver_page(context)
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
            try:
                yield context, page
            finally:
                context.close()
