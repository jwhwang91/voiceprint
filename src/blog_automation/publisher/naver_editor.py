"""네이버 새 글 작성 자동화(SmartEditor ONE).

layout.json 의 blocks 를 위에서 아래로 순서대로 입력한다:
  text  → 본문 문단 입력
  image → image_uploader 로 사진 업로드(배치도 순서대로)
  tags  → 본문 끝 태그 입력

SmartEditor 는 #mainFrame iframe 안에서 동작하며 contenteditable 구조라 DOM 이 까다롭다.
config/selectors.yaml 의 write.* 를 최초 1회 확인해 채운 뒤 사용한다.
"""
from __future__ import annotations
import sys

from ..config import Config, load_selectors
from ..content.layout_planner import preview
from ..content.schema import load_layout, validate_layout, get_image_files
from ..logging_setup import get_logger
from ..utils.browser import browser_context
from .image_uploader import upload_image, reset_group_failures
from ..collector import naver_login

log = get_logger()


def run_publish(cfg: Config, job: str, dry_run: bool = False, yes: bool = False) -> None:
    sel = load_selectors()
    pub = cfg.section("publish")
    dry_run = dry_run or pub.get("dry_run", False)

    photos_dir = cfg.input_dir / job / "photos"
    layout = load_layout(cfg.drafts_dir, job)

    # 1) 배치도 검증 + 미리보기
    errors = validate_layout(layout, photos_dir)
    if errors:
        log.error("배치도 검증 실패:\n  - %s", "\n  - ".join(errors))
        raise SystemExit(1)
    def _safe_print(text: str) -> None:
        sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()

    _safe_print("\n===== 발행 미리보기 =====")
    _safe_print(preview(layout))
    _safe_print("=========================\n")
    if not yes and input("이대로 진행할까요? (y/N) ").strip().lower() != "y":
        log.info("취소됨.")
        return

    blog_id = (layout.get("blog_id")
               or cfg.section("engage").get("my_blog_id")
               or cfg.naver_id)

    # 그룹 레이아웃/업로드 설정(없으면 안전 기본값)
    group_layout = pub.get("group_layout", "슬라이드")
    group_upload_mode = pub.get("group_upload_mode", "group")
    layout_budget_ms = pub.get("layout_popup_budget_ms", 4000)
    save_layout_shots = pub.get("save_layout_screenshots", True)

    # 이전 run 의 연속 실패/덤프 상태 초기화
    reset_group_failures()

    with browser_context(cfg, profile=blog_id or "default") as (ctx, page):
        naver_login.ensure_login(cfg, page)

        # 2) 새 글 작성 화면 진입 (에디터는 iframe 아님 → page 에서 직접 동작)
        page.goto(sel["write"]["url"].format(blog_id=blog_id))
        main_frame = sel["write"].get("main_frame")
        frame = page
        if main_frame:
            frame_el = page.wait_for_selector(main_frame)
            frame = frame_el.content_frame()

        # 에디터 로드 완료 대기
        frame.wait_for_selector(sel["write"]["title_area"], timeout=30000)
        page.wait_for_timeout(1500)

        # '작성 중이던 글' 복구 팝업이 뜨면 닫기(취소) — 새 글로 시작
        popup_sel = '[class*="se-popup-alert"]'
        popup = page.locator(popup_sel)
        if popup.count() > 0:
            log.info("임시저장 복구 팝업 감지 — 취소 클릭")
            dismissed = False
            for label in ("취소", "닫기", "확인"):
                btn = popup.get_by_role("button", name=label)
                if btn.count() > 0:
                    try:
                        btn.first.click(timeout=2000)
                        dismissed = True
                        break
                    except Exception:  # noqa: BLE001
                        pass
            if dismissed:
                # 팝업이 사라질 때까지 대기
                try:
                    page.wait_for_selector(popup_sel, state="hidden", timeout=5000)
                except Exception:  # noqa: BLE001
                    pass
            page.wait_for_timeout(800)

        # 3) 제목 클릭 + 입력
        frame.click(sel["write"]["title_area"], force=True)
        page.wait_for_timeout(300)
        page.keyboard.type(layout.get("title", ""), delay=40)

        # 4) blocks 순서대로 입력
        # 본문 초기 포커스 1회만 클릭, 이후는 키보드만 사용 (se-caret SVG 인터셉트 회피)
        body_sel = sel["write"]["body_area"]
        frame.click(body_sel, force=True)
        page.wait_for_timeout(300)

        for blk in layout["blocks"]:
            t = blk["type"]
            if t in ("text", "heading", "quote"):
                page.keyboard.type(blk.get("content", ""), delay=15)
                page.keyboard.press("Enter")
                page.wait_for_timeout(100)
            elif t == "image":
                paths = [photos_dir / f for f in get_image_files(blk)]
                # 캡션/블록 간 Enter 는 upload_image 가 소유한다(여기서 따로 입력 X).
                upload_image(
                    page, frame, sel, paths,
                    wait_ms=pub.get("per_image_wait_ms", 3500),
                    group_layout=blk.get("layout", group_layout),
                    group_upload_mode=group_upload_mode,
                    layout_popup_budget_ms=layout_budget_ms,
                    save_screenshots=save_layout_shots,
                    caption=blk.get("caption"),
                )
                page.wait_for_timeout(200)
            elif t == "tags":
                tag_text = " ".join("#" + x for x in blk.get("items", []))
                page.keyboard.type(tag_text, delay=15)

        # 5) 저장/발행
        if dry_run:
            log.info("dry-run: 입력만 완료. 저장/발행 안 함. 브라우저에서 확인 후 Enter...")
            input()
            return
        # 저장 전 남아있는 팝업/오버레이 정리
        from .image_uploader import _dismiss_popup as _dp
        _dp(page)
        page.wait_for_timeout(500)
        if pub.get("save_as_draft", True):
            page.click(sel["write"]["save_draft_button"], force=True)
            log.info("임시저장 완료. 네이버에서 검토 후 직접 발행하세요(안전).")
        else:
            page.click(sel["write"]["publish_open_button"])
            page.wait_for_timeout(800)
            page.click(sel["write"]["publish_confirm_button"])
            log.info("발행 완료.")
        page.wait_for_timeout(3000)
