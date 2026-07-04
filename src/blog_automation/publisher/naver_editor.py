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
import time

from ..config import Config, load_selectors
from ..content.layout_planner import preview
from ..content.schema import (
    load_layout, validate_layout, get_image_files,
    representative_block_index, first_image_block_index, representative_warnings,
)
from ..logging_setup import get_logger
from ..utils.browser import browser_context, safe_goto
from ..utils.files import resolve_images
from .image_uploader import (
    upload_image, reset_group_failures, _focus_body, _dump_format_toolbar_state,
)
from .place_inserter import close_place_popup, insert_place
from ..collector import naver_login

log = get_logger()


def _norm_url(u: str) -> str:
    return (u or "").split("#")[0].split("?")[0].rstrip("/")


def _open_fresh_write_page(page, write_url: str, blog_id: str) -> None:
    """항상 '새 글' 편집기로 진입한다(직전 글에 이어쓰기/덮어쓰기 방지).

    앱의 임베드 네이버 뷰는 CDP 로 붙는 **영속 페이지**라, 직전 발행이 남긴 편집기가
    postwrite 에 그대로 떠 있다.

    ⭐ 핵심(반복 회귀의 진짜 원인): 발행은 설계상 **임시저장**까지만 하고 사람이 네이버
    '저장된 글'에서 최종 발행한다. 임시저장본은 고유 문서(documentId)를 가진다.
    - `safe_goto` 는 같은 URL 이면 재네비게이션을 건너뛴다 → 새 job 이 직전 글에 **이어써짐**.
    - `page.reload()` 는 **바로 그 직전 임시저장 문서를 같은 documentId 로 되살린다** → 새 job 을
      쓰고 임시저장하면 직전 임시저장본을 **덮어써 삭제**(실측 관측된 회귀).
    두 경우 모두 '직전 문서를 그대로 연 상태'가 문제다. 따라서 리로드/이어쓰기가 아니라
    **완전히 새 빈 문서**로 진입해야 직전 임시저장본이 '저장된 글'에 보존된다.

    해법: postwrite 로 **새로 navigate** 한다. 네이버는 이때 '작성 중이던 글이 있어요' 복구
    팝업을 띄우고(호출부가 '취소'=새로 작성으로 닫음) 새 documentId 의 빈 문서를 준다.
    - same-URL goto 는 Electron 임베드 뷰에서 ERR_ABORTED + safe_goto early-return 이므로,
      쿼리로 URL 을 살짝 바꿔(캐시버스트) 우회한다. URL 에 여전히 `/postwrite` 가 있어
      앱의 네이버 뷰 표시 트리거(정규식 /postwrite/)도 그대로 매칭된다.
    - ⭐ dirty SmartEditor 는 `addEventListener('beforeunload', …)` 로 이탈 확인을 건다.
      `window.onbeforeunload = null` 로는 이 리스너를 못 지워 goto 가 7ms 만에 ERR_ABORTED
      로 죽는다(실측). 그래서 goto 직전 **캡처 단계 beforeunload 차단 리스너**를 주입해
      에디터 리스너보다 먼저 실행되게 하고 `stopImmediatePropagation`+returnValue 클리어로
      이탈 프롬프트를 무력화한다. 그래야 goto 가 실제로 새 문서를 로드한다.
    - reload 폴백은 **쓰지 않는다** — reload 는 직전 임시저장 문서를 같은 documentId 로
      되살려 새 job 이 그 위에 이어써지거나 덮어써 삭제된다(실측 회귀). ERR_ABORTED 가
      나도 리로드하지 말고 진행한다(대개 새 문서 로드는 됐고 abort 는 네이버측 리다이렉트
      경합일 뿐 → 이후 복구팝업/ENTRY_STATE 로 확인).
    - 홈 등 다른 경로로 우회하면 안 됨(블로그 홈=레거시 프레임 → goto 가 임베드 뷰에서 멈춤,
      앱 뷰도 숨겨짐 — 이전 회귀).
    """
    log.info("[FRESH_ENTRY] 진입 전 page.url=%s (target=%s)", page.url, write_url)
    if _norm_url(page.url) == _norm_url(write_url):
        log.info("직전 발행 편집기 잔여 — 새 빈 문서로 강제 진입(직전 임시저장본 보존)")
        # 캡처 단계에서 beforeunload 를 선점·무력화(에디터의 addEventListener 리스너보다 먼저).
        try:
            page.evaluate(
                """() => {
                    try { window.onbeforeunload = null; } catch (e) {}
                    try {
                        window.addEventListener('beforeunload', function (e) {
                            e.stopImmediatePropagation();
                            e.preventDefault();
                            try { delete e.returnValue; } catch (_) {}
                            e.returnValue = undefined;
                        }, true);
                    } catch (e) {}
                }"""
            )
        except Exception:  # noqa: BLE001
            pass
        # 캐시버스트 쿼리로 same-URL ERR_ABORTED/early-return 을 피하며 새 문서 init 유도.
        sep = "&" if "?" in write_url else "?"
        fresh_url = f"{write_url}{sep}_fresh={int(time.time())}"
        try:
            page.goto(fresh_url, wait_until="domcontentloaded", timeout=20000)
            log.info("[FRESH_ENTRY] goto 성공 → page.url=%s", page.url)
        except Exception as exc:  # noqa: BLE001
            # ERR_ABORTED 라도 리로드하지 않는다(리로드=직전 문서 복원=회귀). 새 문서 로드는
            # 대개 됐으므로 그대로 진행 — 이후 복구팝업 취소 + ENTRY_STATE 로 결과 확인.
            log.warning("[FRESH_ENTRY] goto 예외(리로드 안 함, 그대로 진행) → page.url=%s : %s",
                        page.url, exc)
        return
    safe_goto(page, write_url)


def _dump_fresh_entry_state(page, frame, sel) -> None:
    """진입 직후 에디터 상태 + 떠 있는 팝업을 읽기 전용으로 로깅(원인 확정용)."""
    # 1) 에디터에 남아있는 제목/본문(새 문서면 둘 다 비어야 정상)
    try:
        title_txt = (frame.locator(sel["write"]["title_area"]).first.inner_text() or "").strip()
    except Exception:  # noqa: BLE001
        title_txt = "<read-fail>"
    try:
        body_txt = (frame.locator(".se-section-text").first.inner_text() or "").strip()
    except Exception:  # noqa: BLE001
        body_txt = "<read-fail>"
    try:
        img_n = frame.locator(sel["write"].get("image_component") or ".se-component.se-image").count()
    except Exception:  # noqa: BLE001
        img_n = -1
    log.info("[ENTRY_STATE] url=%s | 제목=%r | 본문 %s자(앞:%r) | 이미지 %s개",
             page.url, title_txt[:30],
             len(body_txt) if body_txt != "<read-fail>" else body_txt, body_txt[:40], img_n)

    # 2) 실제로 떠 있는 팝업/다이얼로그 전수 덤프(class + 버튼 텍스트). 복구 팝업의 진짜
    #    클래스/버튼 라벨을 확정해 popup_sel/취소 로직을 맞추기 위함.
    try:
        popups = page.evaluate(
            """() => {
                const out = [];
                const seen = new Set();
                const nodes = document.querySelectorAll(
                    '[class*="popup"],[class*="layer"],[role="dialog"],[role="alertdialog"]');
                for (const el of nodes) {
                    const r = el.getBoundingClientRect();
                    if (r.width < 40 || r.height < 20) continue;        // 숨김/미미한 것 제외
                    const cls = (el.className || '').toString();
                    if (!cls || seen.has(cls)) continue;
                    seen.add(cls);
                    const btns = Array.from(el.querySelectorAll('button, a[role="button"], [class*="button"]'))
                        .map(b => (b.innerText || b.textContent || '').trim())
                        .filter(t => t && t.length <= 20);
                    out.push({ cls: cls.slice(0, 120), btns: btns.slice(0, 8) });
                    if (out.length >= 12) break;
                }
                return out;
            }"""
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("[ENTRY_STATE] 팝업 덤프 실패: %s", exc)
        popups = []
    if popups:
        for p in popups:
            log.info("[ENTRY_POPUP] class=%s | buttons=%s", p.get("cls"), p.get("btns"))
    else:
        log.info("[ENTRY_POPUP] (감지된 팝업 없음)")


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
        #    ⭐ 반드시 '새 글'로 리셋 — 직전 발행 편집기가 남아 이어쓰기 되는 것 방지.
        _open_fresh_write_page(page, sel["write"]["url"].format(blog_id=blog_id), blog_id)
        main_frame = sel["write"].get("main_frame")
        frame = page
        if main_frame:
            frame_el = page.wait_for_selector(main_frame)
            frame = frame_el.content_frame()

        # 에디터 로드 완료 대기
        frame.wait_for_selector(sel["write"]["title_area"], timeout=30000)
        page.wait_for_timeout(1500)

        # ⭐ 진단 덤프(읽기 전용): 진입 직후 에디터에 뭐가 들어있는지 + 실제로 떠 있는
        #    팝업(클래스·버튼 텍스트)을 그대로 찍는다. "새 글인데 이어써진다" 재현 시
        #    이 로그로 ① 새 문서 진입 실패인지 ② 복구 팝업 셀렉터/버튼 미스매치인지 확정.
        _dump_fresh_entry_state(page, frame, sel)

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

        # ⭐ 자가치유: 이전 run 이 실패하며 남긴 '장소 검색' 팝업이 이 에디터 페이지(임베드
        #    '네이버 보기' 뷰는 같은 URL 재진입 시 리로드하지 않아 팝업이 그대로 남는다)에
        #    떠 있으면 먼저 닫는다. 안 닫으면 title/본문 클릭·이미지 업로드가 전부 막혀
        #    "지도 검색창 띄운 채 리셋 안 됨" 상태가 반복된다.
        close_place_popup(page, frame)

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
