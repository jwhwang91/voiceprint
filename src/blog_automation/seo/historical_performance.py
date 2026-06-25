from __future__ import annotations

"""내 블로그 과거 성과 분석(historical performance).

repo(과거글/성과/유입키워드)만 읽어 카테고리 평균 조회수·검색유입, 유입 키워드 빈도,
강한/약한 제목 패턴(휴리스틱), 유사글 등을 산출한다. 키워드 점수 모듈이 이 결과로
'내 블로그 적합도(my_blog_fit_score)'를 계산한다.

순수 함수(읽기 전용). DB 가 비어 있어도 0/빈값으로 graceful 하게 반환한다.
"""

import math
import re
from collections import Counter
from datetime import date
from typing import TYPE_CHECKING, Any

from ..logging_setup import get_logger

if TYPE_CHECKING:  # 순환 import 회피(런타임엔 타입만 필요)
    from .models import PostMetric, PostRecord, TopicExtraction
    from .repository import Repository

log = get_logger()

# 7d/30d 근사에 쓰는 윈도(일). 발행일로부터 이 일수 이내의 최신 metric 을 그 구간 대표값으로 본다.
_WINDOW_7D = 7
_WINDOW_30D = 30

# 제목 패턴 휴리스틱: (정규식, 사람이 읽는 한국어 라벨)
# 강한/약한 패턴을 median 조회수 대비로 갈라 설명한다.
_TITLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"내돈내산"), "제품명 + 내돈내산"),
    (re.compile(r"(개월|돌|살|세)\b.*(후기|리뷰|추천)"), "월령/나이 + 후기"),
    (re.compile(r"(후기|사용후기|실사용|실제\s*사용)"), "제품/방문 + 후기"),
    (re.compile(r"(장단점|단점|비교)"), "장단점/비교 정보형"),
    (re.compile(r"(추천|추천템|국민템)"), "추천/추천템형"),
    (re.compile(r"(맛집|식당|카페)"), "지역 + 맛집/카페"),
    (re.compile(r"(아이랑|아기랑|가족|아이와)"), "아이랑/가족 동반형"),
    (re.compile(r"(데이트|분위기)"), "데이트/분위기형"),
    (re.compile(r"(주차|예약|웨이팅)"), "주차/예약/웨이팅 실용정보형"),
    (re.compile(r"(여행|가볼만한곳|나들이|코스)"), "여행/나들이 코스형"),
]

# 토큰 분리(한글/영문/숫자 2자 이상). 짧은 조사/기호는 버린다.
_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")

# fit 점수에서 의미 없는 흔한 토큰(겹쳐도 가산 안 함).
_STOPWORD_TOKENS = {"후기", "추천", "리뷰", "맛집", "여행", "육아", "사진", "오늘", "방문", "정보"}


def _parse_date(s: str | None) -> date | None:
    """'YYYY-MM-DD'(앞부분) 파싱. 실패하면 None."""
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _window_metric(
    metrics: list["PostMetric"], published: date | None, window_days: int
) -> "PostMetric | None":
    """발행일 + window_days 이내의 최신 metric 을 그 구간 대표로 고른다.

    발행일을 모르면 전체 metric 중 최신을 반환(근사). metric 이 없으면 None.
    metrics 는 repository 가 metric_date 오름차순으로 준다.
    """
    if not metrics:
        return None
    if published is None:
        return metrics[-1]
    best: "PostMetric | None" = None
    for m in metrics:
        md = _parse_date(m.metric_date)
        if md is None:
            continue
        delta = (md - published).days
        if 0 <= delta <= window_days:
            best = m  # 오름차순이라 마지막으로 잡힌 게 윈도 내 최신
    # 윈도 안에 아무 metric 도 없으면 None(데이터 없음으로 취급).
    #   ⚠️ metrics[0](=가장 이른) 을 쓰면 발행 이전 스냅샷이 섞여 평균을 왜곡한다.
    return best


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {t.lower() for t in _TOKEN_RE.findall(text)}


def _empty_result(category: str | None) -> dict[str, Any]:
    """DB 가 비었거나 분석 불가일 때의 안전한 0/빈 결과."""
    return {
        "category": category,
        "category_avg_views_7d": 0.0,
        "category_avg_views_30d": 0.0,
        "category_avg_search_inflow_30d": 0.0,
        "strong_patterns": [],
        "weak_patterns": [],
        "similar_posts": [],
        "strong_keywords": [],
        "inflow_keyword_freq": {},
    }


def _post_main_keywords(
    post: "PostRecord", inflow_by_post: dict[str, Counter]
) -> list[str]:
    """글의 대표 키워드: 유입 키워드 상위 + 태그(중복 제거, 순서 보존)."""
    out: list[str] = []
    seen: set[str] = set()
    for kw, _cnt in inflow_by_post.get(post.post_id, Counter()).most_common(5):
        k = (kw or "").strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    for tag in post.tags or []:
        t = (tag or "").strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= 6:
            break
    return out


def analyze(
    repo: "Repository",
    category: str | None,
    topic: "TopicExtraction | None" = None,
) -> dict[str, Any]:
    """과거글/성과/유입키워드에서 카테고리 성과 요약을 만든다.

    category 가 주어지면 해당 카테고리 글만, 없으면 전체 글을 본다.
    DB 가 비어 있으면 0/빈값을 반환하고 절대 예외를 던지지 않는다.
    """
    try:
        if category:
            posts = repo.get_posts_by_category(category)
            if not posts:  # 카테고리 데이터가 없으면 전체로 폴백(있는 신호라도 쓴다)
                posts = repo.get_all_posts()
        else:
            posts = repo.get_all_posts()
    except Exception as e:  # noqa: BLE001
        log.warning("historical analyze: 글 조회 실패 → 빈 결과(%s)", e)
        return _empty_result(category)

    if not posts:
        return _empty_result(category)

    # 글별 유입 키워드(post_id → Counter) + 전체 빈도
    inflow_by_post: dict[str, Counter] = {}
    global_freq: Counter = Counter()
    try:
        for ik in repo.get_all_inflow_keywords():
            kw = (ik.keyword or "").strip()
            if not kw:
                continue
            cnt = ik.inflow_count or 0
            inflow_by_post.setdefault(ik.post_id, Counter())[kw] += cnt
            global_freq[kw] += cnt
    except Exception as e:  # noqa: BLE001
        log.warning("historical analyze: 유입키워드 조회 실패(무시) %s", e)

    # 분석 대상 post_id 집합으로 전역 빈도를 제한(카테고리 일관성)
    post_ids = {p.post_id for p in posts}
    inflow_freq: Counter = Counter()
    for pid in post_ids:
        for kw, c in inflow_by_post.get(pid, Counter()).items():
            inflow_freq[kw] += c
    if not inflow_freq:  # 카테고리 글에 유입 데이터가 없으면 전역 빈도라도 노출
        inflow_freq = global_freq
    # 통계(유입 데이터)가 아직 없으면 글 '태그 빈도'를 '내 강점 영역' 신호로 대체한다.
    #   stats 크롤러가 조회수/유입을 채우기 전까지, 블로그가 자주 쓰는 태그(성수데이트·성수맛집…)가
    #   곧 그 블로그의 강점 키워드 영역이다.
    if not inflow_freq:
        tag_freq: Counter = Counter()
        for p in posts:
            for t in (p.tags or []):
                t = (t or "").strip()
                if t:
                    tag_freq[t] += 1
        inflow_freq = tag_freq

    # 글별 7d/30d 조회수·30d 검색유입(근사)
    per_post: list[dict[str, Any]] = []
    for p in posts:
        try:
            metrics = repo.get_metrics_for_post(p.post_id)
        except Exception as e:  # noqa: BLE001
            log.warning("historical analyze: metric 조회 실패(%s) %s", p.post_id, e)
            metrics = []
        pub = _parse_date(p.published_at)
        m7 = _window_metric(metrics, pub, _WINDOW_7D)
        m30 = _window_metric(metrics, pub, _WINDOW_30D)
        views_7d = float(m7.views) if m7 else 0.0
        views_30d = float(m30.views) if m30 else 0.0
        inflow_30d = float(m30.search_inflow) if m30 else 0.0
        per_post.append(
            {
                "post": p,
                "views_7d": views_7d,
                "views_30d": views_30d,
                "search_inflow_30d": inflow_30d,
            }
        )

    # 카테고리 평균(데이터 있는 글만 평균 — 0만 있으면 0)
    def _avg(key: str) -> float:
        vals = [d[key] for d in per_post]
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    cat_avg_7d = _avg("views_7d")
    cat_avg_30d = _avg("views_30d")
    cat_avg_inflow_30d = _avg("search_inflow_30d")

    # 강한/약한 제목 패턴: 30d 조회수 median 기준으로 글을 상/하위로 나누고
    # 각 패턴이 상위에 더 많이 나타나면 strong, 하위에 치우치면 weak.
    views_sorted = sorted(d["views_30d"] for d in per_post)
    n = len(views_sorted)
    median = views_sorted[n // 2] if n else 0.0
    strong_patterns, weak_patterns = _infer_title_patterns(per_post, median)

    # 강한 키워드: 유입 빈도 상위
    strong_keywords = [kw for kw, _ in inflow_freq.most_common(15)]

    # 유사글: 같은 모집단에서 30d 조회수 상위 + (topic 있으면 토큰 겹침 가산)
    topic_tokens = _topic_tokens(topic)
    ranked = sorted(
        per_post,
        key=lambda d: (
            d["views_30d"] + _overlap_bonus(d["post"], inflow_by_post, topic_tokens)
        ),
        reverse=True,
    )
    similar_posts: list[dict[str, Any]] = []
    for d in ranked[:5]:
        p: "PostRecord" = d["post"]
        similar_posts.append(
            {
                "post_id": p.post_id,
                "title": p.title,
                "views_30d": int(d["views_30d"]),
                "search_inflow_30d": int(d["search_inflow_30d"]),
                "main_keywords": _post_main_keywords(p, inflow_by_post),
            }
        )

    return {
        "category": category,
        "category_avg_views_7d": cat_avg_7d,
        "category_avg_views_30d": cat_avg_30d,
        "category_avg_search_inflow_30d": cat_avg_inflow_30d,
        "strong_patterns": strong_patterns,
        "weak_patterns": weak_patterns,
        "similar_posts": similar_posts,
        "strong_keywords": strong_keywords,
        "inflow_keyword_freq": dict(inflow_freq.most_common(40)),
    }


def _topic_tokens(topic: "TopicExtraction | None") -> set[str]:
    """topic 의 핵심 필드를 토큰화(유사글 가산용)."""
    if topic is None:
        return set()
    parts: list[str] = []
    for v in (
        topic.location,
        topic.product_type,
        topic.brand,
        topic.age_group,
        topic.content_type,
    ):
        if v:
            parts.append(str(v))
    parts.extend(topic.detected_topics or [])
    return _tokens(" ".join(parts))


def _overlap_bonus(
    post: "PostRecord", inflow_by_post: dict[str, Counter], topic_tokens: set[str]
) -> float:
    """topic 토큰이 글 제목/유입키워드와 겹치면 유사글 랭킹에 소폭 가산."""
    if not topic_tokens:
        return 0.0
    post_tokens = _tokens(post.title)
    for kw in inflow_by_post.get(post.post_id, Counter()):
        post_tokens |= _tokens(kw)
    overlap = topic_tokens & post_tokens
    return float(len(overlap)) * 0.5  # 조회수 스케일 대비 약한 타이브레이커


def _infer_title_patterns(
    per_post: list[dict[str, Any]], median: float
) -> tuple[list[str], list[str]]:
    """제목 패턴별로 평균 조회수를 모아 median 대비 강/약을 한국어 라벨로 설명."""
    if not per_post:
        return [], []
    # 패턴 라벨 → 조회수 리스트
    bucket: dict[str, list[float]] = {}
    for d in per_post:
        title = d["post"].title or ""
        for pat, label in _TITLE_PATTERNS:
            if pat.search(title):
                bucket.setdefault(label, []).append(d["views_30d"])

    strong: list[tuple[str, float]] = []
    weak: list[tuple[str, float]] = []
    for label, vals in bucket.items():
        if len(vals) < 1:
            continue
        avg = sum(vals) / len(vals)
        if avg >= median and avg > 0:
            strong.append((label, avg))
        elif avg < median:
            weak.append((label, avg))

    strong.sort(key=lambda x: x[1], reverse=True)
    weak.sort(key=lambda x: x[1])
    strong_labels = [f"{lbl} (평균 조회 {int(avg)})" for lbl, avg in strong[:4]]
    weak_labels = [f"{lbl} (평균 조회 {int(avg)})" for lbl, avg in weak[:4]]
    return strong_labels, weak_labels


def my_blog_fit_score(
    keyword: str,
    historical: dict[str, Any],
    topic: "TopicExtraction | None" = None,
) -> float:
    """키워드가 내 블로그 과거 강점과 얼마나 맞는지 0~100.

    중립 50 기준. strong_keywords/유입 빈도와 토큰이 겹치면 가산,
    topic.category 가 historical['category'] 와 같으면 가산. 0~100 으로 clamp.
    """
    if not keyword:
        return 50.0
    if not historical:
        return 50.0

    score = 50.0
    kw_tokens = _tokens(keyword) - _STOPWORD_TOKENS
    if not kw_tokens:
        kw_tokens = _tokens(keyword)  # 전부 stopword 면 그대로 본다

    strong_keywords = historical.get("strong_keywords") or []
    strong_tokens: set[str] = set()
    for sk in strong_keywords:
        strong_tokens |= _tokens(sk)

    # 1) 강한 키워드와의 토큰 겹침(키워드당 +8, 최대 +24).
    #    정확 일치 + 부분 포함(압축 태그 대응): '성수'(키워드) ⊂ '성수데이트'(태그) 도 매칭한다.
    def _hits(kt: str) -> bool:
        if kt in strong_tokens:
            return True
        return any((len(kt) >= 2 and kt in s) or (len(s) >= 2 and s in kt)
                   for s in strong_tokens)

    overlap = {kt for kt in kw_tokens if _hits(kt)}
    score += min(len(overlap) * 8.0, 24.0)

    # 2) 키워드 전체가 강한 키워드 목록에 직접 존재하면 강한 가산
    kw_norm = keyword.strip().lower()
    if any(kw_norm == (sk or "").strip().lower() for sk in strong_keywords):
        score += 12.0

    # 3) 유입 빈도 가중(겹친 토큰의 누적 빈도가 크면 추가 가산, 최대 +12)
    freq = historical.get("inflow_keyword_freq") or {}
    if freq and overlap:
        freq_tokens: Counter = Counter()
        for fk, c in freq.items():
            for t in _tokens(fk):
                freq_tokens[t] += int(c or 0)
        hit = sum(freq_tokens.get(t, 0) for t in overlap)
        if hit > 0:
            score += min(math.log1p(hit) * 3.0, 12.0)

    # 4) 카테고리 일치 가산
    hist_cat = historical.get("category")
    if topic is not None and hist_cat and topic.category == hist_cat:
        score += 6.0

    # 5) 약한 패턴 토큰과만 겹치고 강점은 없으면 소폭 감점
    if not overlap:
        weak_tokens: set[str] = set()
        for wp in historical.get("weak_patterns") or []:
            weak_tokens |= _tokens(wp)
        if kw_tokens & weak_tokens:
            score -= 4.0

    return max(0.0, min(100.0, round(score, 1)))
