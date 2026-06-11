"""Playwright 브라우저 팩토리.

- 세션(쿠키)을 data/auth/ 에 저장/복원해서 매번 로그인하지 않도록 함(persistent context).
- 네이버 봇 탐지 회피를 위한 최소한의 stealth 설정 포함.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import BrowserContext, Page, sync_playwright

_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
"""


@contextmanager
def browser_context(cfg, profile: str = "default") -> Iterator[tuple[BrowserContext, Page]]:
    """persistent context 를 열고 (context, page) 를 yield."""
    b = cfg.section("browser")
    user_data_dir = Path(cfg.auth_dir) / profile
    user_data_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
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
