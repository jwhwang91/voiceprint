"""셀렉터 패치(self-healing) — 검증 + 사용자 오버라이드 적용.

자가치유 흐름에서 Claude Code 가 `inspect-dom --json` 출력을 보고 만든 **패치 JSON** 을 받아
검증하고, 통과하면 `<workspace>/config/selectors.user.yaml` 에만 반영한다. 절대 번들
`config/selectors.yaml`(기본값)이나 소스 코드를 건드리지 않는다. 적용 이력은
`<logs>/healing-history.jsonl` 에 한 줄씩 남는다.

패치 스키마:
    {
      "type": "selector_patch",
      "target": "write.publish_button",
      "old_selector": "button:has-text('발행')",     # 선택
      "new_selector": "[class*='publish_btn']",
      "evidence": {"matched_count": 1, "visible": true, "text": "발행"},  # 선택
      "confidence": 0.91,                              # 선택 [0,1]
      "reason": "default selector missed; live DOM found robust partial class match"
    }
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from .. import paths
from ..logging_setup import get_logger
from ..selectors import load_default_selectors, save_selector_override

log = get_logger()

PATCH_TYPE = "selector_patch"

# 너무 광범위/위험해서 거부할 셀렉터(오클릭·전역 매칭 위험). 정확 일치만 검사.
_DANGEROUS_EXACT = {
    "", "*", "body", "html", "head", ":root",
    "div", "span", "a", "button", "input", "li", "ul", "ol", "p", "img",
    "label", "section", "header", "footer", "main", "nav", "form", "table", "tr", "td",
}


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _is_dangerous(sel: str) -> bool:
    s = (sel or "").strip()
    if len(s) < 2:
        return True
    if s.lower() in _DANGEROUS_EXACT:
        return True
    return False


def _known_sections() -> set[str]:
    try:
        return set(load_default_selectors().keys())
    except Exception:  # noqa: BLE001
        return set()


def validate_patch(patch: Any) -> dict:
    """패치를 스키마/안전성 기준으로 검증. {ok, errors, warnings} 반환(라이브 DOM 미확인)."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(patch, dict):
        return {"ok": False, "errors": ["패치가 JSON object 가 아닙니다"], "warnings": []}

    if patch.get("type") != PATCH_TYPE:
        errors.append(f"type 은 '{PATCH_TYPE}' 여야 합니다 (받음: {patch.get('type')!r})")

    target = patch.get("target")
    if not isinstance(target, str) or "." not in target or any(
            not seg.strip() for seg in target.split(".")):
        errors.append("target 은 'section.key' 점 표기여야 합니다 (예: write.publish_button)")
    else:
        top = target.split(".")[0]
        known = _known_sections()
        if known and top not in known:
            warnings.append(f"target 의 섹션 '{top}' 이 기본 셀렉터에 없습니다(오타 가능): "
                            f"알려진 섹션 {sorted(known)}")

    new_sel = patch.get("new_selector")
    if not isinstance(new_sel, str) or not new_sel.strip():
        errors.append("new_selector 는 비어 있지 않은 문자열이어야 합니다")
    elif _is_dangerous(new_sel):
        errors.append(f"new_selector 가 너무 광범위/위험합니다(거부): {new_sel!r}")

    conf = patch.get("confidence")
    if conf is not None:
        try:
            c = float(conf)
            if not (0.0 <= c <= 1.0):
                errors.append("confidence 는 0~1 범위여야 합니다")
        except (TypeError, ValueError):
            errors.append("confidence 는 숫자여야 합니다")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def verify_against_live_dom(patch: dict, page) -> dict:
    """라이브 DOM 에서 new_selector 매칭을 확인. {matched, visible, ok, note} 반환."""
    css = patch.get("new_selector")
    try:
        loc = page.locator(css)
        matched = loc.count()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "matched": None, "visible": None,
                "note": f"유효하지 않은 셀렉터({type(e).__name__})"}
    visible = None
    if matched:
        try:
            visible = loc.evaluate_all("(els) => els.filter(e => e.getClientRects().length>0).length")
        except Exception:  # noqa: BLE001
            visible = None
    note = ""
    ok = matched is not None and matched >= 1
    if not ok:
        note = "라이브 DOM 에서 new_selector 매칭 0 — 적용하지 않음"
    elif matched and matched > 30:
        note = f"매칭이 매우 많음({matched}) — 너무 광범위할 수 있음(경고)"
    return {"ok": ok, "matched": matched, "visible": visible, "note": note}


def _append_history(record: dict) -> None:
    try:
        hp = paths.get_healing_history_path()
        hp.parent.mkdir(parents=True, exist_ok=True)
        with open(hp, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001 — 이력 기록 실패가 패치 적용을 막지 않게
        log.warning("healing-history 기록 실패: %s", type(e).__name__)


def apply_patch(patch: dict, *, page=None) -> dict:
    """검증 통과 시 사용자 오버라이드에 적용 + 이력 기록.

    page 가 주어지면 적용 전 라이브 DOM 으로 new_selector 매칭을 확인한다(0 이면 거부).
    반환: {applied, target, new_selector, path?, errors, warnings, verify?}
    """
    v = validate_patch(patch)
    if not v["ok"]:
        return {"applied": False, "errors": v["errors"], "warnings": v["warnings"]}

    verify = None
    if page is not None:
        verify = verify_against_live_dom(patch, page)
        if not verify["ok"]:
            return {"applied": False, "errors": [verify["note"] or "라이브 DOM 확인 실패"],
                    "warnings": v["warnings"], "verify": verify}

    target = patch["target"]
    new_sel = patch["new_selector"].strip()
    metadata = {
        "reason": patch.get("reason"),
        "confidence": patch.get("confidence"),
        "source": patch.get("source", "inspect-dom"),
        "old_selector": patch.get("old_selector"),
        "evidence": patch.get("evidence"),
    }
    if verify is not None:
        metadata["verified"] = {"matched": verify["matched"], "visible": verify["visible"]}
    # None 값은 군더더기라 제거.
    metadata = {k: val for k, val in metadata.items() if val is not None}

    path = save_selector_override(target, new_sel, metadata)

    record = {
        "timestamp": _now(), "target": target,
        "old_selector": patch.get("old_selector"), "new_selector": new_sel,
        "confidence": patch.get("confidence"), "reason": patch.get("reason"),
        "verified": verify, "applied": True, "override_path": str(path),
    }
    _append_history(record)
    return {"applied": True, "target": target, "new_selector": new_sel,
            "path": str(path), "errors": [], "warnings": v["warnings"], "verify": verify}


# ───────────────────────── CLI 진입점 ─────────────────────────

def _load_patch(patch_path: str) -> dict:
    return json.loads(Path(patch_path).read_text(encoding="utf-8"))


def _maybe_verify_page(cfg, blog_id, verify_flag):
    """verify 가 필요한지 판단. (True/False/None=auto). auto 는 앱 모드(CDP)일 때만 켠다."""
    import os
    if verify_flag is False:
        return False
    if verify_flag is None:  # auto: 앱 안(CDP)에서만 자동 확인(브라우저 새로 안 띄움)
        return bool(os.getenv("VOICEPRINT_CDP_ENDPOINT", "").strip())
    return True


def run_validate_patch(cfg, *, patch: str, verify: bool | None = False, blog_id=None) -> int:
    p = _load_patch(patch)
    result = validate_patch(p)
    if _maybe_verify_page(cfg, blog_id, verify):
        bid = _blog_id(cfg, blog_id)
        from ..utils.browser import browser_context
        with browser_context(cfg, profile=bid) as (_ctx, page):
            result["verify"] = verify_against_live_dom(p, page)
            if not result["verify"]["ok"]:
                result["ok"] = False
                result["errors"] = result.get("errors", []) + [result["verify"]["note"]]
    print(json.dumps({"mode": "validate_patch", **result}, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def run_apply_patch(cfg, *, patch: str, verify: bool | None = None, blog_id=None) -> int:
    p = _load_patch(patch)
    if _maybe_verify_page(cfg, blog_id, verify):
        bid = _blog_id(cfg, blog_id)
        from ..utils.browser import browser_context
        with browser_context(cfg, profile=bid) as (_ctx, page):
            result = apply_patch(p, page=page)
    else:
        result = apply_patch(p, page=None)
    print(json.dumps({"mode": "apply_patch", **result}, ensure_ascii=False, indent=2))
    return 0 if result.get("applied") else 1


def _blog_id(cfg, override):
    # inspect_dom 과 동일한 규칙 재사용.
    from .inspect_dom import _blog_id as _bid
    return _bid(cfg, override)
