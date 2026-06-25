from __future__ import annotations

"""제목 최적화 — 자연스러운 한국어 제목 후보 생성·점수화.

primary 키워드를 앞쪽에 배치하고 secondary 1개 + 가치 훅(분위기/장단점/후기/데이트 등)을
엮어 카테고리별 템플릿으로 제목을 만든다. 키워드 스터핑/낚시(클릭베이트) 없이,
모바일에서 읽기 좋은 길이(<=40자 권장)를 지향한다.

점수 = position*0.25 + intent_match*0.25 + click_attractiveness*0.20
       + historical_pattern*0.20 + readability*0.10 - clickbait_penalty - mismatch_penalty
(각 구성요소 0~100, components 에 저장). 결정적(deterministic) — 동일 입력엔 동일 출력.
"""

import re

from ..logging_setup import get_logger
from . import constants
from .models import TitleCandidate, TopicExtraction

log = get_logger()

# 가치 훅(클릭베이트 아님). 카테고리별 자연스러운 마무리/포인트 어구.
_VALUE_HOOKS: dict[str, list[str]] = {
    "맛집": ["솔직 후기", "분위기 좋았던 곳", "방문 후기", "메뉴 추천"],
    "여행": ["가볼만한곳", "다녀온 후기", "코스 정리", "솔직 후기"],
    "육아": ["기록", "솔직 후기", "이렇게 했어요", "꿀팁 정리"],
    "육아템": ["내돈내산 후기", "장단점 정리", "솔직 후기", "실사용 후기"],
    "일상": ["기록", "소소한 후기", "일상 정리"],
    "기타": ["후기", "정리", "솔직 후기"],
}

# 낚시성(클릭베이트) 어구 — 들어가면 감점.
_CLICKBAIT_WORDS: tuple[str, ...] = (
    "충격", "대박", "헉", "미쳤", "역대급", "실화", "소름", "필수템", "무조건", "완벽",
    "최고", "끝판왕", "갓", "레전드", "인생", "단 한 번", "지금 당장", "절대",
)

# mismatch: 토픽 플래그가 없는데 제목이 주장하면 감점할 (어구, 필요 플래그) 목록.
_MISMATCH_CLAIMS: tuple[tuple[str, str], ...] = (
    ("주차", "has_parking_evidence"),
    ("데이트", "has_date_mood"),
    ("아이랑", "has_kid_context"),
    ("아기랑", "has_kid_context"),
    ("내돈내산", "is_product_review"),
    ("실사용", "is_product_review"),
    ("장단점", "is_product_review"),
    ("비교", "is_product_review"),
)

_IDEAL_MAX_CHARS = 40        # 모바일 권장 상한
_HARD_MAX_CHARS = 50         # 이 이상이면 가독성 강하게 감점
_MIN_CHARS = 8


def optimize_titles(
    primary: str,
    secondaries: list[str],
    topic: TopicExtraction,
    historical: dict,
    growth_cfg,
) -> list[TitleCandidate]:
    """제목 후보를 만들어 점수순으로 정렬해 반환(첫 번째가 추천 제목).

    primary 가 비면 secondary/토픽으로 폴백한다. 실패해도 빈 리스트만 반환(예외 금지).
    """
    try:
        cap = int(growth_cfg.seo.get("max_title_candidates", 10) or 10)
    except Exception:  # noqa: BLE001
        cap = 10
    cap = max(1, cap)

    primary = (primary or "").strip()
    secs = [s.strip() for s in (secondaries or []) if s and s.strip()]
    # primary 가 없으면 secondary 첫 항목을, 그것도 없으면 토픽 코어를 primary 로 승격.
    if not primary:
        if secs:
            primary = secs.pop(0)
        else:
            primary = _topic_core(topic)
    if not primary:
        log.warning("[title_optimizer] primary 키워드/토픽 코어가 비어 제목 생성 생략")
        return []

    category = (getattr(topic, "category", None) or "기타").strip() or "기타"
    raw_titles = _build_raw_titles(primary, secs, topic, category)

    # 중복 제거(순서 보존) 후 점수화.
    seen: dict[str, None] = {}
    candidates: list[TitleCandidate] = []
    for title in raw_titles:
        t = _normalize_title(title)
        if not t or t in seen:
            continue
        seen[t] = None
        candidates.append(_score_title(t, primary, secs, topic, historical, category))

    # 점수 내림차순(동점이면 짧은 제목 우선 → 결정적). title 로 최종 타이브레이크.
    candidates.sort(key=lambda c: (-c.score, len(c.title), c.title))
    return candidates[:cap]


# ───────────────────────── 제목 후보 생성 ─────────────────────────

def _build_raw_titles(
    primary: str,
    secs: list[str],
    topic: TopicExtraction,
    category: str,
) -> list[str]:
    """primary 앞쪽 + secondary 1개 + 가치 훅 조합으로 자연스러운 제목들을 만든다."""
    hooks = _VALUE_HOOKS.get(category, _VALUE_HOOKS["기타"])
    sec1 = secs[0] if secs else ""
    sec2 = secs[1] if len(secs) > 1 else ""
    location = (getattr(topic, "location", None) or "").strip()
    product = (getattr(topic, "product_type", None) or "").strip()
    menu = _topic_field(topic, "menu") or _topic_field(topic, "메뉴")

    out: list[str] = []

    def add(t: str) -> None:
        if t and t.strip():
            out.append(t.strip())

    # 1) primary 단독 + 훅 (가장 안전한 기본형) — 훅 2종.
    add(f"{primary}, {hooks[0]}")
    if len(hooks) > 1:
        add(f"{primary} {hooks[1]}")

    # 2) primary + secondary + 훅 (secondary 가 primary 와 안 겹칠 때만).
    if sec1 and not _overlaps(primary, sec1):
        add(f"{primary}, {sec1} {hooks[0]}")
        add(f"{primary} {hooks[0]} ({sec1})")
    if sec2 and not _overlaps(primary, sec2) and not _overlaps(sec1, sec2):
        add(f"{primary}, {sec2} {hooks[0]}")

    # 3) 카테고리별 자연 템플릿.
    if category == "맛집":
        food = menu or sec1
        if location and food and not _overlaps(location, food):
            add(f"{location} 데이트 맛집, 분위기 좋았던 {food} 후기"
                if getattr(topic, "has_date_mood", False)
                else f"{location} 맛집, {food} 솔직 후기")
        if location and not _overlaps(primary, location):
            add(f"{primary}, {location} 다녀온 솔직 후기")
    elif category == "여행":
        if location and not _overlaps(primary, location):
            add(f"{location} 가볼만한곳, {primary} 다녀온 후기")
        add(f"{primary}, 코스랑 후기 정리")
    elif category == "육아템":
        prod = product or primary
        add(f"{prod} 내돈내산 후기, 세척과 흡착력 장단점 정리"
            if getattr(topic, "is_product_review", False)
            else f"{prod} 후기, 장단점 정리")
        if sec1 and not _overlaps(prod, sec1):
            add(f"{prod} 실사용 후기, {sec1}까지 정리")
    elif category == "육아":
        add(f"{primary} 기록, 우리 아이 이야기")
        if sec1 and not _overlaps(primary, sec1):
            add(f"{primary}, {sec1} 꿀팁 정리")
    else:  # 일상/기타
        add(f"{primary}, 소소한 기록")

    # 4) 마지막 보강: secondary 들을 자연스럽게 끼운 형태(있으면).
    if sec1 and not _overlaps(primary, sec1):
        add(f"{primary} {sec1} {hooks[0]}")

    return out


def _topic_core(topic: TopicExtraction) -> str:
    """primary/secondary 가 모두 없을 때 쓰는 토픽 코어(폴백)."""
    for attr in ("product_type", "location", "brand"):
        v = (getattr(topic, attr, None) or "").strip()
        if v:
            return v
    topics = getattr(topic, "detected_topics", None) or []
    for t in topics:
        if t and t.strip():
            return t.strip()
    return ""


def _topic_field(topic: TopicExtraction, key: str) -> str:
    """topic.extra 에서 보조 필드(menu/메뉴 등)를 안전하게 꺼낸다."""
    extra = getattr(topic, "extra", None) or {}
    v = extra.get(key)
    return (v or "").strip() if isinstance(v, str) else ""


# ───────────────────────── 점수화 ─────────────────────────

def _score_title(
    title: str,
    primary: str,
    secs: list[str],
    topic: TopicExtraction,
    historical: dict,
    category: str,
) -> TitleCandidate:
    position = _position_score(title, primary)
    intent_match = _intent_match_score(title, primary, secs, topic)
    click = _click_attractiveness_score(title, category)
    hist = _historical_pattern_score(title, historical)
    readability = _readability_score(title)
    clickbait_pen = _clickbait_penalty(title)
    mismatch_pen = _mismatch_penalty(title, topic)
    stuffing_pen = _stuffing_penalty(title)

    final = (
        position * 0.25
        + intent_match * 0.25
        + click * 0.20
        + hist * 0.20
        + readability * 0.10
        - clickbait_pen
        - mismatch_pen
        - stuffing_pen          # ⭐ 키워드 반복(스터핑)은 최종 점수에서 직접 강하게 감점
    )
    final = max(0.0, min(100.0, final))

    components = {
        "position": round(position, 1),
        "intent_match": round(intent_match, 1),
        "click_attractiveness": round(click, 1),
        "historical_pattern": round(hist, 1),
        "readability": round(readability, 1),
        "clickbait_penalty": round(clickbait_pen, 1),
        "mismatch_penalty": round(mismatch_pen, 1),
        "stuffing_penalty": round(stuffing_pen, 1),
    }
    reason = _build_reason(title, primary, components)
    return TitleCandidate(title=title, score=round(final, 1), reason=reason, components=components)


def _position_score(title: str, primary: str) -> float:
    """primary 가 앞쪽(특히 첫 단어)일수록 높음. 없으면 0."""
    if not primary:
        return 0.0
    idx = title.find(primary)
    if idx < 0:
        return 0.0
    n = max(1, len(title))
    # 0(맨앞)이면 100, 길이 비례로 선형 감소(최소 40 보장).
    return max(40.0, 100.0 - (idx / n) * 100.0)


def _intent_match_score(
    title: str,
    primary: str,
    secs: list[str],
    topic: TopicExtraction,
) -> float:
    """검색 의도 충족: primary 포함 + secondary/의도어 반영 + 후기/추천 등 의도 시그널."""
    score = 50.0
    if primary and primary in title:
        score += 25.0
    # secondary 1개라도 들어가면 의도 보강(과다 스터핑은 readability/clickbait 가 잡음).
    if any(s and s in title for s in secs):
        score += 15.0
    # 토픽 target_intents 단어가 제목에 닿으면 가산.
    intents = getattr(topic, "target_intents", None) or []
    if any(_token_in(title, it) for it in intents):
        score += 10.0
    # '후기/추천/정리/장단점' 같은 검색 의도 시그널.
    if re.search(r"(후기|추천|정리|장단점|가볼만한곳|꿀팁|비교)", title):
        score += 5.0
    return max(0.0, min(100.0, score))


def _click_attractiveness_score(title: str, category: str) -> float:
    """낚시 없이 클릭을 끄는 요소(가치 훅·구체 어구). 밋밋하면 중립."""
    score = 55.0
    hooks = _VALUE_HOOKS.get(category, _VALUE_HOOKS["기타"])
    if any(h in title for h in hooks):
        score += 20.0
    if re.search(r"(분위기|솔직|내돈내산|장단점|가성비|실사용)", title):
        score += 15.0
    # 너무 길면 매력도도 약간 깎임(스캔 어려움).
    if len(title) > _IDEAL_MAX_CHARS:
        score -= 10.0
    return max(0.0, min(100.0, score))


def _historical_pattern_score(title: str, historical: dict) -> float:
    """과거 잘 된 글의 강한 키워드/패턴과 겹치면 가산. 이력 없으면 중립 50."""
    strong = (historical or {}).get("strong_keywords") or []
    inflow = (historical or {}).get("inflow_keyword_freq") or {}
    if not strong and not inflow:
        return 50.0
    score = 50.0
    hit = 0
    for kw in strong:
        if kw and _token_in(title, kw):
            hit += 1
    for kw in inflow.keys():
        if kw and _token_in(title, kw):
            hit += 1
    score += min(40.0, hit * 12.0)
    return max(0.0, min(100.0, score))


def _readability_score(title: str) -> float:
    """모바일 가독성: 길이/단어수/반복 기준. 길거나 단어 반복 많으면 감점."""
    n = len(title)
    score = 100.0
    if n < _MIN_CHARS:
        score -= 25.0
    if n > _IDEAL_MAX_CHARS:
        score -= (n - _IDEAL_MAX_CHARS) * 2.0
    if n > _HARD_MAX_CHARS:
        score -= 15.0
    # 단어 중복(같은 토큰 2회 이상)이면 가독성/스터핑 신호 → 감점.
    tokens = [t for t in re.split(r"\s+", title) if t]
    dup = len(tokens) - len(set(tokens))
    score -= dup * 12.0
    # 반복 어구(스터핑) — 2자 이상 토큰이 제목에 2회 이상 나오면 감점.
    score -= _repeat_phrase_penalty(title, tokens)
    # 구분기호(대시/middot)는 네이버 가로선 위험 → 강한 감점.
    if re.search(r"[—–·]|--", title):
        score -= 30.0
    return max(0.0, min(100.0, score))


def _repeat_phrase_penalty(title: str, tokens: list[str]) -> float:
    """2자 이상 토큰이 제목 안에서 2회 이상 등장하면 스터핑으로 보고 감점."""
    pen = 0.0
    counted: set[str] = set()
    for tok in tokens:
        if len(tok) < 2 or tok in counted:
            continue
        counted.add(tok)
        if title.count(tok) >= 2:
            pen += 15.0
    return min(45.0, pen)


def _stuffing_penalty(title: str) -> float:
    """같은 의미 토큰(2자+)이 제목에서 반복되면 키워드 스터핑으로 보고 직접 감점.

    readability 에도 반영되지만 가중치(0.10)가 작아 '내돈내산 내돈내산' 같은 스터핑이
    상위로 올라오는 걸 못 막는다. 그래서 최종 점수에서 별도로 강하게 깎는다.
    """
    toks = [re.sub(r"[^0-9A-Za-z가-힣]", "", t) for t in re.split(r"\s+", title)]
    toks = [t for t in toks if len(t) >= 2]
    counts: dict[str, int] = {}
    for t in toks:
        counts[t] = counts.get(t, 0) + 1
    pen = sum((c - 1) * 16.0 for c in counts.values() if c >= 2)
    return min(70.0, pen)


def _clickbait_penalty(title: str) -> float:
    """낚시성 어구·과도한 느낌표/물음표 → 양수 감점."""
    pen = 0.0
    for w in _CLICKBAIT_WORDS:
        if w in title:
            pen += 20.0
    # 느낌표/물음표 남발.
    marks = title.count("!") + title.count("?")
    if marks >= 2:
        pen += 10.0
    elif marks == 1:
        pen += 4.0
    if "..." in title or "…" in title:
        pen += 6.0
    return min(60.0, pen)


def _mismatch_penalty(title: str, topic: TopicExtraction) -> float:
    """제목이 토픽 플래그가 없는 사실을 주장하면 감점(주차/데이트/아이랑/내돈내산 등)."""
    pen = 0.0
    for phrase, flag in _MISMATCH_CLAIMS:
        if phrase in title and not bool(getattr(topic, flag, False)):
            pen += 18.0
    return min(60.0, pen)


# ───────────────────────── 보조 유틸 ─────────────────────────

def _overlaps(a: str, b: str) -> bool:
    """두 키워드가 서로 포함관계면 True(중복 결합 방지)."""
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return False
    return a in b or b in a


def _token_in(title: str, keyword: str) -> bool:
    """키워드의 토큰 중 하나라도 제목에 포함되면 True(공백 분리 기준)."""
    kw = (keyword or "").strip()
    if not kw:
        return False
    if kw in title:
        return True
    return any(tok and tok in title for tok in kw.split())


def _normalize_title(title: str) -> str:
    """공백 정리. 양끝 구분기호/쉼표 정돈."""
    t = re.sub(r"\s+", " ", (title or "").strip())
    t = re.sub(r"\s+,", ",", t)
    t = re.sub(r",{2,}", ",", t)
    return t.strip(" ,")


def _build_reason(title: str, primary: str, components: dict) -> str:
    """사람이 읽는 짧은 근거(왜 이 점수인지)."""
    bits: list[str] = []
    if primary and title.startswith(primary):
        bits.append("primary 키워드를 맨 앞에 배치")
    elif primary and primary in title:
        bits.append("primary 키워드를 앞쪽에 배치")
    if components.get("clickbait_penalty", 0) > 0:
        bits.append("낚시성 표현 감점")
    if components.get("stuffing_penalty", 0) > 0:
        bits.append("키워드 반복(스터핑) 감점")
    if components.get("mismatch_penalty", 0) > 0:
        bits.append("사진/사실과 맞지 않는 주장 감점")
    if len(title) > _IDEAL_MAX_CHARS:
        bits.append(f"길이 {len(title)}자(모바일 권장 초과)")
    else:
        bits.append(f"길이 {len(title)}자")
    return ", ".join(bits) if bits else "기본 점수"
