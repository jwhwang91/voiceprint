"""셀렉터 로딩 — 번들 기본값 + 사용자 런타임 오버라이드(자가치유) 병합.

배포/공유를 위해 **핵심 기본 셀렉터는 안정적으로 유지**하고(`config/selectors.yaml`), 네이버가
DOM 을 바꿔 생긴 사용자별 수정은 **워크스페이스**(`<workspace>/config/selectors.user.yaml`)에만
쓴다. 그래야 앱을 업데이트해도 사용자의 패치가 유지되고, 반대로 기본값은 오염되지 않는다.

병합 규칙:
  · 기본값(`selectors.yaml`)을 로드한다.
  · 사용자 오버라이드(`selectors.user.yaml`)가 있으면 **깊은 병합**으로 기본값 위에 덮는다.
  · 오버라이드가 없거나/깨졌거나/읽기 불가면 **경고 후 기본값만** 쓴다(발행을 절대 막지 않음).

값 포맷 — 둘 다 지원:
  · 구(舊): `publish_button: "button:has-text('발행')"`              (그냥 문자열)
  · 신(新): `publish_button: {selector: "...", updated_at, reason, confidence, source}`  (dict)

⭐ 핵심 호환성: 기존 소비 코드 100% 가 셀렉터 값을 **문자열**로 기대한다(page.locator(val) 등).
   그래서 `load_selectors()` 는 효과(병합) 트리를 **문자열로 평탄화**해서 돌려준다 — 신포맷 dict
   값은 그 `selector` 문자열로 접힌다. 덕분에 모든 소비부가 **수정 없이** 그대로 동작한다.
   메타데이터까지 필요하면 `load_selectors_raw()` 를 쓴다(패치/진단 도구용).
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import yaml

from . import paths
from .logging_setup import get_logger

log = get_logger()


# ───────────────────────── 병합/정규화 ─────────────────────────

def _deep_merge(base: dict, over: dict) -> dict:
    """over 를 base 위에 깊은 병합(둘 다 dict 인 키만 재귀, 그 외는 over 가 교체)."""
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _flatten_value(v: Any) -> Any:
    """신포맷 dict({selector: "..."}) 를 그 문자열로 접는다. 그 외 값은 그대로."""
    if isinstance(v, dict) and isinstance(v.get("selector"), str):
        return v["selector"]
    if isinstance(v, dict):
        return {k: _flatten_value(x) for k, x in v.items()}
    return v


def _flatten_tree(d: dict) -> dict:
    """효과 트리 전체를 재귀로 평탄화(모든 신포맷 노드 → 문자열)."""
    return {k: _flatten_value(v) for k, v in d.items()}


# ───────────────────────── 로딩 ─────────────────────────

def _read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_default_selectors() -> dict[str, Any]:
    """번들 기본 셀렉터만(오버라이드 미적용)."""
    return _read_yaml(paths.get_default_selectors_path())


def _load_user_override() -> dict[str, Any]:
    """사용자 오버라이드(없거나 깨졌으면 빈 dict + 경고)."""
    p = paths.get_user_selectors_path()
    if not p.exists():
        return {}
    try:
        data = _read_yaml(p)
        if not isinstance(data, dict):
            log.warning("셀렉터 오버라이드가 dict 가 아님 — 무시: %s", p)
            return {}
        return data
    except Exception as e:  # noqa: BLE001 — 깨진 오버라이드가 발행을 막지 않게
        log.warning("셀렉터 오버라이드 읽기 실패(기본값만 사용): %s (%s)", p, type(e).__name__)
        return {}


def load_selectors_raw() -> dict[str, Any]:
    """기본값 + 사용자 오버라이드를 병합하되 **평탄화하지 않은** 트리(신포맷 dict 보존).

    패치/진단 도구가 메타데이터(updated_at/reason/confidence)를 봐야 할 때 쓴다.
    일반 소비부는 load_selectors()(문자열 평탄화)를 쓸 것.
    """
    base = load_default_selectors()
    user = _load_user_override()
    return _deep_merge(base, user) if user else base


def load_selectors() -> dict[str, Any]:
    """효과 셀렉터(기본값 + 오버라이드 병합) — 모든 값이 **문자열로 평탄화**된 트리.

    기존 소비 코드(page.locator(val) 등)와 100% 호환된다.
    """
    return _flatten_tree(load_selectors_raw())


# ───────────────────────── 점(dotted) 접근 헬퍼 ─────────────────────────

def get_selector(selectors: dict[str, Any], dotted_key: str, default: Any = None) -> Any:
    """`get_selector(sel, "write.publish_button")` → 문자열 셀렉터(없으면 default).

    selectors 가 평탄화돼 있으면(load_selectors) 문자열을, 원본이면(load_selectors_raw) 신포맷
    dict 를 만나도 그 `selector` 를 꺼내 항상 문자열을 돌려준다.
    """
    node: Any = selectors
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    if isinstance(node, dict):
        sel = node.get("selector")
        return sel if isinstance(sel, str) else default
    return node


# ───────────────────────── 사용자 오버라이드 쓰기(자가치유) ─────────────────────────

def save_selector_override(path_key: str, selector: str, metadata: dict | None = None) -> Path:
    """사용자 셀렉터 오버라이드를 `<workspace>/config/selectors.user.yaml` 에 기록.

    절대 번들 기본값(config/selectors.yaml)을 건드리지 않는다.

    path_key: "write.publish_button" 같은 점 표기.
    selector: 새 CSS/Playwright 셀렉터 문자열.
    metadata: updated_at/reason/confidence/source/old_selector/evidence 등(선택).
    """
    if not isinstance(path_key, str) or "." not in path_key:
        raise ValueError(f"path_key 는 'section.key' 점 표기여야 합니다: {path_key!r}")
    if not isinstance(selector, str) or not selector.strip():
        raise ValueError("selector 는 비어 있지 않은 문자열이어야 합니다")

    p = paths.get_user_selectors_path()
    p.parent.mkdir(parents=True, exist_ok=True)

    # 기존 오버라이드를 읽어 병합(다른 키 보존).
    current: dict[str, Any] = {}
    if p.exists():
        try:
            current = _read_yaml(p)
            if not isinstance(current, dict):
                current = {}
        except Exception:  # noqa: BLE001
            current = {}

    entry: dict[str, Any] = {"selector": selector.strip()}
    meta = dict(metadata or {})
    meta.setdefault("updated_at", datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
    meta.setdefault("source", "inspect-dom")
    entry.update(meta)

    # 점 표기를 따라 내려가며 dict 를 만든다.
    parts = path_key.split(".")
    node = current
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = entry

    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump(current, f, allow_unicode=True, sort_keys=False)
    log.info("셀렉터 오버라이드 저장: %s = %s → %s", path_key, selector, p)
    return p
