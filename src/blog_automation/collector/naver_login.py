"""네이버 로그인.

권장: --manual-login (사람이 직접 로그인). 네이버는 자동 입력 시 캡차를 자주 띄운다.
자동 로그인은 보조 수단이며 실패할 수 있다.
"""
from __future__ import annotations

from playwright.sync_api import Page

from ..config import load_selectors
from ..logging_setup import get_logger

log = get_logger()


def is_logged_in(page: Page) -> bool:
    sel = load_selectors()["login"]
    page.goto("https://www.naver.com")
    page.wait_for_timeout(1200)
    return page.locator(sel["success_indicator"]).count() > 0


def manual_login(page: Page, timeout_s: int = 180) -> None:
    """브라우저를 띄워 사용자가 직접 로그인하도록 대기(자동 감지, 최대 3분)."""
    sel = load_selectors()["login"]
    if "nidlogin" not in page.url:
        page.goto(sel["url"])
    log.info("브라우저에서 직접 로그인하세요. 로그인 완료를 자동 감지합니다(최대 %d초)...", timeout_s)
    steps = timeout_s // 4
    for _ in range(steps):
        page.wait_for_timeout(4000)
        # 로그인 완료 = 로그인/캡차 페이지를 벗어남
        if "nidlogin" not in page.url and "captcha" not in page.url:
            log.info("로그인 완료.")
            return
    raise TimeoutError(f"{timeout_s}초 내에 로그인이 완료되지 않았습니다.")


def ensure_login(cfg, page: Page) -> None:
    """세션 재사용 → .env 자동 로그인 → (실패 시)수동 브라우저 로그인."""
    if is_logged_in(page):
        log.info("이미 로그인됨(세션 재사용).")
        return
    sel = load_selectors()["login"]
    if cfg.naver_id and cfg.naver_pw and not cfg.naver_id.startswith("여기에"):
        log.info(".env 계정으로 자동 로그인 시도...")
        page.goto(sel["url"])
        page.wait_for_timeout(1500)
        page.fill(sel["id_input"], cfg.naver_id)
        page.fill(sel["pw_input"], cfg.naver_pw)
        page.wait_for_timeout(400)
        try:
            page.click(sel["submit_button"])
        except Exception:  # noqa: BLE001
            page.keyboard.press("Enter")
        # 로그인 페이지 벗어나기까지 대기(최대 10s)
        for _ in range(10):
            page.wait_for_timeout(1000)
            if "nidlogin" not in page.url and "captcha" not in page.url:
                log.info("자동 로그인 성공.")
                return
        log.warning("자동 로그인 실패(캡차 또는 추가인증). 브라우저에서 직접 로그인하세요.")
    manual_login(page)


def auto_login(page: Page, naver_id: str, naver_pw: str) -> None:
    """ID/PW 자동 입력 로그인(캡차 시 실패 가능)."""
    sel = load_selectors()["login"]
    page.goto(sel["url"])
    # 사람처럼 타이핑
    page.fill(sel["id_input"], "")
    page.type(sel["id_input"], naver_id, delay=90)
    page.type(sel["pw_input"], naver_pw, delay=90)
    page.click(sel["submit_button"])
    page.wait_for_load_state("networkidle")
    log.info("자동 로그인 시도 완료. 캡차/추가인증이 뜨면 직접 처리 후 Enter...")
    input()
