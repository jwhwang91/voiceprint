"""주제(TopicExtraction)에서 SEO 후보 키워드를 생성한다.

constants 의 카테고리별 템플릿 + 공통 롱테일 모디파이어를 조합해
primary(가장 구체·핵심) / secondary(롱테일) / tag(압축형) / avoid(빅키워드) 후보를 만든다.
네트워크 없는 순수 함수 — 같은 입력이면 항상 같은 출력(결정적).
"""
from __future__ import annotations

import re

from ..logging_setup import get_logger
from . import constants
from .models import KeywordCandidates, TopicExtraction

log = get_logger()

# 템플릿 플레이스홀더 추출용(예: "{지역} {음식} 맛집" → ["지역","음식"]).
_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")

# 후보 키워드 토큰 사이 공백 정리용.
_WS_RE = re.compile(r"\s+")

# primary(핵심) 로 끌어올릴 모디파이어 — 검색 의도가 분명한 핵심 후기형.
_PRIMARY_MODIFIERS = ("후기", "내돈내산", "장단점")

# tag 후보로 쓰기엔 너무 일반적이라 제외할 단독 토큰.
_GENERIC_TAG_TOKENS = {"맛집", "여행", "육아", "후기", "추천", "리뷰", "일상", "카페"}


def _norm(text: str) -> str:
    """앞뒤 공백 제거 + 내부 다중 공백 1칸으로."""
    return _WS_RE.sub(" ", (text or "").strip())


def _dedup(items: list[str]) -> list[str]:
    """순서 보존 중복 제거(정규화 기준)."""
    seen: dict[str, None] = {}
    out: list[str] = []
    for it in items:
        k = _norm(it)
        if k and k not in seen:
            seen[k] = None
            out.append(k)
    return out


def _placeholder_values(topic: TopicExtraction) -> dict[str, str]:
    """topic 필드 + extra + detected_topics 에서 플레이스홀더 값 맵을 만든다.

    값이 비어 있으면 키를 넣지 않는다(→ 호출부에서 해당 템플릿을 통째로 스킵).
    """
    extra = topic.extra or {}
    vals: dict[str, str] = {}

    def put(key: str, *candidates: object) -> None:
        for c in candidates:
            s = _norm(str(c)) if c is not None else ""
            if s:
                vals[key] = s
                return

    put("지역", topic.location, extra.get("지역"), extra.get("location"))
    put("제품명", topic.product_type, extra.get("제품명"), extra.get("product_type"))
    put("브랜드명", topic.brand, extra.get("브랜드명"), extra.get("brand"))
    put("아이연령", topic.age_group, extra.get("아이연령"), extra.get("age_group"))
    put("나이대", extra.get("나이대"), extra.get("age_group"), topic.age_group)
    put("음식", extra.get("음식"), extra.get("food"))
    put("메뉴", extra.get("메뉴"), extra.get("menu"), extra.get("음식"))
    put("업종", extra.get("업종"), extra.get("category_type"))
    put("역명", extra.get("역명"), extra.get("station"))
    put("상황", extra.get("상황"), extra.get("situation"), topic.content_type)
    return vals


def _fill_template(template: str, vals: dict[str, str]) -> str | None:
    """템플릿의 모든 플레이스홀더가 채워지면 결과 문자열, 하나라도 없으면 None."""
    needed = _PLACEHOLDER_RE.findall(template)
    for ph in needed:
        if ph not in vals:
            return None
    filled = template
    for ph in needed:
        filled = filled.replace("{" + ph + "}", vals[ph])
    return _norm(filled)


def _core_terms(topic: TopicExtraction, vals: dict[str, str]) -> list[str]:
    """주제 핵심 단어(롱테일 결합의 베이스). 지역/제품/브랜드/연령 + detected_topics."""
    terms: list[str] = []
    for key in ("지역", "제품명", "브랜드명", "아이연령", "메뉴", "음식"):
        if vals.get(key):
            terms.append(vals[key])
    for t in (topic.detected_topics or []):
        s = _norm(str(t))
        if s:
            terms.append(s)
    return _dedup(terms)


def _compact(keyword: str) -> str:
    """태그용 압축형(공백 제거)."""
    return keyword.replace(" ", "")


def generate_candidates(topic: TopicExtraction, growth_cfg) -> KeywordCandidates:
    """topic 에서 후보 키워드를 생성한다(결정적, 네트워크 없음).

    - 카테고리 템플릿을 채우되 필요한 플레이스홀더가 없으면 템플릿 스킵.
    - primary: 지역+업종/메뉴, 제품+후기/내돈내산/장단점 등 가장 구체·핵심.
    - secondary: 핵심어 + COMMON_LONGTAIL_MODIFIERS 롱테일 결합.
    - tag: primary/secondary 의 압축형(공백 제거).
    - avoid: (BIG_HEAD_KEYWORDS ∪ DEFAULT_AVOID_TAGS[category]) 중 이 주제에 관련된 것.
    - 중복 제거(순서 보존), max_keyword_candidates 로 cap.
    """
    try:
        category = topic.category if topic.category in constants.CATEGORY_KEYWORD_TEMPLATES else None
        vals = _placeholder_values(topic)
        cores = _core_terms(topic, vals)

        # ── 1) 템플릿 채우기 ──
        filled: list[str] = []
        for tpl in constants.CATEGORY_KEYWORD_TEMPLATES.get(category, []):
            kw = _fill_template(tpl, vals)
            if kw:
                filled.append(kw)
        filled = _dedup(filled)

        # primary 후보: 핵심 후기형 모디파이어가 붙은 것 + 단어 수가 적은(=구체적이고 짧은) 템플릿.
        primary: list[str] = []
        secondary: list[str] = []
        for kw in filled:
            if any(m in kw for m in _PRIMARY_MODIFIERS) or len(kw.split()) <= 2:
                primary.append(kw)
            else:
                secondary.append(kw)

        # ── 2) 롱테일 결합(핵심어 + 카테고리 적합 모디파이어) → secondary ──
        #   카테고리별 적합 모디파이어만 결합(제품형에 '비오는날' 같은 장소어를 붙이지 않음).
        modifiers = constants.CATEGORY_LONGTAIL_MODIFIERS.get(
            category, constants.COMMON_LONGTAIL_MODIFIERS
        )
        for core in cores:
            for mod in modifiers:
                combo = _norm(f"{core} {mod}")
                if combo and combo != core:
                    secondary.append(combo)

        primary = _dedup(primary)
        secondary = [s for s in _dedup(secondary) if s not in set(primary)]

        # ── 3) 캡(max_keyword_candidates 를 primary/secondary 합산에 적용) ──
        max_total = int((growth_cfg.seo or {}).get("max_keyword_candidates", 80) or 80)
        primary = primary[:max_total]
        remaining = max(0, max_total - len(primary))
        secondary = secondary[:remaining]

        # ── 4) tag 후보(압축형) ──
        tag_source = primary + secondary
        tags: list[str] = []
        for kw in tag_source:
            # 단독 일반 토큰(맛집/후기 등)은 태그로 빈약 → 결합형만 압축.
            if kw in _GENERIC_TAG_TOKENS:
                continue
            tags.append(_compact(kw))
        # 핵심어 단독도 압축형 태그로 추가(예: 지역명, 제품명).
        for core in cores:
            if core not in _GENERIC_TAG_TOKENS:
                tags.append(_compact(core))
        tags = _dedup(tags)

        # ── 5) avoid 후보(빅키워드 ∪ 카테고리 회피 태그) 중 관련된 것 ──
        avoid_pool: list[str] = []
        avoid_pool.extend(constants.BIG_HEAD_KEYWORDS)
        if category:
            avoid_pool.extend(constants.DEFAULT_AVOID_TAGS.get(category, []))
        haystack = " ".join(filled + cores + [vals.get(k, "") for k in vals])
        avoid: list[str] = []
        for term in avoid_pool:
            t = _norm(term)
            if not t:
                continue
            # 관련성: 후보군에 정확히 있거나, 핵심어/지역/카테고리와 토큰이 겹치면 회피 대상.
            related = (
                t in haystack
                or any(tok and tok in t for tok in cores)
                or any(tok and tok in haystack for tok in t.split())
            )
            if related:
                avoid.append(t)
        avoid = _dedup(avoid)

        log.info(
            "[SEO][candidates] cat=%s primary=%d secondary=%d tags=%d avoid=%d",
            topic.category, len(primary), len(secondary), len(tags), len(avoid),
        )
        return KeywordCandidates(
            primary_candidates=primary,
            secondary_candidates=secondary,
            tag_candidates=tags,
            avoid_candidates=avoid,
        )
    except Exception as exc:  # noqa: BLE001
        # 후보 생성은 부가 단계 — 실패해도 빈 묶음으로 폴백(파이프라인 진행).
        log.warning("[SEO][candidates] 후보 생성 실패 → 빈 결과 폴백: %s", exc)
        return KeywordCandidates()
