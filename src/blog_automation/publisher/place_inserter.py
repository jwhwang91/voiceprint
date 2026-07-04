"""SmartEditor '장소(지도)' 카드 삽입.

layout.json 의 place 블록을 네이버 SmartEditor ONE 의 '장소' 기능으로 본문에 꽂는다:
  - 상단 툴바의 '장소' 버튼 클릭
    -> 장소 검색 팝업(모달)
    -> 검색창에 query 입력 -> 검색
    -> 결과 목록에서 첫 결과(또는 name/address 매칭) 선택
    -> '확인/추가' 로 본문에 지도 카드 삽입

⚠️ 장소 버튼·팝업의 실제 DOM 셀렉터는 아직 미확정(config/selectors.yaml 의 write.place_* 가
   null). 그래서 이 모듈은 두 경로로 동작한다:
   1) selectors.yaml 에 값이 있으면 그걸 우선 사용.
   2) 없으면 **라벨/접근성 이름 기반 폴백**으로 best-effort 시도(image_uploader 가
      '내 PC에서 추가'/레이아웃 라벨을 다루는 방식과 동일한 관례).
   그리고 최초 실행에서 항상 [PLACE_DUMP] 로 실제 툴바·팝업 DOM 을 한 번 남겨,
   그 출력으로 selectors.yaml 의 write.place_* 를 확정한다.

설계 불변식(image_uploader 와 동일 정신):
  · 모든 대기는 timeout 으로 bound — 무한 대기 없음.
  · 장소 삽입 실패(버튼/팝업 미발견 등)는 **비치명적** — log.warning 후 skip 하고
    글 전체 발행은 계속 진행한다(장소 1개 때문에 글을 막지 않는다).
"""
from __future__ import annotations

from playwright.sync_api import Frame, Page

from ..logging_setup import get_logger

log = get_logger()

# 툴바 '장소' 버튼의 접근성 이름/툴팁 후보(셀렉터 미확정 시 폴백 매칭용).
_PLACE_BUTTON_LABELS = ("장소", "지도", "place", "map")

# 결과 선택 후 '삽입/확인' 버튼 라벨 후보.
_PLACE_CONFIRM_LABELS = ("확인", "추가", "등록", "입력", "완료")


def _place_popup_open(frame: Frame) -> bool:
    """장소 검색 팝업(레이어)이 실제로 떠 있는지 — 읽기 전용 휴리스틱.

    셀렉터 미확정이라 정확한 컨테이너를 모르므로, '보이는 장소/검색 입력창' 존재를
    신호로 쓴다(있으면 팝업이 열린 상태). 오탐을 줄이려 placeholder 에 장소/검색/주소가
    든 것만 센다.
    """
    try:
        return bool(frame.evaluate(
            r"""() => {
                const kw = /장소|검색|주소|place|map/i;
                for (const el of document.querySelectorAll('input')) {
                    if (el.type === 'file' || el.type === 'hidden') continue;
                    const ph = el.placeholder || '';
                    if (!kw.test(ph)) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) return true;
                }
                return false;
            }"""
        ))
    except Exception:  # noqa: BLE001
        return False


def _dismiss_lingering_map_popup(page: Page, frame: Frame, *, tries: int = 3) -> bool:
    """place 삽입 **성공 뒤** 남을 수 있는 지도 카드 팝업 레이어(`se-popup-placesMap`)를 정리한다.

    관측된 버그: 결과 클릭 → 확인까지 다 성공해도 `.se-popup-placesMap` dim 레이어가 화면에
    남아 이후 모든 `.se-toolbar` 클릭(사진 추가 등)을 가로챈다("subtree intercepts pointer
    events"). `close_place_popup()`(검색 입력창 유무로 판단)은 이 레이어를 감지하지 못해
    이 경로가 따로 필요하다. dim 레이어를 클릭(모달 바깥 클릭으로 닫히는 일반 패턴) →
    안 되면 Escape 반복.
    """
    try:
        if frame.locator('[class*="se-popup-placesMap"]').count() == 0:
            return True
    except Exception:  # noqa: BLE001
        return True
    for _ in range(max(1, tries)):
        try:
            dim = frame.locator('[class*="se-popup-placesMap"] [class*="se-popup-dim"]')
            if dim.count() > 0:
                dim.first.click(timeout=1500, force=True)
            else:
                page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(400)
        try:
            if frame.locator('[class*="se-popup-placesMap"]').count() == 0:
                log.info("장소 삽입 후 남은 지도 팝업 정리 완료.")
                return True
        except Exception:  # noqa: BLE001
            pass
    log.warning("장소 삽입 후 지도 팝업이 끝까지 남아있음 — 이후 업로드가 막힐 수 있음.")
    return False


def close_place_popup(page: Page, frame: Frame, *, tries: int = 3) -> bool:
    """열려 있는 장소 검색 팝업을 Escape 로 닫는다(bound, 비치명적).

    실패한 place 삽입이나 이전 run 이 남긴 지도 검색 레이어를 정리해, 뒤따르는
    이미지 업로드/저장을 막지 않도록 한다. 팝업이 없으면 아무것도 하지 않는다
    (열려있지 않을 때 불필요한 Escape 로 본문 선택을 건드리지 않기 위함).
    반환: 팝업이 (원래 없었거나) 닫히면 True, 끝까지 남아있으면 False.
    """
    if not _place_popup_open(frame):
        return True
    for _ in range(max(1, tries)):
        try:
            page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(400)
        if not _place_popup_open(frame):
            log.info("장소 검색 팝업 정리 완료(Escape).")
            return True
    log.warning("장소 검색 팝업이 Escape 로 닫히지 않음 — 남은 레이어가 업로드를 막을 수 있음.")
    return False


def _place_selectors_ready(sel: dict) -> bool:
    """place 삽입에 필수인 셀렉터가 확정됐는지. search_input + result_item 둘 다 필요."""
    w = sel.get("write", {})
    return bool(w.get("place_search_input")) and bool(w.get("place_result_item"))


def _toolbar_place_button(frame: Frame, sel: dict):
    """장소 툴바 버튼 Locator. selectors.yaml 우선, 없으면 라벨 기반 폴백. 못 찾으면 None."""
    place_sel = sel["write"].get("place_button")
    if place_sel:
        loc = frame.locator(f".se-toolbar {place_sel}")
        try:
            if loc.count() == 0:
                loc = frame.locator(place_sel)
        except Exception:  # noqa: BLE001
            loc = frame.locator(place_sel)
        if loc.count() > 0:
            return loc.first

    # 폴백: 툴바 버튼 중 접근성 이름/툴팁이 장소/지도 인 것.
    for label in _PLACE_BUTTON_LABELS:
        for attr in ("aria-label", "title"):
            cand = frame.locator(f'.se-toolbar button[{attr}*="{label}"]')
            try:
                if cand.count() > 0:
                    return cand.first
            except Exception:  # noqa: BLE001
                pass
    return None


def _dump_place_state(page: Page, frame: Frame, sel: dict, tag: str) -> None:
    """장소 툴바 버튼/검색 팝업 DOM 을 '읽기만' 한다(클릭/키입력 없음).

    로그는 모두 '[PLACE_DUMP]' 접두사 — 첫 실제 실행의 이 출력으로
    selectors.yaml 의 write.place_button / place_search_input / place_result_item /
    place_confirm_button 을 확정한다.
    """
    try:
        log.info("[PLACE_DUMP] ===== begin tag=%s =====", tag)
        # 1) 툴바 버튼 후보(이름에 장소/지도/위치 류가 든 버튼).
        btns = frame.evaluate(
            r"""() => {
                const kw = /장소|지도|위치|place|map/i;
                const out = [];
                document.querySelectorAll('button, [role=button]').forEach((b) => {
                    const name = (b.getAttribute('aria-label')
                                  || b.getAttribute('title')
                                  || (b.textContent || '').trim());
                    if (!name || !kw.test(name)) return;
                    out.push({name: name.slice(0, 40),
                              cls: (b.className || '').toString().slice(0, 100)});
                });
                return out.slice(0, 20);
            }"""
        ) or []
        log.info("[PLACE_DUMP] tag=%s 툴바 버튼 후보=%r", tag, btns)

        # 2) 화면에 떠 있는 팝업/입력창(검색창·결과 후보 식별용).
        popup = frame.evaluate(
            r"""() => {
                const out = {inputs: [], dialogs: []};
                document.querySelectorAll('input').forEach((el) => {
                    if (el.type === 'file') return;
                    out.inputs.push({type: el.type, ph: el.placeholder || '',
                                     cls: (el.className || '').toString().slice(0, 80)});
                });
                document.querySelectorAll('[class*=popup],[class*=modal],[class*=dialog],[class*=layer]').forEach((el) => {
                    const cls = (el.className || '').toString();
                    if (cls) out.dialogs.push(cls.slice(0, 100));
                });
                return {inputs: out.inputs.slice(0, 15), dialogs: out.dialogs.slice(0, 15)};
            }"""
        ) or {}
        log.info("[PLACE_DUMP] tag=%s 팝업/입력=%r", tag, popup)
        log.info("[PLACE_DUMP] ===== end tag=%s =====", tag)
    except Exception as exc:  # noqa: BLE001
        log.warning("[PLACE_DUMP] tag=%s read failed: %s", tag, exc)


def _find_search_input(page: Page, frame: Frame, sel: dict):
    """장소 검색 입력창 Locator. selectors.yaml 우선, 없으면 보이는 텍스트 input 폴백."""
    in_sel = sel["write"].get("place_search_input")
    candidates = [in_sel] if in_sel else [
        'input[placeholder*="장소"]', 'input[placeholder*="검색"]',
        'input[type="text"]', 'input[type="search"]',
    ]
    for cs in candidates:
        if not cs:
            continue
        loc = frame.locator(cs)
        try:
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        except Exception:  # noqa: BLE001
            pass
    return None


def _click_search_button(frame: Frame, sel: dict) -> bool:
    """'장소 검색' 실행 버튼 클릭(있으면). 없으면 False → 호출부가 Enter 로 폴백."""
    btn_sel = sel["write"].get("place_search_button")
    if not btn_sel:
        return False
    loc = frame.locator(btn_sel)
    try:
        if loc.count() > 0 and loc.first.is_visible():
            loc.first.click(timeout=3000)
            log.info("'장소 검색' 버튼 클릭")
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _click_confirm(frame: Frame, sel: dict) -> bool:
    """결과 선택 후 '삽입/확인' 버튼 클릭(있으면). 없으면 결과 클릭만으로 삽입된 것으로 간주."""
    conf_sel = sel["write"].get("place_confirm_button")
    if conf_sel:
        loc = frame.locator(conf_sel)
        try:
            if loc.count() > 0:
                loc.first.click(timeout=3000)
                return True
        except Exception:  # noqa: BLE001
            pass
    for label in _PLACE_CONFIRM_LABELS:
        btn = frame.locator(f'button:has-text("{label}")')
        try:
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=3000)
                log.info("장소 '%s' 버튼 클릭", label)
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def insert_place(page: Page, frame: Frame, sel: dict, blk: dict,
                 *, wait_ms: int = 1500) -> bool:
    """layout.json place 블록을 본문에 삽입. 성공 True, 실패(비치명적) False.

    blk: {"type":"place","query":"바오 서울 성수","name":"바오 서울","address":"..."}
    """
    query = (blk.get("query") or "").strip()
    if not query:
        log.warning("place 블록에 query 가 없어 건너뜀: %r", blk)
        return False

    # 0) 최초 실행 진단 — 셀렉터 확정용. (읽기 전용, 지도 버튼 클릭 없이 툴바만 덤프)
    _dump_place_state(page, frame, sel, tag="before-place-button")

    # ⭐ 셀렉터 게이트: 검색창/결과 항목 셀렉터가 확정되지 않았으면 **지도를 열지 않는다**.
    #    (blind 폴백으로 지도를 열면 검색창에 글자만 치고 결과 선택에 실패해 팝업이 열린 채
    #     남아 뒤따르는 이미지 업로드/저장을 전부 막는다 — 실제로 관측된 "지도 검색창에 갇힘" 버그.)
    #    위 [PLACE_DUMP] 로 write.place_search_input / place_result_item 을 확정해 채운 뒤에만
    #    실제 삽입을 시도한다. 그 전까지 place 는 no-op(글 발행은 계속 진행).
    if not _place_selectors_ready(sel):
        log.warning("place 셀렉터 미확정(place_search_input/place_result_item=null) — 지도를 열지 "
                    "않고 건너뜁니다. 위 [PLACE_DUMP] 로 확정해 config/selectors.yaml 을 채우세요. "
                    "query=%r", query)
        return False

    # 1) 장소 툴바 버튼.
    btn = _toolbar_place_button(frame, sel)
    if btn is None:
        log.warning("장소 툴바 버튼을 찾지 못함 — place 삽입 건너뜀(위 [PLACE_DUMP]로 "
                    "selectors.yaml write.place_button 확정 필요). query=%r", query)
        return False
    try:
        btn.scroll_into_view_if_needed()
        btn.click(timeout=5000)
    except Exception as exc:  # noqa: BLE001
        log.warning("장소 버튼 클릭 실패 — 건너뜀: %s", exc)
        close_place_popup(page, frame)
        return False
    page.wait_for_timeout(wait_ms)
    _dump_place_state(page, frame, sel, tag="after-place-button")  # 팝업 DOM 확정용

    # 2) 검색창에 query 입력 → 검색.
    search = _find_search_input(page, frame, sel)
    if search is None:
        log.warning("장소 검색 입력창을 찾지 못함 — 건너뜀(위 [PLACE_DUMP] 참고). query=%r", query)
        close_place_popup(page, frame)
        return False
    try:
        search.click(timeout=3000)
        search.fill(query)
        # react-autosuggest 입력창은 Enter 로 검색이 안 될 수 있어, '장소 검색' 버튼이
        # 확정돼 있으면 그걸 누른다(없으면 Enter 폴백).
        if not _click_search_button(frame, sel):
            page.keyboard.press("Enter")
    except Exception as exc:  # noqa: BLE001
        log.warning("장소 검색 입력 실패 — 건너뜀: %s", exc)
        close_place_popup(page, frame)
        return False
    page.wait_for_timeout(wait_ms)

    # 3) 결과 선택. selectors.yaml 의 place_result_item 우선, 없으면 첫 결과 휴리스틱.
    res_sel = sel["write"].get("place_result_item")
    result = None
    if res_sel:
        loc = frame.locator(res_sel)
        try:
            if loc.count() > 0:
                result = loc.first
        except Exception:  # noqa: BLE001
            result = None
    if result is None:
        # 폴백: 검색 결과로 보이는 클릭 가능한 li/항목 첫 번째.
        for cs in ('[class*="search"] li', '[class*="result"] li',
                   '[class*="place"] li', 'ul li'):
            loc = frame.locator(cs)
            try:
                if loc.count() > 0 and loc.first.is_visible():
                    result = loc.first
                    break
            except Exception:  # noqa: BLE001
                pass
    if result is None:
        log.warning("장소 검색 결과를 찾지 못함 — 건너뜀(위 [PLACE_DUMP] 참고). query=%r", query)
        close_place_popup(page, frame)
        return False
    try:
        result.click(timeout=3000)
    except Exception as exc:  # noqa: BLE001
        log.warning("장소 결과 클릭 실패 — 건너뜀: %s", exc)
        close_place_popup(page, frame)
        return False
    page.wait_for_timeout(500)

    # 4) 확인/추가(있으면) → 본문에 삽입. 그 뒤 다음 블록을 위해 줄바꿈.
    _click_confirm(frame, sel)
    page.wait_for_timeout(wait_ms)
    _dismiss_lingering_map_popup(page, frame)
    try:
        page.keyboard.press("Enter")
    except Exception:  # noqa: BLE001
        pass
    log.info("장소 카드 삽입 완료: %s", blk.get("name") or query)
    return True
