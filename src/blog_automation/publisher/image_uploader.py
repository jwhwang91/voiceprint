"""SmartEditor 이미지 업로드.

SmartEditor ONE 이미지 삽입:
  - 상단 툴바의 사진 버튼(se-image-toolbar-button) 클릭
    -> "사진 첨부 방식" 팝업(내 PC에서 / MYBOX / 스마트폰)이 먼저 뜸
    -> "내 PC에서 추가" 클릭 -> OS 파일 다이얼로그
  - 파일 1개: 단독 이미지 블록
  - 파일 2+개: 슬라이드/콜라주/개별 레이아웃 선택 컨트롤이 뜸 (자동 처리)

레이아웃 선택 컨트롤의 실제 형태(dim-modal 팝업 vs 이미지 그룹에 붙는 인라인
컨트롤 스트립)는 네이버 빌드마다 다를 수 있어 아직 확정되지 않았다. 그래서 이
모듈은 컨테이너 클래스가 아니라 **라벨(개별/콜라주/슬라이드) 가시성**으로 컨트롤을
판별하고, 첫 그룹에서는 항상 [GROUP_CHOOSER_DUMP] 로 실제 DOM 을 한 번 남긴다.

설계 불변식(adversarial review 6종 시나리오 반영):
  1) 어떤 경우에도 무한 대기/장시간 정지 없음(모든 대기는 budget 으로 bound).
  2) 인라인 스트립에는 Escape 를 보내지 않는다(선택된 이미지 컴포넌트 파괴 위험).
     dim-modal 일 때만 Escape. 스트립은 본문 클릭(선택 해제)으로 정리한다.
  3) 컨트롤 판별은 라벨 기반(영구 에디터 chrome 으로 인한 오탐 방지).
  4) 매 업로드 직전 _ensure_clean_editor 로 이전 블록이 남긴 스트립/모달을 제거.
  5) 캡션/줄바꿈은 upload_image 가 소유한다(caller 와의 caret 협응 버그 제거).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from playwright.sync_api import Frame, Page

from ..logging_setup import get_logger

log = get_logger()

# ---------------------------------------------------------------------------
# 셀렉터 / 라벨 상수  (UI 바뀌면 GROUP_CHOOSER_DUMP 로그를 보고 여기를 고친다)
# ---------------------------------------------------------------------------

# dim-modal 팝업 컨테이너 후보(방식 선택 팝업/알림 등). Escape 대상은 이것뿐.
_POPUP_SELECTORS = [
    '[class*="se-popup-dim-transparent"]',
    '[class*="se-popup-dim"]',
    '[class*="se-popup"]',
    '[class*="se-dialog"]',
    '[class*="se-modal"]',
]

# 레이아웃 컨트롤 컨테이너 "후보" — 진단 덤프용으로만 쓴다(판별 게이트로는 쓰지 않음).
# ⚠️ 영구 에디터 chrome(se-property-toolbar / se-image-toolbar / role=toolbar)은
#    항상 보이므로 절대 넣지 않는다(그룹 미발견을 오탐으로 만든다).
_LAYOUT_CONTAINER_SELECTORS = [
    '[class*="se-imageStrip"]',
    '[class*="se-image-strip"]',
    '[class*="se-image-layout"]',
    '[class*="se-l-property"]',
    '[role="radiogroup"]',
    '[role="tablist"]',
]

# 선호 레이아웃 -> 클릭 매칭 토큰 후보
_LAYOUT_CHOICES: dict[str, tuple[str, ...]] = {
    "슬라이드": ("슬라이드", "슬라이드쇼", "slide"),
    "콜라주": ("콜라주", "collage", "그리드"),
    "개별": ("개별사진", "개별", "individual", "기본"),
    "2열": ("2열",),
}

# 컨트롤 판별/덤프에 쓰는 한글 라벨
_ALL_LAYOUT_LABELS = ("개별", "개별사진", "콜라주", "슬라이드", "슬라이드쇼", "2열")

# 선택 후 (있을 때만) 누르는 확정 버튼. 없으면 즉시 적용된 것으로 간주.
_CONFIRM_LABELS = ("적용", "완료", "확인", "등록")

# "사진 첨부 방식" 팝업에서 내 PC 업로드 버튼 텍스트 후보
_PC_UPLOAD_LABELS = ("내 PC에서", "내 PC에서 추가", "PC에서", "직접 올리기")

# 연속 그룹 실패 한계 — 초과하면 이번 run 의 남은 그룹은 개별 업로드로 자동 전환
_GROUP_FAIL_THRESHOLD_DEFAULT = 2

# 모듈 단위 상태(run 시작 시 reset_group_failures() 로 초기화)
_consecutive_group_failures = 0
_dumped_first_group = False


def reset_group_failures() -> None:
    """run_publish 시작 시 호출 — 이전 run 상태가 새 run 에 영향 주지 않도록."""
    global _consecutive_group_failures, _dumped_first_group
    _consecutive_group_failures = 0
    _dumped_first_group = False


# ---------------------------------------------------------------------------
# 팝업/오버레이 판별 & 정리
# ---------------------------------------------------------------------------

def _label_visible(page: Page, label: str) -> bool:
    """라벨이 텍스트 또는 아이콘(aria-label/title/alt)으로 화면에 보이면 True.

    아이콘만 있는 컨트롤(텍스트 없는 타일 버튼)도 잡기 위해 속성까지 확인한다.
    대기 없이 즉시 스냅샷 판정(빠름)."""
    try:
        base = page.get_by_text(label, exact=False)
        if base.count() > 0 and base.first.is_visible():
            return True
    except Exception:  # noqa: BLE001
        pass
    css = f'[aria-label*="{label}"], [title*="{label}"], [alt*="{label}"]'
    try:
        loc = page.locator(css)
        if loc.count() > 0 and loc.first.is_visible():
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _looks_like_layout_chooser(page: Page) -> bool:
    """레이아웃 옵션(개별/콜라주/슬라이드) 중 2개 이상 보이면 컨트롤이 떠 있는 것."""
    matches = 0
    for lab in ("개별", "콜라주", "슬라이드"):
        if _label_visible(page, lab):
            matches += 1
            if matches >= 2:
                return True
    return False


def _has_visible_dim_modal(page: Page) -> bool:
    """dim-modal 팝업이 실제로 보이는지(Escape 대상 존재 여부)."""
    for sel in _POPUP_SELECTORS:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def _dismiss_any_popup(page: Page) -> None:
    """화면에 떠있는 dim-modal 팝업/알림을 닫는다(인라인 스트립은 건드리지 않음)."""
    alert = page.locator('[class*="se-popup-alert"]')
    try:
        if alert.count() > 0:
            for label in ("취소", "닫기", "확인"):
                btn = alert.get_by_role("button", name=label)
                if btn.count() > 0:
                    try:
                        btn.first.click(timeout=1500)
                        page.wait_for_timeout(400)
                        return
                    except Exception:  # noqa: BLE001
                        pass
    except Exception:  # noqa: BLE001
        pass

    if _has_visible_dim_modal(page):
        for _ in range(2):
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            if not _has_visible_dim_modal(page):
                return


# naver_editor.py 에서 import 하는 이름을 그대로 유지
_dismiss_popup = _dismiss_any_popup


def _focus_body(page: Page, frame: Frame, sel: dict) -> None:
    """본문 마지막 문단을 클릭해 이미지 컴포넌트 선택을 해제한다(파괴적이지 않음).

    인라인 레이아웃 스트립은 선택이 이미지에서 벗어나면 접힌다. dim-modal 이
    떠 있으면 클릭이 가로채이므로 호출 전에 모달을 먼저 닫아야 한다."""
    body_sel = sel["write"]["body_area"]
    try:
        para = frame.locator(body_sel)
        n = para.count()
        if n > 0:
            para.nth(n - 1).click(force=True, timeout=2000)
            page.wait_for_timeout(150)
            return
    except Exception:  # noqa: BLE001
        pass
    try:
        frame.click(body_sel, force=True, timeout=2000)
        page.wait_for_timeout(150)
    except Exception:  # noqa: BLE001
        pass


def _ensure_clean_editor(page: Page, frame: Frame, sel: dict) -> None:
    """업로드 직전 호출 — 이전 블록이 남긴 dim-modal/인라인 스트립을 제거한다.

    이게 핵심 방어막: 늦게 뜬(또는 정리 못한) 컨트롤이 다음 블록의 툴바 클릭/
    파일 다이얼로그를 가로채는 것을 막는다(36초 정지 재발 방지)."""
    # 1) dim-modal/알림부터(Escape). 모달이 떠 있으면 본문 클릭이 안 먹는다.
    _dismiss_any_popup(page)
    # 2) 남은 인라인 레이아웃 스트립 -> 본문 클릭으로 선택 해제(Escape 금지)
    try:
        for _ in range(3):
            if not _looks_like_layout_chooser(page):
                break
            _focus_body(page, frame, sel)
            page.wait_for_timeout(200)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# 진단 덤프 (다음 실제 실행에서 정확한 DOM 을 확정하기 위함)
# ---------------------------------------------------------------------------

def _screenshots_dir() -> Path:
    root = Path(__file__).resolve().parents[3]  # publisher -> blog_automation -> src -> ROOT
    out = root / "logs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _dump_group_chooser_state(page: Page, tag: str, n_photos: int,
                              save_screenshot: bool = True) -> None:
    """그룹 레이아웃 컨트롤 상태를 한 번에 덤프(예외에 절대 안전).

    로그는 모두 '[GROUP_CHOOSER_DUMP]' 접두사를 달아 grep 가능하게 한다.
    """
    try:
        log.info("[GROUP_CHOOSER_DUMP] ===== begin tag=%s n_photos=%d =====", tag, n_photos)
        try:
            log.info("[GROUP_CHOOSER_DUMP] url=%s frames=%d", page.url, len(page.frames))
        except Exception:  # noqa: BLE001
            pass

        # 1) 후보 컨테이너 present/visible
        hits = []
        for s in _POPUP_SELECTORS + _LAYOUT_CONTAINER_SELECTORS:
            try:
                loc = page.locator(s)
                c = loc.count()
                if c:
                    vis = False
                    try:
                        vis = loc.first.is_visible(timeout=200)
                    except Exception:  # noqa: BLE001
                        pass
                    hits.append((s, c, vis))
            except Exception:  # noqa: BLE001
                pass
        log.info("[GROUP_CHOOSER_DUMP] container_hits=%s", hits)

        # 2) 보이는 클릭 가능한 요소 텍스트(버튼/role=button/탭/라디오)
        btn_texts = []
        try:
            loc = page.locator(
                'button:visible, [role="button"]:visible, [role="tab"]:visible, '
                '[role="radio"]:visible'
            )
            total = 0
            try:
                total = loc.count()
            except Exception:  # noqa: BLE001
                pass
            for i in range(min(total, 30)):
                try:
                    el = loc.nth(i)
                    t = (el.inner_text() or "").strip().replace("\n", " ")
                    aria = el.get_attribute("aria-label") or ""
                    title = el.get_attribute("title") or ""
                    if t or aria or title:
                        btn_texts.append({"text": t[:40], "aria": aria[:40], "title": title[:40]})
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass
        log.info("[GROUP_CHOOSER_DUMP] visible_controls=%r", btn_texts)

        # 3) 한글 레이아웃 라벨 존재/가시/태그
        label_hits = []
        for lab in _ALL_LAYOUT_LABELS + _CONFIRM_LABELS:
            try:
                base = page.get_by_text(lab, exact=False)
                cnt = base.count()
                vis = False
                tag_name = None
                if cnt:
                    el = base.first
                    try:
                        vis = el.is_visible(timeout=200)
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        tag_name = el.evaluate("e => e.tagName")
                    except Exception:  # noqa: BLE001
                        pass
                label_hits.append({"label": lab, "count": cnt, "visible": vis, "tag": tag_name})
            except Exception:  # noqa: BLE001
                pass
        log.info("[GROUP_CHOOSER_DUMP] label_hits=%r", label_hits)

        # 4) 매칭된 컨테이너(또는 activeElement)의 outerHTML
        html = ""
        matched = next((h[0] for h in hits if h[2]), None) or (hits[0][0] if hits else None)
        if matched:
            try:
                html = page.locator(matched).first.evaluate("e => e.outerHTML")
            except Exception:  # noqa: BLE001
                pass
        if not html:
            try:
                html = page.evaluate(
                    "() => { const a=document.activeElement;"
                    " return a ? (a.closest('[class]')||a).outerHTML : 'NO_ACTIVE'; }"
                )
            except Exception:  # noqa: BLE001
                pass
        log.info("[GROUP_CHOOSER_DUMP] container_outerHTML(%s)=%s",
                 matched, (html or "")[:4000].replace("\n", " "))

        # 5) 스크린샷
        shot_path = ""
        if save_screenshot:
            try:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                shot_path = str(_screenshots_dir() / f"group_chooser_{tag}_{ts}.png")
                page.screenshot(path=shot_path, timeout=4000)
            except Exception as e:  # noqa: BLE001
                log.warning("[GROUP_CHOOSER_DUMP] screenshot failed: %s", e)
                shot_path = ""
        log.info("[GROUP_CHOOSER_DUMP] screenshot=%s", shot_path)
        log.info("[GROUP_CHOOSER_DUMP] paste ALL lines containing GROUP_CHOOSER_DUMP "
                 "(pre+post) and attach newest logs/screenshots/group_chooser_*.png")
        log.info("[GROUP_CHOOSER_DUMP] ===== end tag=%s =====", tag)
    except Exception as exc:  # noqa: BLE001
        log.warning("[GROUP_CHOOSER_DUMP] dump failed: %s", exc)


# ---------------------------------------------------------------------------
# 툴바 / 방식 선택 팝업
# ---------------------------------------------------------------------------

def _click_toolbar_image_button(page: Page, frame: Frame, sel: dict) -> None:
    """상단 툴바의 이미지 삽입 버튼을 클릭한다."""
    image_btn_sel = sel["write"]["image_button"]

    toolbar_btn = frame.locator(f".se-toolbar {image_btn_sel}")
    try:
        if toolbar_btn.count() == 0:
            toolbar_btn = frame.locator(image_btn_sel).first
    except Exception:  # noqa: BLE001
        toolbar_btn = frame.locator(image_btn_sel).first

    toolbar_btn.scroll_into_view_if_needed()
    toolbar_btn.click(timeout=5000)


def _click_pc_upload_if_method_popup(page: Page) -> bool:
    """이미지 버튼 클릭 후 '사진 첨부 방식' 팝업이 뜨면 '내 PC에서 추가'를 클릭한다.

    팝업이 없으면 False(툴바 클릭이 바로 파일 다이얼로그를 연 경우).
    레이아웃 옵션이 보이면 방식 팝업이 아니므로 건드리지 않는다.
    """
    joined = ", ".join(_POPUP_SELECTORS)
    try:
        page.wait_for_selector(joined, timeout=2000, state="visible")
    except Exception:  # noqa: BLE001
        return False

    # 레이아웃 컨트롤이면 방식 팝업 아님
    if _looks_like_layout_chooser(page):
        return False

    log.info("사진 첨부 방식 팝업 감지 -> '내 PC에서 추가' 클릭 시도")
    for label in _PC_UPLOAD_LABELS:
        btn = page.locator(f'button:has-text("{label}")')
        try:
            if btn.count() > 0:
                btn.first.click(timeout=3000)
                log.info("'%s' 클릭 완료", label)
                return True
        except Exception:  # noqa: BLE001
            pass

    log.warning("내 PC 업로드 버튼을 찾지 못함 — 팝업 첫 번째 버튼 클릭")
    for sel in _POPUP_SELECTORS:
        try:
            container = page.locator(sel)
            if container.count() > 0:
                inner = container.first.locator("button").first
                inner.click(timeout=2000)
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


# ---------------------------------------------------------------------------
# 레이아웃 선택 처리
# ---------------------------------------------------------------------------

def _try_click_layout_option(page: Page, preferred: str) -> bool:
    """preferred 레이아웃 옵션을 클릭한다. 성공하면 True.

    텍스트는 '가장 가까운 클릭 가능 조상'을 클릭한다(모달에서 bare text 노드 클릭이
    라디오/타일 상태를 토글하지 못하는 문제 회피).
    확정 버튼은 가정하지 않는다(있을 때만 별도 처리).
    """
    tokens = _LAYOUT_CHOICES.get(preferred, (preferred,))
    ancestor = ("xpath=ancestor-or-self::*[self::button or self::a or self::li "
                "or @role='button' or @role='radio' or @role='tab'][1]")

    # 1) 텍스트 -> 클릭 가능 조상
    for tok in tokens:
        try:
            base = page.get_by_text(tok, exact=False)
            if base.count() == 0:
                continue
            el = base.first
            if not el.is_visible():
                continue
            target = el.locator(ancestor)
            clickable = target.first if target.count() > 0 else el
            clickable.click(timeout=2000)
            log.info("레이아웃 '%s' 선택 (text=%s)", preferred, tok)
            return True
        except Exception:  # noqa: BLE001
            pass

    # 2) role=button name
    for tok in tokens:
        try:
            btn = page.get_by_role("button", name=tok).first
            if btn.is_visible(timeout=200):
                btn.click(timeout=2000)
                log.info("레이아웃 '%s' 선택 (role=button name=%s)", preferred, tok)
                return True
        except Exception:  # noqa: BLE001
            pass

    # 3) aria-label / title / data 속성(아이콘 버튼 대비)
    for tok in tokens:
        css = (f'[aria-label*="{tok}"]:visible, [title*="{tok}"]:visible, '
               f'[data-name*="{tok}"]:visible, [data-log*="{tok}"]:visible')
        try:
            el = page.locator(css).first
            if el.is_visible(timeout=200):
                el.click(timeout=2000)
                log.info("레이아웃 '%s' 선택 (attr=%s)", preferred, tok)
                return True
        except Exception:  # noqa: BLE001
            pass

    # 4) class 토큰(se-l-slide/se-l-collage 등)
    class_token = {
        "슬라이드": "se-l-slide",
        "콜라주": "se-l-collage",
        "개별": "se-l-default",
    }.get(preferred)
    if class_token:
        try:
            el = page.locator(f'[class*="{class_token}"]:visible').first
            if el.is_visible(timeout=200):
                el.click(timeout=2000)
                log.info("레이아웃 '%s' 선택 (class=%s)", preferred, class_token)
                return True
        except Exception:  # noqa: BLE001
            pass

    return False


def _click_confirm_if_present(page: Page) -> None:
    """확정 버튼(적용/확인/완료/등록)이 보이면 클릭. 없으면 즉시 적용된 것으로 간주."""
    for label in _CONFIRM_LABELS:
        try:
            btn = page.get_by_role("button", name=label).first
            if btn.is_visible(timeout=200):
                btn.click(timeout=1500)
                log.info("레이아웃 확정 버튼 '%s' 클릭", label)
                return
        except Exception:  # noqa: BLE001
            pass


def _handle_layout_popup(page: Page, preferred: str, n_photos: int,
                         budget_ms: int = 4000,
                         save_screenshot: bool = True) -> str:
    """그룹 업로드 후 레이아웃 선택 컨트롤(인라인/모달)을 처리한다.

    반환(3-state):
      "applied" — 선호 레이아웃을 명시적으로 적용함
      "default" — 컨트롤이 안 떠 기본 레이아웃으로 삽입된 것으로 간주(실패 아님)
      "failed"  — 컨트롤은 떴으나 옵션 클릭 실패(개별 폴백 카운트 대상)

    절대 무한 대기하지 않는다. 인라인 스트립에는 Escape 를 보내지 않는다.
    """
    global _dumped_first_group
    force_dump = not _dumped_first_group
    _dumped_first_group = True

    # budget 동안 컨트롤이 뜰 때까지 폴링(느린/큰 이미지로 늦게 뜨는 경우 포착)
    chooser_seen = False
    loops = max(1, budget_ms // 250)
    for _ in range(loops):
        if _looks_like_layout_chooser(page):
            chooser_seen = True
            break
        page.wait_for_timeout(250)

    if not chooser_seen:
        # 컨트롤 미발견 -> 기본 레이아웃으로 자동 삽입된 것으로 간주(실패 아님).
        # 첫 그룹은 '정말 없는지' 확인용으로 한 번 덤프(스크린샷 포함).
        if force_dump:
            _dump_group_chooser_state(page, tag="pre-nochooser", n_photos=n_photos,
                                      save_screenshot=save_screenshot)
        log.info("레이아웃 컨트롤 미발견 — 기본 레이아웃으로 삽입된 것으로 간주")
        return "default"

    # 진단 덤프는 run 의 '첫 그룹'에서만(2026-06-11 실행으로 DOM 확정:
    # dim-modal "사진 첨부 방식" + 타일 개별사진/콜라주/슬라이드, 타일 클릭=즉시 적용).
    # 옵션 클릭 실패 시에는 아래 else 의 'post' 덤프가 따로 남으므로 진단은 충분.
    if force_dump:
        _dump_group_chooser_state(page, tag="pre", n_photos=n_photos,
                                  save_screenshot=save_screenshot)

    modal = _has_visible_dim_modal(page)
    applied = _try_click_layout_option(page, preferred)

    if applied:
        page.wait_for_timeout(300)
        # 모달이면 확정 버튼 + 모달이 실제로 사라질 때까지 대기(잔여 오버레이가
        # 다음 블록 클릭을 삼키는 문제 방지)
        if modal or _has_visible_dim_modal(page):
            _click_confirm_if_present(page)
            try:
                page.wait_for_selector(", ".join(_POPUP_SELECTORS),
                                       state="hidden", timeout=3000)
            except Exception:  # noqa: BLE001
                pass
    else:
        log.warning("선호 레이아웃 '%s' 옵션을 찾지 못함 -> 기본값 유지(폴백)", preferred)
        _dump_group_chooser_state(page, tag="post", n_photos=n_photos,
                                  save_screenshot=save_screenshot)

    # 정리: dim-modal 이 남았을 때만 Escape. 인라인 스트립에는 Escape 금지
    # (선택된 이미지 그룹을 지우거나 방금 적용한 레이아웃을 날릴 수 있음).
    # 인라인 스트립은 뒤따르는 캡션 입력/Enter, 그리고 다음 블록의
    # _ensure_clean_editor(본문 클릭)로 안전하게 접힌다.
    if _has_visible_dim_modal(page):
        for _ in range(2):
            page.keyboard.press("Escape")
            page.wait_for_timeout(250)
            if not _has_visible_dim_modal(page):
                break

    return "applied" if applied else "failed"


# ---------------------------------------------------------------------------
# 캡션/줄바꿈 (이미지 블록의 캡션과 블록 간 줄바꿈은 여기서 소유)
# ---------------------------------------------------------------------------

def _type_caption_and_advance(page: Page, caption: str | None) -> None:
    """캡션이 있으면 입력하고, 항상 Enter 한 번으로 다음 블록 위치(본문 새 문단)로 이동.

    삽입 직후 caret 은 보통 이미지 캡션 필드에 있으므로 단독 사진은 캡션이
    정상 부착된다(기존 동작 보존). 그룹은 컨트롤 형태에 따라 위치가 달라질 수
    있어 best-effort(임시저장 후 검토 권장).
    """
    if caption:
        try:
            page.keyboard.type(caption, delay=15)
            page.wait_for_timeout(100)
        except Exception:  # noqa: BLE001
            pass
    try:
        page.keyboard.press("Enter")
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(150)


# ---------------------------------------------------------------------------
# 단일 파일 업로드(재사용 코어)
# ---------------------------------------------------------------------------

def _upload_one(page: Page, frame: Frame, sel: dict, file_str: str,
                wait_ms: int) -> bool:
    """파일 하나를 삽입한다(레이아웃 컨트롤 없음). 성공 시 True. 캡션/Enter 는 호출자 책임."""
    _ensure_clean_editor(page, frame, sel)
    uploaded = False
    for attempt in range(3):
        try:
            with page.expect_file_chooser(timeout=8000) as fc_info:
                _click_toolbar_image_button(page, frame, sel)
                _click_pc_upload_if_method_popup(page)
            fc_info.value.set_files([file_str])
            uploaded = True
            break
        except Exception as exc:  # noqa: BLE001
            log.warning("업로드 시도 %d 실패: %s", attempt + 1, exc)
            if attempt < 2:
                page.wait_for_timeout(1200)
                _ensure_clean_editor(page, frame, sel)
    if not uploaded:
        return False
    page.wait_for_timeout(wait_ms)
    return True


def upload_group_individually(page: Page, frame: Frame, sel: dict,
                              file_strs: list[str], wait_ms: int,
                              *, caption: str | None = None) -> bool:
    """그룹 사진을 한 장씩 개별 업로드한다(레이아웃 컨트롤을 절대 트리거하지 않음).

    무한 대기를 원천 차단하는 안전 폴백. 슬라이드/콜라주 그룹화는 잃지만 행은 없다.
    첫 장부터 실패하면 툴바/셀렉터 문제로 보고 즉시 중단(수 분 dead-retry 방지).
    캡션/줄바꿈은 이 함수가 소유한다(caller 가 중복 입력하지 않음).
    """
    log.warning("개별 업로드 모드 — %d장을 한 장씩 삽입(그룹화 없음)", len(file_strs))
    ok_all = True
    n = len(file_strs)
    for i, f in enumerate(file_strs):
        ok = _upload_one(page, frame, sel, f, wait_ms)
        if not ok:
            log.error("개별 업로드 실패: %s", Path(f).name)
            ok_all = False
            if i == 0:
                log.error("첫 장부터 실패 — 툴바/셀렉터 문제로 보고 개별 업로드 중단")
                return False
            continue
        # 마지막 장이 아니면 줄바꿈으로 다음 삽입 위치 확보
        if i < n - 1:
            try:
                page.keyboard.press("Enter")
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(150)
    # 마지막 장 뒤에 캡션 + 줄바꿈(소유권 일원화 — caller 는 추가 입력 안 함)
    _type_caption_and_advance(page, caption)
    return ok_all


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def upload_image(page: Page, frame: Frame, sel: dict, image_paths: list[Path],
                 wait_ms: int = 3500, *, group_layout: str = "슬라이드",
                 group_upload_mode: str = "group",
                 layout_popup_budget_ms: int = 4000,
                 save_screenshots: bool = True,
                 group_fail_threshold: int = _GROUP_FAIL_THRESHOLD_DEFAULT,
                 caption: str | None = None) -> None:
    """이미지 블록 하나를 처리한다(삽입 + 그룹 레이아웃 + 캡션 + 줄바꿈).

    image_paths 1개 -> 단독 사진
    image_paths 2개 이상 -> 그룹(슬라이드/콜라주/개별)

    group_layout: 선호 그룹 레이아웃("슬라이드" 기본). layout.json image 블록의
        block["layout"] 값을 naver_editor 가 여기로 전달한다.
    group_upload_mode: "group"(기본) | "individual"(항상 개별 업로드).
    caption: 이미지 캡션(있으면). 캡션/블록 간 Enter 는 이 함수가 책임진다 —
        naver_editor 는 이미지 블록에 대해 따로 캡션/Enter 를 입력하지 않는다.

    (공개 positional 시그니처 upload_image(page, frame, sel, image_paths, wait_ms) 는
     유지. 나머지는 안전 기본값을 가진 keyword-only 인자다.)
    """
    global _consecutive_group_failures

    existing = [p for p in image_paths if p.exists()]
    for p in image_paths:
        if not p.exists():
            log.warning("사진 없음, 건너뜀: %s", p.name)
    if not existing:
        return

    file_strs = [str(p) for p in existing]
    is_group = len(existing) > 1
    names = ", ".join(p.name for p in existing)

    # 단일 사진 — 레이아웃 컨트롤 없음(기존 동작 보존: caret=캡션 필드 -> 캡션 정상 부착)
    if not is_group:
        if _upload_one(page, frame, sel, file_strs[0], wait_ms):
            _type_caption_and_advance(page, caption)
            log.info("사진 업로드 완료 (1장): %s", names)
        else:
            log.error("사진 업로드 실패 (모든 시도 소진): %s", names)
        return

    # 그룹 — 모드/자동 강등 판단
    force_individual = (
        group_upload_mode == "individual"
        or _consecutive_group_failures >= group_fail_threshold
    )
    if force_individual:
        if (_consecutive_group_failures >= group_fail_threshold
                and group_upload_mode != "individual"):
            log.warning("연속 그룹 실패 %d회 -> 남은 그룹은 개별 업로드로 자동 전환",
                        _consecutive_group_failures)
        upload_group_individually(page, frame, sel, file_strs, wait_ms, caption=caption)
        log.info("사진 업로드 완료 (개별 %d장): %s", len(existing), names)
        return

    # 정상 그룹 업로드
    _ensure_clean_editor(page, frame, sel)
    uploaded = False
    for attempt in range(3):
        try:
            with page.expect_file_chooser(timeout=8000) as fc_info:
                _click_toolbar_image_button(page, frame, sel)
                _click_pc_upload_if_method_popup(page)
            fc_info.value.set_files(file_strs)
            uploaded = True
            break
        except Exception as exc:  # noqa: BLE001
            log.warning("그룹 업로드 시도 %d 실패: %s", attempt + 1, exc)
            if attempt < 2:
                page.wait_for_timeout(1200)
                _ensure_clean_editor(page, frame, sel)

    if not uploaded:
        log.error("그룹 업로드 실패 (파일 다이얼로그 안 열림) -> 개별 폴백: %s", names)
        _consecutive_group_failures += 1
        upload_group_individually(page, frame, sel, file_strs, wait_ms, caption=caption)
        log.info("사진 업로드 완료 (개별 폴백 %d장): %s", len(existing), names)
        return

    page.wait_for_timeout(wait_ms)

    # ⭐ 그룹화는 set_files(다중)으로 이미 보장됨 — 사진들은 삽입 순간 한 그룹이 된다.
    # 레이아웃 컨트롤 처리는 '그룹 내 스타일'(슬라이드/콜라주/개별) 선택일 뿐이라,
    # 스타일 선택 실패가 그룹을 깨거나 개별 업로드 폴백을 불러서는 안 된다
    # (페르소나상 그룹화가 최우선). 삽입 성공 = 실패 streak 해제.
    # 개별 폴백은 오직 '그룹 삽입 자체가 실패(파일 다이얼로그 안 열림)'할 때만 발생.
    _consecutive_group_failures = 0

    result = _handle_layout_popup(
        page, preferred=group_layout, n_photos=len(existing),
        budget_ms=layout_popup_budget_ms, save_screenshot=save_screenshots,
    )
    if result == "applied":
        pass  # 그룹 + 선호 스타일까지 적용 완료
    elif result == "default":
        log.info("레이아웃 컨트롤 미발견 — 그룹은 기본 스타일로 삽입됨"
                 "(선호 '%s' 미적용일 수 있음, 임시저장본 검토 권장)", group_layout)
    else:  # "failed"
        log.warning("그룹은 정상 삽입됨 — 다만 선호 스타일 '%s' 클릭 실패로 "
                    "기본 스타일 유지(그룹화는 유지됨)", group_layout)

    _type_caption_and_advance(page, caption)
    log.info("사진 업로드 완료 (그룹 %d장): %s", len(existing), names)
