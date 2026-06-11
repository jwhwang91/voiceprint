"""Phase 3: 대상 글 방문 → 체류(2분+) → 댓글 등록.

기본은 dry_run(체류만, 등록 안 함). --go 또는 settings.engage.dry_run=false 일 때만 실제 등록.
사람처럼: 느린 스크롤로 체류시간 확보, 동작 사이 랜덤 지연, 소량만.

⚠️ 네이버 약관상 자동 댓글은 제재 위험. 사용자 책임 하에 보수적으로 사용.
"""
from __future__ import annotations

import random
from pathlib import Path

from playwright.sync_api import Page

from ..config import Config, load_selectors
from ..collector import naver_login
from ..logging_setup import get_logger
from ..utils.browser import browser_context
from ..utils.files import read_json

log = get_logger()


def _human_dwell(page: Page, seconds: float) -> None:
    """사람처럼 천천히 스크롤하며 최소 seconds 만큼 체류."""
    elapsed = 0.0
    direction = 1
    while elapsed < seconds:
        page.mouse.wheel(0, random.randint(250, 650) * direction)
        pause = random.uniform(2.5, 6.0)
        page.wait_for_timeout(int(pause * 1000))
        elapsed += pause
        if random.random() < 0.2:           # 가끔 위로 살짝(다시 읽는 척)
            direction = -1
        else:
            direction = 1
    log.info("  체류 %ds 완료", int(elapsed))


def _post_comment(page, sel: dict, comment: str) -> bool:
    """댓글창 열고 등록. 입력창은 contenteditable div(.u_cbox_text)."""
    tc = sel["target_comment"]
    scope = page
    if tc.get("main_frame"):
        fr_el = page.query_selector(tc["main_frame"])
        if fr_el and fr_el.content_frame():
            scope = fr_el.content_frame()

    # 댓글(cbox) lazy-load 트리거: 댓글 영역으로 스크롤
    try:
        scope.eval_on_selector(tc["comment_area"],
                               "e => e.scrollIntoView({block:'center'})")
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(1500)

    # 작성창 펼치기(접혀 있을 때만)
    opener = scope.query_selector(tc.get("comment_open_button") or "")
    if opener:
        try:
            opener.click()
            page.wait_for_timeout(1200)
        except Exception:  # noqa: BLE001
            pass

    area = scope.query_selector(tc["comment_textarea"])
    if not area:
        log.warning("  댓글 입력창(%s)을 찾지 못함", tc["comment_textarea"])
        return False
    # contenteditable: 포커스 후 키보드 입력
    area.click()
    page.wait_for_timeout(400)
    page.keyboard.type(comment, delay=55)
    page.wait_for_timeout(800)
    submit = scope.query_selector(tc["submit_button"])
    if not submit:
        log.warning("  등록 버튼(%s)을 찾지 못함", tc["submit_button"])
        return False
    submit.click()
    page.wait_for_timeout(2500)
    return True


def run_engage(cfg: Config, job: str, go: bool = False) -> None:
    eng = cfg.section("engage")
    dry_run = not go and eng.get("dry_run", True)
    sel = load_selectors()

    base = Path(cfg.collected_dir).parent / "engage" / job
    comments = read_json(base / "comments.json").get("comments", [])
    if not comments:
        log.error("comments.json 이 비어있습니다. 먼저 Claude Code 로 댓글을 생성하세요.")
        return

    print(f"\n=== 답방 대상 {len(comments)}개 (dry_run={dry_run}) ===")
    for c in comments:
        print(f"  [{c['nickname']}] {c['url']}\n      → {c['comment']}")
    if input("\n진행할까요? (y/N) ").strip().lower() != "y":
        log.info("취소됨.")
        return

    my_id = eng.get("my_blog_id")
    dwell = eng.get("dwell_seconds", 130)
    jitter = eng.get("dwell_jitter_seconds", 40)

    with browser_context(cfg, profile=my_id or "naver") as (ctx, page):
        naver_login.ensure_login(cfg, page)   # 댓글 등록엔 로그인 필요

        for i, c in enumerate(comments):
            log.info("[%d/%d] 방문: %s", i + 1, len(comments), c["url"])
            page.goto(c["url"])
            page.wait_for_timeout(3000)

            _human_dwell(page, dwell + random.uniform(0, jitter))  # 2분+ 체류 보장

            if dry_run:
                log.info("  dry-run: 댓글 등록 생략. (예정 댓글: %s)", c["comment"])
            else:
                ok = _post_comment(page, sel, c["comment"])
                log.info("  댓글 등록: %s", "성공" if ok else "실패/건너뜀")

            if i < len(comments) - 1:
                delay = eng.get("delay_between_posts_ms", 45000)
                delay = int(delay + random.uniform(0, delay * 0.4))  # 랜덤 가미
                log.info("  다음까지 %.0fs 대기...", delay / 1000)
                page.wait_for_timeout(delay)

    log.info("답방 완료(job=%s).", job)
