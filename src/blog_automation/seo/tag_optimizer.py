"""태그 최적화 — primary/secondary 키워드와 주제 메타로 네이버 블로그 태그를 만든다.

태그는 공백을 제거한 컴팩트 형태(예: '성수동 데이트 맛집' → '성수동데이트맛집')로 만들고,
빅키워드(BIG_HEAD_KEYWORDS) 와 카테고리별 회피 태그(DEFAULT_AVOID_TAGS) 는 selected 에서 빼고
avoid_tags 로 분리한다. 입출력은 순서를 보존하고 중복을 제거해 결정적(deterministic)이다.
"""
from __future__ import annotations

from typing import Any

from ..logging_setup import get_logger
from . import constants
from .models import TopicExtraction

log = get_logger()


def _compact(text: str | None) -> str:
    """태그 컴팩트화 — 내부 공백 제거 + 양끝 정리. None/빈값은 ''."""
    if not text:
        return ""
    # 모든 공백류(스페이스/탭/개행)를 제거해 한 덩어리 태그로 만든다.
    return "".join((text or "").split())


def _dedup_keep_order(items: list[str]) -> list[str]:
    """순서를 보존하며 중복 제거(빈 문자열은 버린다)."""
    seen: dict[str, None] = {}
    out: list[str] = []
    for it in items:
        s = (it or "").strip()
        if s and s not in seen:
            seen[s] = None
            out.append(s)
    return out


def optimize_tags(
    primary: str,
    secondaries: list[str],
    topic: TopicExtraction,
    growth_cfg: Any,
    existing_candidates: list[str] | None = None,
) -> dict[str, list[str]]:
    """primary/secondary + 주제 메타로 selected/avoid 태그를 구성한다.

    - selected_tags: 컴팩트 태그 5~max_tags 개. 빅키워드/회피태그는 제외.
    - avoid_tags: DEFAULT_AVOID_TAGS[category] + BIG_HEAD_KEYWORDS(컴팩트) 중 등장한 것.
    실패해도 빈 결과를 돌려주며 호출자가 폴백할 수 있게 한다.
    """
    try:
        category = (getattr(topic, "category", None) or "기타")
        max_tags = int((growth_cfg.seo or {}).get("max_tags", 10))
        if max_tags < 1:
            max_tags = 1

        # ── 1) 회피 집합 구성(원형 + 컴팩트형 모두 매칭에 쓴다) ──
        avoid_raw = list(constants.DEFAULT_AVOID_TAGS.get(category, []))
        avoid_raw += list(constants.BIG_HEAD_KEYWORDS)
        # 컴팩트형 집합(selected 에서 제외할 때 비교용)
        avoid_compact: set[str] = set()
        for a in avoid_raw:
            ac = _compact(a)
            if ac:
                avoid_compact.add(ac)

        # ── 2) 후보 소스 모으기(우선순위 순서대로) ──
        source: list[str] = []
        if primary:
            source.append(primary)
        source.extend(secondaries or [])
        # 주제 메타(지역/제품/브랜드/연령/카테고리)도 단독 태그로 추가
        for meta in (
            getattr(topic, "location", None),
            getattr(topic, "product_type", None),
            getattr(topic, "brand", None),
            getattr(topic, "age_group", None),
            category,
        ):
            if meta:
                source.append(str(meta))
        # 호출자가 넘긴 기존 후보(예: candidate generator 의 tag_candidates)도 뒤에 붙인다.
        if existing_candidates:
            source.extend(existing_candidates)

        # ── 3) 컴팩트화 + 중복 제거 ──
        compacted = [_compact(s) for s in source]
        compacted = _dedup_keep_order(compacted)

        # ── 4) 회피 태그 분리 ──
        selected: list[str] = []
        avoid_tags: list[str] = []
        for tag in compacted:
            if tag in avoid_compact:
                avoid_tags.append(tag)
            else:
                selected.append(tag)

        # 회피 집합 자체도 결과의 avoid_tags 에 노출(등장 여부와 무관하게 사용자 안내용).
        avoid_tags.extend(sorted(avoid_compact))
        avoid_tags = _dedup_keep_order(avoid_tags)

        # ── 5) 개수 제한(상한 max_tags / 하한 5는 후보 부족 시 가능한 만큼) ──
        selected = selected[:max_tags]

        # 5개 미만이면 회피되지 않은 주제 단어로 최소한만 보충(이미 selected/avoid 에 없는 것).
        if len(selected) < 5:
            already = set(selected) | set(avoid_tags)
            filler_pool: list[str] = []
            for sec in (secondaries or []):
                filler_pool.append(_compact(sec))
            for t in (getattr(topic, "detected_topics", None) or []):
                filler_pool.append(_compact(t))
            for cand in _dedup_keep_order(filler_pool):
                if len(selected) >= min(5, max_tags):
                    break
                if cand and cand not in already and cand not in avoid_compact:
                    selected.append(cand)
                    already.add(cand)

        selected = _dedup_keep_order(selected)[:max_tags]

        log.info(
            "tag_optimizer: category=%s selected=%d avoid=%d (max_tags=%d)",
            category, len(selected), len(avoid_tags), max_tags,
        )
        return {"selected_tags": selected, "avoid_tags": avoid_tags}
    except Exception as exc:  # noqa: BLE001
        log.warning("tag_optimizer 실패, 빈 결과 반환: %s", exc)
        return {"selected_tags": [], "avoid_tags": []}
