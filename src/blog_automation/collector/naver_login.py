"""네이버 로그인.

권장: --manual-login (사람이 직접 로그인). 네이버는 자동 입력 시 캡차를 자주 띄운다.
자동 로그인은 보조 수단이며 실패할 수 있다.
"""
from __future__ import annotations

from playwright.sync_api import Page

from ..config import load_selectors
from ..logging_setup import get_logger
from ..utils.browser import safe_goto

log = get_logger()


def is_logged_in(page: Page, *, poll_s: int = 8) -> bool:
    """로그인 여부를 '여러 초에 걸쳐 폴링'으로 판단한다.

    예전엔 네이버 홈을 다시 로드한 뒤 **딱 1.2초**만 기다리고 로그아웃 버튼을
    확인했다. 네이버 홈이 느리거나 throttle(ERR_ABORTED) 걸리면 그 1.2초 안에
    버튼이 안 떠서 '로그인 안 됨'으로 오판 → 멀쩡한 세션인데도 재로그인/캡차로
    빠져 발행이 운빨로 실패했다(잘되다 안되다의 원인).

    개선:
      · 이미 네이버 페이지에 있고 로그인 인디케이터가 보이면 **재이동 없이** 즉시 True.
      · 아니면 홈으로 한 번 이동한 뒤, 1초 간격으로 최대 poll_s 초 동안 인디케이터를
        기다린다(한 번의 스냅샷이 아니라 폴링).
    """
    sels = load_selectors()
    sel = sels["login"]
    indicator = sel["success_indicator"]

    try:
        cur = page.url or ""
    except Exception:  # noqa: BLE001
        cur = ""
    on_naver = "naver.com" in cur
    on_login = "nidlogin" in cur or "captcha" in cur

    # 0-a) 이미 블로그 글쓰기 에디터(postwrite)에 들어와 있으면 = 로그인된 상태다.
    #   success_indicator 는 네이버 '홈'의 로그아웃 인디케이터라 에디터 페이지엔 없어서,
    #   앱(CDP)이 에디터를 띄워둔 채 publish 하면 멀쩡히 로그인됐는데도 False 로 오판해
    #   재로그인(→ nidlogin 이동 → ERR_ABORTED/다이얼로그 크래시)으로 빠졌다. 미로그인이면
    #   postwrite 는 nidlogin 으로 리다이렉트되므로, postwrite URL + 제목영역 존재 = 로그인.
    if on_naver and not on_login and "postwrite" in cur.lower():
        try:
            ta = sels.get("write", {}).get("title_area")
            if not ta or page.locator(ta).count() > 0:
                return True
        except Exception:  # noqa: BLE001
            return True

    # 0-b) 이미 네이버 화면이면 굳이 홈으로 재이동하지 않는다(throttle 위험·세션 흔들기 방지).
    if not on_naver or on_login:
        safe_goto(page, "https://www.naver.com")

    # 1) 1초 간격 폴링 — 느린 로드/일시 throttle 에도 인디케이터를 끝까지 기다린다.
    for _ in range(max(1, poll_s)):
        try:
            if page.locator(indicator).count() > 0:
                return True
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1000)
    # 마지막으로 한 번 더 확인(루프 마지막 대기 직후 떴을 수 있음).
    try:
        return page.locator(indicator).count() > 0
    except Exception:  # noqa: BLE001
        return False


def manual_login(page: Page, timeout_s: int = 180) -> None:
    """브라우저를 띄워 사용자가 직접 로그인하도록 대기(자동 감지, 최대 3분)."""
    sel = load_selectors()["login"]
    if "nidlogin" not in page.url:
        safe_goto(page, sel["url"])
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
        safe_goto(page, sel["url"])
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
