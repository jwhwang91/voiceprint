"""title_optimizer (additive SEO layer) — 제목 후보 생성·점수화 테스트.

추천 제목(titles[0])이 primary 키워드를 앞쪽에 두는지, 키워드 스터핑(중복 토큰)이
깨끗한 제목보다 낮게 점수화되는지, 클릭베이트/길이/사실 불일치가 감점되는지,
그리고 결정적(deterministic)인지 검증한다.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blog_automation.seo.title_optimizer import (  # noqa: E402
    optimize_titles,
    _clickbait_penalty,
    _score_title,
    _CLICKBAIT_WORDS,
)
from blog_automation.seo.config import load_growth_config  # noqa: E402
from blog_automation.seo.models import TopicExtraction  # noqa: E402


# ───────────────────────── fixtures/helpers ─────────────────────────

def _cfg():
    g = load_growth_config()
    return g


def _foodie_topic():
    """방문형 맛집 토픽 — 주차 증거 없음(mismatch 검증용)."""
    return TopicExtraction(
        input_folder="job_food",
        category="맛집",
        location="성수",
        detected_topics=["카페"],
        target_intents=["후기", "추천"],
        has_parking_evidence=False,
        has_date_mood=False,
        has_kid_context=False,
    )


def _has_repeated_token(title: str) -> bool:
    """제목 안에서 2자 이상 토큰이 (즉시/비즉시 상관없이) 2회 이상 등장하면 True."""
    toks = [re.sub(r"[^0-9A-Za-z가-힣]", "", t) for t in re.split(r"\s+", title)]
    toks = [t for t in toks if len(t) >= 2]
    counts: dict[str, int] = {}
    for t in toks:
        counts[t] = counts.get(t, 0) + 1
    return any(c >= 2 for c in counts.values())


# ───────────────────────── tests ─────────────────────────

def test_recommended_contains_primary_near_front():
    g = _cfg()
    topic = _foodie_topic()
    primary = "성수 카페"
    titles = optimize_titles(primary, ["브런치"], topic, {}, g)

    assert titles, "후보가 비어 있으면 안 됨"
    top = titles[0].title
    # 추천 제목은 primary 키워드를 포함해야 한다.
    assert primary in top
    # 그리고 앞쪽(맨 앞으로 시작하거나, 전반부 안)이어야 한다.
    idx = top.find(primary)
    assert top.startswith(primary) or idx <= len(top) // 2


def test_no_repeated_token_in_top_two():
    """스터핑(중복 토큰)된 제목은 상위 2개에 올라오지 않아야 한다."""
    g = _cfg()
    topic = _foodie_topic()
    titles = optimize_titles("성수 카페", ["브런치"], topic, {}, g)
    assert len(titles) >= 1
    for cand in titles[:2]:
        assert not _has_repeated_token(cand.title), (
            f"상위 제목에 반복 토큰: {cand.title!r}"
        )


def test_stuffed_title_scores_lower_than_clean():
    """'... 내돈내산 내돈내산 ...' 같이 토큰이 중복된 제목은
    깨끗한 추천 제목보다 점수가 낮아야 한다."""
    g = _cfg()
    topic = _foodie_topic()
    titles = optimize_titles("성수 카페", ["브런치"], topic, {}, g)
    assert titles
    recommended = titles[0]

    # 동일 primary 로, 토큰을 일부러 중복시킨 스터핑 제목을 직접 점수화.
    stuffed = _score_title(
        "성수 카페 내돈내산 내돈내산 후기",
        "성수 카페",
        ["브런치"],
        topic,
        {},
        "맛집",
    )
    assert stuffed.components.get("stuffing_penalty", 0) > 0
    assert stuffed.score < recommended.score


def test_clickbait_words_penalized_directly():
    """클릭베이트 어구는 clickbait_penalty 를 통해 직접 감점된다."""
    for word in ("대박", "충격"):
        assert word in _CLICKBAIT_WORDS
        pen = _clickbait_penalty(f"성수 카페 {word} 후기")
        assert pen > 0
    # 클릭베이트 없는 제목은 0 감점.
    assert _clickbait_penalty("성수 카페 솔직 후기") == 0.0


def test_returned_titles_have_no_clickbait_words():
    """optimize 가 만든 어떤 후보도 클릭베이트 단어를 포함하지 않는다."""
    g = _cfg()
    topic = _foodie_topic()
    titles = optimize_titles("성수 카페", ["브런치"], topic, {}, g)
    assert titles
    for cand in titles:
        for word in _CLICKBAIT_WORDS:
            assert word not in cand.title, f"클릭베이트 '{word}' in {cand.title!r}"


def test_all_titles_within_length_cap():
    """모든 후보 제목은 ~50자 이내여야 한다."""
    g = _cfg()
    topic = _foodie_topic()
    titles = optimize_titles("성수 카페", ["브런치", "디저트"], topic, {}, g)
    assert titles
    for cand in titles:
        assert len(cand.title) <= 50, f"너무 김({len(cand.title)}자): {cand.title!r}"


def test_optimizer_does_not_invent_parking_without_evidence():
    """주차 증거가 없을 때, 옵티마이저가 스스로 '주차'를 지어내지 않아야 한다.

    (secondary 로 강제 주입하지 않는 한 어떤 후보에도 '주차'가 없어야 함.)
    """
    g = _cfg()
    topic = _foodie_topic()
    assert topic.has_parking_evidence is False
    titles = optimize_titles("성수 카페", ["브런치"], topic, {}, g)
    assert titles
    for cand in titles:
        assert "주차" not in cand.title, f"증거 없이 주차를 지어냄: {cand.title!r}"


def test_recommended_title_does_not_claim_parking_without_evidence():
    """'주차'를 secondary 로 주입해도, mismatch 감점으로 추천(1위) 제목은 '주차'를 빼야 한다."""
    g = _cfg()
    topic = _foodie_topic()
    assert topic.has_parking_evidence is False
    titles = optimize_titles("성수 카페", ["주차"], topic, {}, g)
    assert titles
    # 1위(추천) 제목은 증거 없는 주차 주장을 하지 않는다.
    assert "주차" not in titles[0].title, f"추천 제목에 주차 주장: {titles[0].title!r}"
    # 그리고 주차를 포함한 후보는 깨끗한 1위보다 낮게 점수화된다.
    parking_cands = [c for c in titles if "주차" in c.title]
    assert parking_cands  # 주입했으니 후보로는 존재
    assert all(c.score < titles[0].score for c in parking_cands)


def test_mismatch_penalty_lowers_parking_claim():
    """주차 증거 없는 토픽에서 '주차'를 주장한 제목은 mismatch 감점을 받아야 한다."""
    topic = _foodie_topic()
    cand = _score_title("성수 카페 주차 후기", "성수 카페", [], topic, {}, "맛집")
    assert cand.components.get("mismatch_penalty", 0) > 0


def test_deterministic():
    """동일 입력엔 동일 출력(제목·점수 모두)."""
    g = _cfg()
    topic = _foodie_topic()
    run1 = optimize_titles("성수 카페", ["브런치"], topic, {}, g)
    run2 = optimize_titles("성수 카페", ["브런치"], topic, {}, g)
    assert [(c.title, c.score) for c in run1] == [(c.title, c.score) for c in run2]


def test_missing_open_api_credentials_does_not_break(monkeypatch):
    """Open API 자격증명이 없어도 제목 최적화는 정상 동작(부가 레이어, 네트워크 무관)."""
    g = _cfg()
    monkeypatch.setattr(g, "has_open_api_credentials", lambda: False)
    monkeypatch.setattr(g, "use_open_api", lambda: False)
    topic = _foodie_topic()
    titles = optimize_titles("성수 카페", ["브런치"], topic, {}, g)
    assert titles
    assert "성수 카페" in titles[0].title
