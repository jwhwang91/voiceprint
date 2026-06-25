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
from ..content.schema import (
    load_layout, validate_layout, get_image_files,
    representative_block_index, first_image_block_index, representative_warnings,
)
from ..logging_setup import get_logger
from ..utils.browser import browser_context
from ..utils.files import resolve_images
from .image_uploader import (
    upload_image, reset_group_failures, _focus_body, _dump_format_toolbar_state,
)
from .place_inserter import insert_place
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

    # 대표 이미지(썸네일) 비치명적 경고 — 발행을 막지 않고 알리기만(사람이 임시저장본에서 확인).
    for w in representative_warnings(layout):
        log.warning("대표 이미지: %s", w)
    if not yes:
        try:
            answer = input("이대로 진행할까요? (y/N) ").strip().lower()
        except EOFError:
            # 비대화형 실행(파이프/`!`/CI 등)에서는 stdin 이 없어 input() 이 EOFError.
            # 안전하게 중단한다(브라우저 자동화로 진행하지 않음). 자동 진행은 --yes 사용.
            log.info("비대화형 환경이라 확인 프롬프트를 받을 수 없어 중단합니다. "
                     "자동 진행하려면 --yes 를 붙이세요.")
            return
        if answer != "y":
            log.info("취소됨.")
            return

    blog_id = (layout.get("blog_id")
               or cfg.section("engage").get("my_blog_id")
               or cfg.naver_id)

    # 그룹 레이아웃/업로드 설정(없으면 안전 기본값)
    group_layout = pub.get("group_layout", "콜라주")  # 그룹 기본=콜라주(슬라이드 금지)
    group_upload_mode = pub.get("group_upload_mode", "group")
    layout_budget_ms = pub.get("layout_popup_budget_ms", 4000)
    save_layout_shots = pub.get("save_layout_screenshots", True)

    # 대표 이미지(썸네일) 처리 계획.
    #   · 네이버 기본: '첫 이미지'가 썸네일. 대표가 첫 이미지면 클릭 불필요(가장 안전).
    #   · 대표가 첫 이미지가 아닐 때만 에디터에서 [대표] 버튼 클릭이 필요한데, 그 DOM 이
    #     아직 미확정이라 enforce_representative_click(기본 false)일 때만 시도한다.
    rep_idx = representative_block_index(layout)
    first_img_idx = first_image_block_index(layout)
    enforce_rep_click = pub.get("enforce_representative_click", False)
    if rep_idx is not None and rep_idx == first_img_idx:
        log.info("대표 이미지: 첫 이미지 블록(blocks[%d])이 대표 — 네이버 기본 썸네일과 일치(클릭 불필요)", rep_idx)
    elif rep_idx is not None and not enforce_rep_click:
        log.warning("대표 이미지: 대표(blocks[%d])가 첫 이미지가 아님. enforce_representative_click=false 라 "
                    "에디터 클릭을 생략 → 네이버 기본(첫 이미지)이 썸네일이 됩니다. 대표를 첫 이미지로 "
                    "배치하거나, 첫 실행의 [REPRESENTATIVE_DUMP] 로 대표 버튼을 확정한 뒤 true 로 켜세요.", rep_idx)

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

        for idx, blk in enumerate(layout["blocks"]):
            t = blk["type"]
            if t in ("text", "heading", "quote"):
                # 진단(읽기 전용, 클릭/키입력 없음): 타이핑 직전 서식 툴바 상태를 확인해
                # 직전 블록(특히 그룹 사진)이 서식 토글을 켠 채 남겼는지 핀포인트한다.
                # 활성 감지 시 WARNING 으로 정확히 어느 블록 경계가 오염됐는지 드러난다.
                _dump_format_toolbar_state(page, tag=f"before-text-block#{idx}")
                # 직전 그룹(슬라이드/콜라주) 캡션·서식 컨텍스트에서 빠져나와 깨끗한 본문
                # 문단에 caret 을 놓는다. 이걸 안 하면 그룹 뒤 caret 이 캡션/선택 상태에
                # 남아 다음 텍스트가 취소선 등 서식을 물려받아 글 전체로 번진다.
                _focus_body(page, frame, sel)
                page.keyboard.type(blk.get("content", ""), delay=15)
                page.keyboard.press("Enter")
                page.wait_for_timeout(100)
            elif t == "image":
                # photos/<카테고리>/ 하위까지 재귀 해석(validate 통과 → 정확히 1개 매치).
                paths = [resolve_images(photos_dir, f)[0] for f in get_image_files(blk)]
                # 이 블록이 대표이고, 첫 이미지가 아니며, enforce 가 켜졌을 때만 에디터에서
                # [대표] 클릭을 시도한다(첫 이미지면 네이버 기본으로 이미 대표 → 클릭 불필요).
                set_rep = (idx == rep_idx and enforce_rep_click and idx != first_img_idx)
                # 캡션/블록 간 Enter 는 upload_image 가 소유한다(여기서 따로 입력 X).
                upload_image(
                    page, frame, sel, paths,
                    wait_ms=pub.get("per_image_wait_ms", 3500),
                    # layout 키가 없거나 null/"" 이면 기본값(콜라주)으로. 빈 값이 None 으로
                    # 새어 들어가 레이아웃 선택이 깨지는 일 방지.
                    group_layout=(blk.get("layout") or group_layout),
                    group_upload_mode=group_upload_mode,
                    layout_popup_budget_ms=layout_budget_ms,
                    save_screenshots=save_layout_shots,
                    caption=blk.get("caption"),
                    set_representative=set_rep,
                )
                page.wait_for_timeout(200)
            elif t == "place":
                # 네이버 '장소(지도)' 카드. 실패해도 비치명적(글 발행은 계속).
                insert_place(page, frame, sel, blk)
                page.wait_for_timeout(200)
            elif t == "tags":
                tag_text = " ".join("#" + x for x in blk.get("items", []))
                page.keyboard.type(tag_text, delay=15)

        # 5) 저장/발행 — ⭐ 어떤 모드든 '페이지를 떠나기 전 반드시 임시저장'한다.
        #    (dry-run 포함. 사람이 네이버 '저장된 글'에서 이어받아 최종 발행하도록.)
        # 저장 전 남아있는 팝업/오버레이 정리
        from .image_uploader import _dismiss_popup as _dp
        _dp(page)
        page.wait_for_timeout(500)

        def _save_draft() -> None:
            page.click(sel["write"]["save_draft_button"], force=True)
            # 임시저장 AJAX 가 끝날 시간을 준다(비대화형 종료 시 저장 유실 방지).
            page.wait_for_timeout(2500)
            log.info("임시저장 완료 — 네이버 '내 블로그 > 저장된 글'에서 검토 후 직접 발행하세요.")

        # dry-run 도 예외 없이 임시저장한다(이전엔 저장 없이 떠나 사람이 인계 못 했음).
        _save_draft()

        if dry_run:
            log.info("dry-run: 임시저장까지만 수행(최종 발행은 사람이 직접).")
            try:
                input("브라우저에서 확인 후 Enter 를 누르면 종료합니다... ")
            except EOFError:
                # 비대화형 실행(파이프/`!`/CI)에서는 멈출 수 없으니 바로 종료(이미 임시저장됨).
                log.info("비대화형 환경 — Enter 대기 없이 종료합니다.")
            page.wait_for_timeout(500)
            return

        if not pub.get("save_as_draft", True):
            # 자동 발행을 명시적으로 요청한 경우에만(임시저장은 이미 끝난 상태).
            page.click(sel["write"]["publish_open_button"])
            page.wait_for_timeout(800)
            page.click(sel["write"]["publish_confirm_button"])
            log.info("발행 완료.")
        page.wait_for_timeout(3000)
