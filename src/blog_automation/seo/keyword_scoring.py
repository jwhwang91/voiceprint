from __future__ import annotations

"""키워드 후보 점수화 + 핵심/보조 키워드 선정.

candidate generator 가 만든 후보를, collector 가 모은 research(KeywordResearch) 와
topic/historical 신호로 채점한다. 결정론적(네트워크 없음)이며, research 가 없으면
중립 프록시(수요 40 / 기회 50 / 경쟁 50)로 대체한다. 가중치는 growth_cfg.scoring.
"""

import re
from datetime import datetime

from . import constants
from ..logging_setup import get_logger
from .historical_performance import my_blog_fit_score
from .models import KeywordCandidates, KeywordResearch, ScoredKeyword, TopicExtraction

log = get_logger()

# research[kw] 가 없을 때 쓰는 중립 프록시
_NEUTRAL_DEMAND = 40.0
_NEUTRAL_OPPORTUNITY = 50.0
_NEUTRAL_COMPETITION = 50.0

# 토픽 플래그 ↔ 키워드 모디파이어(content_fit / mismatch 판정용)
#   ⚠️ 부분일치 오탐 주의: 바로 '아기'/'아이' 를 넣으면 '돌아기'(←'아기' 포함) 등이 오탐된다.
#      'X랑/X와' 같이 '아이를 데려가는' 검색 의도가 분명한 형태만 둔다.
_KID_MODIFIERS = ("아이랑", "아기랑", "아이와", "아기와", "유모차", "키즈")
_DATE_MODIFIERS = ("데이트", "분위기", "기념일", "커플")
_PARKING_MODIFIERS = ("주차",)
_PRODUCT_MODIFIERS = ("내돈내산", "실사용", "비교", "후기", "장단점", "사용후기", "단점", "리뷰")

# mismatch(주장 ↔ 근거 불일치) 판정: 모디파이어 → 필요한 토픽 플래그명
_MISMATCH_RULES: list[tuple[tuple[str, ...], str]] = [
    (("주차",), "has_parking_evidence"),
    (("데이트",), "has_date_mood"),
    (("아이랑", "아기랑", "아이와", "아기와"), "has_kid_context"),
    (("내돈내산", "실사용", "비교"), "is_product_review"),
]


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """0..100 범위로 클램프."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _has_any(keyword: str, modifiers: tuple[str, ...]) -> bool:
    return any(m in keyword for m in modifiers)


def _content_fit_score(keyword: str, topic: TopicExtraction) -> float:
    """토픽 '근거가 있는' 플래그를 키워드가 주장하면 가산, 근거 없으면 감산.

    ⭐ 핵심: 단순히 지역명을 포함했다고 일률적으로 높게 주지 않는다(그러면 '성수 비오는날'
       과 '성수 데이트 맛집' 이 같은 점수가 됨). 근거 있는 모디파이어(데이트·주차·아이랑·내돈내산)
       를 가진 키워드가 더 높게 나오도록 플래그별로 가산한다.
    """
    base = 50.0
    flag_checks = (
        (_KID_MODIFIERS, topic.has_kid_context),
        (_DATE_MODIFIERS, topic.has_date_mood),
        (_PARKING_MODIFIERS, topic.has_parking_evidence),
        (_PRODUCT_MODIFIERS, topic.is_product_review),
    )
    for modifiers, evidenced in flag_checks:
        if _has_any(keyword, modifiers):
            base += 18.0 if evidenced else -25.0   # 근거 있으면↑, 주장 불일치면↓

    # 토픽 핵심어(지역/제품명/브랜드/연령)가 들어가면 약가산(최대 2개까지 누적).
    core_hits = 0
    for core in (topic.location, topic.product_type, topic.brand, topic.age_group):
        if core and core in keyword and core_hits < 2:
            base += 8.0
            core_hits += 1
    return _clamp(base)


def _seasonality_score(keyword: str, month: int) -> float:
    """현재 월 시즌 단어와 맞으면 가산, 정반대 비수기면 감산. 무관하면 중립 50."""
    score = 50.0
    season_words = constants.SEASONALITY_BY_MONTH.get(month, [])
    if any(word in keyword for word in season_words):
        score += 25.0   # 시즌성은 '동점 깨기' 수준의 보조 신호(콘텐츠 적합도를 압도하지 않게)
    # 비수기 단어가 들어가 있으면 약한 감점
    for word, off_months in constants.SEASON_OPPOSITES.items():
        if word in keyword and month in off_months:
            score -= 30.0
            break
    return _clamp(score)


def _competition_penalty(keyword: str, research: KeywordResearch | None) -> float:
    """빅키워드/너무 짧음/문서수 과다 → 0보다 큰 감점."""
    penalty = 0.0
    if keyword in constants.BIG_HEAD_KEYWORDS:
        penalty += 25.0
    # 공백 제거 기준 매우 짧은 단독 헤드(롱테일 아님)
    compact = keyword.replace(" ", "")
    if len(compact) <= 3 and " " not in keyword:
        penalty += 15.0
    doc_count = research.blog_document_count if research else None
    if doc_count is not None:
        if doc_count >= 1_000_000:
            penalty += 20.0
        elif doc_count >= 300_000:
            penalty += 10.0
    return penalty


def _mismatch_penalty(keyword: str, topic: TopicExtraction) -> float:
    """키워드가 주장하는 맥락을 토픽 플래그가 부정하면 0보다 큰 감점."""
    penalty = 0.0
    for modifiers, flag_name in _MISMATCH_RULES:
        if _has_any(keyword, modifiers) and not getattr(topic, flag_name, False):
            penalty += 20.0
    return penalty


def _demand_and_opportunity(research: KeywordResearch | None) -> tuple[float, float]:
    """research 에서 수요/기회 점수를 읽거나 중립 프록시로 대체."""
    if research is None:
        return _NEUTRAL_DEMAND, _NEUTRAL_OPPORTUNITY
    demand = research.search_demand_score
    opportunity = research.opportunity_score
    demand_val = _NEUTRAL_DEMAND if demand is None else float(demand)
    opp_val = _NEUTRAL_OPPORTUNITY if opportunity is None else float(opportunity)
    return _clamp(demand_val), _clamp(opp_val)


def _dominant_reason(
    keyword: str,
    demand: float,
    opportunity: float,
    fit: float,
    content: float,
    season: float,
    competition_pen: float,
    mismatch_pen: float,
) -> str:
    """최종 점수를 가장 크게 좌우한 요인을 짧은 한글 설명으로."""
    if mismatch_pen > 0:
        return "주제 근거와 맞지 않아 감점(주장 불일치)"
    if competition_pen >= 20:
        return "경쟁 과포화(빅키워드/문서수 과다)로 감점"
    factors = {
        "검색수요": demand,
        "기회(저경쟁)": opportunity,
        "내 블로그 적합도": fit,
        "콘텐츠 적합도": content,
        "시즌성": season,
    }
    top = max(factors, key=factors.get)
    return f"{top} 우세({int(round(factors[top]))}점)"


def score_keywords(
    candidates: KeywordCandidates,
    research: dict[str, KeywordResearch],
    topic: TopicExtraction,
    historical: dict,
    growth_cfg,
) -> list[ScoredKeyword]:
    """후보(primary+secondary) 전체를 채점해 final_score 내림차순으로 반환."""
    scoring = growth_cfg.scoring
    w_demand = float(scoring.get("search_demand_weight", 0.25))
    w_opp = float(scoring.get("opportunity_weight", 0.25))
    w_fit = float(scoring.get("my_blog_fit_weight", 0.25))
    w_content = float(scoring.get("content_fit_weight", 0.15))
    w_season = float(scoring.get("seasonality_weight", 0.10))

    month = datetime.now().month
    research = research or {}

    # primary + secondary 후보를 순서 보존하며 중복 제거
    seen: set[str] = set()
    targets: list[str] = []
    for kw in list(candidates.primary_candidates) + list(candidates.secondary_candidates):
        k = (kw or "").strip()
        if k and k not in seen:
            seen.add(k)
            targets.append(k)

    # 후보 생성기가 '핵심(core)' 으로 분류한 키워드 집합 — primary 슬롯은 여기서 우선 고른다.
    # (그래야 '성수 비오는날' 같은 시즌 롱테일이 핵심 '성수 맛집' 을 제치고 primary 가 되지 않음)
    primary_set = {(k or "").strip() for k in candidates.primary_candidates if (k or "").strip()}

    results: list[ScoredKeyword] = []
    for kw in targets:
        try:
            res = research.get(kw)
            demand, opportunity = _demand_and_opportunity(res)
            fit = _clamp(float(my_blog_fit_score(kw, historical, topic)))
            content = _content_fit_score(kw, topic)
            season = _seasonality_score(kw, month)
            competition_pen = _competition_penalty(kw, res)
            mismatch_pen = _mismatch_penalty(kw, topic)

            final = (
                demand * w_demand
                + opportunity * w_opp
                + fit * w_fit
                + content * w_content
                + season * w_season
                - competition_pen
                - mismatch_pen
            )
            final = _clamp(final)

            reason = _dominant_reason(
                kw, demand, opportunity, fit, content, season, competition_pen, mismatch_pen
            )
            results.append(
                ScoredKeyword(
                    keyword=kw,
                    role="primary" if kw in primary_set else "secondary",
                    final_score=round(final, 2),
                    search_demand_score=round(demand, 2),
                    opportunity_score=round(opportunity, 2),
                    my_blog_fit_score=round(fit, 2),
                    content_fit_score=round(content, 2),
                    seasonality_score=round(season, 2),
                    competition_penalty=round(competition_pen, 2),
                    mismatch_penalty=round(mismatch_pen, 2),
                    reason=reason,
                )
            )
        except Exception:  # noqa: BLE001
            # 한 키워드 실패가 전체를 막지 않게 한다.
            log.warning("키워드 채점 실패, 건너뜀: %s", kw)
            continue

    results.sort(key=lambda s: s.final_score, reverse=True)
    return results


def _normalize(text: str) -> str:
    """근접 중복 비교용: 공백 제거 + 소문자."""
    return re.sub(r"\s+", "", (text or "")).lower()


def _is_near_duplicate(keyword: str, other: str) -> bool:
    """공백 무시 시 한쪽이 다른 쪽을 포함하면 근접 중복으로 본다."""
    a = _normalize(keyword)
    b = _normalize(other)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def select_primary_and_secondary(
    scored: list[ScoredKeyword],
    growth_cfg,
) -> tuple[ScoredKeyword | None, list[ScoredKeyword]]:
    """primary 는 '핵심(core)' 후보 중 최고점, 보조는 그 다음(근접 중복 제외)으로 선정.

    score_keywords 가 후보 생성기의 핵심 후보에 role=='primary' 를 표시해 둔다. 핵심 후보가
    하나라도 있으면 그 안에서 최고점을 primary 로 고른다(시즌·모디파이어 롱테일이 핵심을
    제치지 못하게). 핵심이 없으면 전체 최고점을 primary 로.
    """
    if not scored:
        return None, []

    max_secondary = int(growth_cfg.seo.get("max_selected_secondary_keywords", 5))

    primary_tier = [s for s in scored if s.role == "primary"]
    pool = primary_tier if primary_tier else scored
    primary = max(pool, key=lambda s: s.final_score)

    # 선정 결과로 role 을 최종 확정(정확히 하나만 primary).
    for s in scored:
        s.role = "secondary"
    primary.role = "primary"

    secondaries: list[ScoredKeyword] = []
    for cand in scored:  # 이미 점수 내림차순 정렬됨
        if len(secondaries) >= max_secondary:
            break
        if cand is primary:
            continue
        if _is_near_duplicate(cand.keyword, primary.keyword):
            continue
        if any(_is_near_duplicate(cand.keyword, s.keyword) for s in secondaries):
            continue
        secondaries.append(cand)

    return primary, secondaries
