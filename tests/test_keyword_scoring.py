"""키워드 점수화 회귀 테스트(keyword_scoring).

수정한 알려진 버그들을 고정한다:
  1) 맛집(성수, 데이트 근거 O / 주차 근거 X)의 PRIMARY 는 핵심어('성수 맛집')여야 하고,
     '성수 비오는날' 같은 시즌 롱테일이 PRIMARY 가 되면 안 된다.
  2) '주차' 를 주장하는데 has_parking_evidence 가 False 면 mismatch_penalty>0.
  3) '돌아기' 키워드는 bare '아기' 부분일치로 kid 보너스를 받으면 안 된다.
  4) BIG_HEAD_KEYWORDS 의 빅키워드는 competition_penalty>0.
그리고 select_primary_and_secondary 가 정확히 하나의 primary 와
근접 중복을 제외한 secondary 들을 돌려주는지 검증한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blog_automation.seo import constants  # noqa: E402
from blog_automation.seo.config import load_growth_config  # noqa: E402
from blog_automation.seo.keyword_candidate_generator import (  # noqa: E402
    generate_candidates,
)
from blog_automation.seo.keyword_scoring import (  # noqa: E402
    _content_fit_score,
    _competition_penalty,
    _is_near_duplicate,
    score_keywords,
    select_primary_and_secondary,
)
from blog_automation.seo.models import (  # noqa: E402
    KeywordCandidates,
    TopicExtraction,
)


def _growth_cfg(monkeypatch):
    """네트워크/credential 무관하게 결정론적으로 만든 GrowthConfig.

    Open API credential 존재 여부는 본 모듈 점수화에 쓰이지 않지만,
    .env 값에 의존하지 않도록 인스턴스를 직접 패치해 둔다.
    """
    g = load_growth_config()
    monkeypatch.setattr(g, "has_open_api_credentials", lambda: False)
    monkeypatch.setattr(g, "use_open_api", lambda: False)
    return g


def _matjip_seongsu_topic():
    """성수 맛집: 데이트 분위기 근거 O, 주차 근거 X."""
    return TopicExtraction(
        input_folder="seongsu",
        category="맛집",
        location="성수",
        has_date_mood=True,
        has_parking_evidence=False,
    )


# ─────────────────────────── 1) PRIMARY = 핵심어 ───────────────────────────

def test_primary_is_core_keyword_not_seasonal_longtail(monkeypatch):
    """성수 맛집 토픽의 PRIMARY 는 '성수 맛집'(핵심)이어야 하고
    '성수 비오는날' 같은 시즌 롱테일이 PRIMARY 가 되면 안 된다.

    회귀 포인트: 시즌 롱테일이 raw final_score 가 더 높아도, role 기반 선정으로
    핵심 후보가 PRIMARY 슬롯을 차지한다.
    """
    g = _growth_cfg(monkeypatch)
    topic = _matjip_seongsu_topic()

    cands = generate_candidates(topic, g)
    # 후보 생성기가 '성수 맛집' 을 핵심(primary 후보)으로, '성수 비오는날' 을 롱테일로 분류해야 한다.
    assert "성수 맛집" in cands.primary_candidates
    assert "성수 비오는날" not in cands.primary_candidates
    assert "성수 비오는날" in cands.secondary_candidates

    scored = score_keywords(cands, {}, topic, {}, g)
    primary, secondaries = select_primary_and_secondary(scored, g)

    assert primary is not None
    assert primary.keyword == "성수 맛집"
    # 시즌 롱테일은 절대 PRIMARY 가 아니다.
    assert "비오는날" not in primary.keyword


def test_primary_wins_even_when_longtail_scores_higher(monkeypatch):
    """핵심어의 raw final_score 가 시즌 롱테일보다 낮아도 PRIMARY 로 뽑혀야 한다.

    KeywordCandidates 를 직접 만들어 role 기반 선정을 직접 검증한다.
    """
    g = _growth_cfg(monkeypatch)
    topic = _matjip_seongsu_topic()

    cands = KeywordCandidates(
        primary_candidates=["성수 맛집"],
        secondary_candidates=["성수 데이트 맛집", "성수 비오는날"],
    )
    scored = score_keywords(cands, {}, topic, {}, g)
    by_kw = {s.keyword: s for s in scored}

    # '성수 데이트 맛집'(데이트 근거 O) 가 핵심어보다 raw 점수가 높다 — 그럼에도 PRIMARY 는 핵심어.
    assert by_kw["성수 데이트 맛집"].final_score >= by_kw["성수 맛집"].final_score

    primary, _ = select_primary_and_secondary(scored, g)
    assert primary.keyword == "성수 맛집"


# ─────────────────────────── 2) 주차 mismatch ───────────────────────────

def test_parking_claim_without_evidence_gets_mismatch_penalty(monkeypatch):
    """has_parking_evidence False 인데 '주차' 를 주장하면 mismatch_penalty>0."""
    g = _growth_cfg(monkeypatch)
    topic = _matjip_seongsu_topic()  # has_parking_evidence=False

    cands = KeywordCandidates(
        primary_candidates=["성수 맛집"],
        secondary_candidates=["성수 주차 맛집"],
    )
    scored = score_keywords(cands, {}, topic, {}, g)
    parking = next(s for s in scored if s.keyword == "성수 주차 맛집")
    core = next(s for s in scored if s.keyword == "성수 맛집")

    assert parking.mismatch_penalty > 0
    # 근거 없는 주차 주장이라 reason 에 불일치 감점이 드러난다.
    assert "불일치" in parking.reason
    # 주차 미주장 핵심어는 mismatch 감점이 없다.
    assert core.mismatch_penalty == 0


# ─────────────────────────── 3) '돌아기' phantom kid 보너스 없음 ───────────────────────────

def test_dol_baby_keyword_no_phantom_kid_bonus(monkeypatch):
    """'돌아기' 가 bare '아기' 부분일치로 kid content_fit 보너스를 받으면 안 된다.

    육아템(is_product_review=True) 토픽에서 '돌아기 내돈내산' 의 content_fit 은
    kid 보너스 없는 일반 제품 키워드('흡착식판 후기')와 같아야 한다.
    """
    # core hit 영향 제거를 위해 product_type/age_group/brand/location 미설정.
    topic = TopicExtraction(
        input_folder="yukatem",
        category="육아템",
        is_product_review=True,
    )

    product_review_fit = _content_fit_score("흡착식판 후기", topic)
    dol_baby_fit = _content_fit_score("돌아기 내돈내산", topic)

    # 둘 다 제품 모디파이어 1개 + core hit 0 → 동일 점수여야 한다(phantom kid 가산 없음).
    assert dol_baby_fit == product_review_fit
    # 보너스가 한 번만 들어간 형태(50 + 18)인지 확인 — kid(+18) 이 추가로 안 붙었다.
    assert dol_baby_fit == 68.0


def test_kid_modifier_real_match_does_get_bonus(monkeypatch):
    """대조군: 진짜 kid 모디파이어('아기랑')는 has_kid_context 근거가 있으면 가산된다.

    이로써 위 테스트의 동치가 '보너스 자체를 못 줘서'가 아니라
    '돌아기에 phantom 매치가 없어서' 임을 분리 검증한다.
    """
    kid_topic = TopicExtraction(
        input_folder="kid",
        category="맛집",
        location="성수",
        has_kid_context=True,
    )
    # '아기랑'(진짜 kid 의도) → 근거 O 면 +18 가산.
    with_kid = _content_fit_score("성수 아기랑 맛집", kid_topic)
    # '돌아기'(phantom) → kid 가산 없음.
    dol_baby = _content_fit_score("성수 돌아기 맛집", kid_topic)
    assert with_kid > dol_baby


# ─────────────────────────── 4) 빅키워드 competition_penalty ───────────────────────────

def test_big_head_keyword_gets_competition_penalty(monkeypatch):
    """constants.BIG_HEAD_KEYWORDS 의 빅키워드는 competition_penalty>0."""
    g = _growth_cfg(monkeypatch)
    topic = _matjip_seongsu_topic()

    big_head = "서울 맛집"
    assert big_head in constants.BIG_HEAD_KEYWORDS  # 전제 고정

    # 함수 단위로 감점 발생 확인(research 없음 → 빅키워드 자체로 감점).
    assert _competition_penalty(big_head, None) > 0

    cands = KeywordCandidates(
        primary_candidates=["성수 맛집"],
        secondary_candidates=[big_head],
    )
    scored = score_keywords(cands, {}, topic, {}, g)
    bh = next(s for s in scored if s.keyword == big_head)
    assert bh.competition_penalty > 0


# ─────────────────────────── 선정 결과 형태 ───────────────────────────

def test_select_returns_exactly_one_primary_and_dedup_secondaries(monkeypatch):
    """select_primary_and_secondary 는 정확히 하나의 primary 와
    근접 중복을 제외한 secondary 들을 돌려준다.
    """
    g = _growth_cfg(monkeypatch)
    topic = _matjip_seongsu_topic()

    cands = KeywordCandidates(
        primary_candidates=["성수 맛집"],
        # '성수맛집' 은 '성수 맛집' 의 근접 중복(공백만 다름) → secondary 에서 빠져야 한다.
        secondary_candidates=["성수 데이트 맛집", "성수 비오는날", "성수맛집"],
    )
    scored = score_keywords(cands, {}, topic, {}, g)
    primary, secondaries = select_primary_and_secondary(scored, g)

    # 정확히 하나의 primary.
    assert primary is not None
    assert primary.role == "primary"
    primary_count = sum(1 for s in scored if s.role == "primary")
    assert primary_count == 1

    sec_keywords = [s.keyword for s in secondaries]
    # 모든 secondary 는 role 이 'secondary'.
    assert all(s.role == "secondary" for s in secondaries)
    # primary 자신은 secondary 에 없다.
    assert primary.keyword not in sec_keywords
    # 근접 중복('성수맛집')은 제외된다.
    assert "성수맛집" not in sec_keywords
    assert _is_near_duplicate("성수맛집", primary.keyword)
    # 정상 롱테일들은 남아 있다.
    assert "성수 데이트 맛집" in sec_keywords
    # max_selected_secondary_keywords 상한을 넘지 않는다.
    max_sec = int(g.seo.get("max_selected_secondary_keywords", 5))
    assert len(secondaries) <= max_sec


def test_empty_scored_returns_none_and_empty(monkeypatch):
    """채점 결과가 비면 (None, []) 을 돌려준다."""
    g = _growth_cfg(monkeypatch)
    primary, secondaries = select_primary_and_secondary([], g)
    assert primary is None
    assert secondaries == []
