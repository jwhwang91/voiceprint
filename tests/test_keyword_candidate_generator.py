"""keyword_candidate_generator 후보 생성 테스트(결정적, 네트워크 없음)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blog_automation.seo.config import load_growth_config  # noqa: E402
from blog_automation.seo.keyword_candidate_generator import (  # noqa: E402
    generate_candidates,
)
from blog_automation.seo.models import (  # noqa: E402
    KeywordCandidates,
    TopicExtraction,
)


def _all_candidates(cand: KeywordCandidates) -> list[str]:
    return (
        list(cand.primary_candidates)
        + list(cand.secondary_candidates)
        + list(cand.tag_candidates)
    )


def test_matjip_location_situation_longtails():
    """맛집: 지역+상황 롱테일이 secondary, '성수 맛집' 은 primary 에."""
    g = load_growth_config()
    topic = TopicExtraction(
        input_folder="job1",
        category="맛집",
        location="성수",
        content_type="방문 후기",
        has_date_mood=True,
        has_parking_evidence=True,
    )
    cand = generate_candidates(topic, g)

    # '성수 맛집' 은 2단어 → primary
    assert "성수 맛집" in cand.primary_candidates

    # 지역+상황 롱테일은 secondary
    assert "성수 데이트 맛집" in cand.secondary_candidates
    assert "성수 주차 편한 맛집" in cand.secondary_candidates


def test_yukatem_product_intent_in_primary():
    """육아템: 제품명+의도(후기/내돈내산/장단점)가 primary 에 포함."""
    g = load_growth_config()
    topic = TopicExtraction(
        input_folder="job2",
        category="육아템",
        product_type="흡착식판",
        content_type="제품 리뷰",
        is_product_review=True,
    )
    cand = generate_candidates(topic, g)

    assert "흡착식판 후기" in cand.primary_candidates
    assert "흡착식판 내돈내산" in cand.primary_candidates
    assert "흡착식판 장단점" in cand.primary_candidates


def test_no_unfilled_placeholder_in_any_candidate():
    """어떤 후보(primary/secondary/tag)에도 미치환 '{' 가 없어야 한다."""
    g = load_growth_config()

    matjip = TopicExtraction(
        input_folder="job1",
        category="맛집",
        location="성수",
        content_type="방문 후기",
        has_date_mood=True,
        has_parking_evidence=True,
    )
    yukatem = TopicExtraction(
        input_folder="job2",
        category="육아템",
        product_type="흡착식판",
        content_type="제품 리뷰",
        is_product_review=True,
    )

    for topic in (matjip, yukatem):
        cand = generate_candidates(topic, g)
        for kw in _all_candidates(cand):
            assert "{" not in kw, f"미치환 플레이스홀더 발견: {kw!r}"
            assert "}" not in kw, f"미치환 플레이스홀더 발견: {kw!r}"


def test_total_candidate_count_capped():
    """primary+secondary 합산이 max_keyword_candidates 이하."""
    g = load_growth_config()
    max_total = int(g.seo["max_keyword_candidates"])

    topic = TopicExtraction(
        input_folder="job1",
        category="맛집",
        location="성수",
        content_type="방문 후기",
        has_date_mood=True,
        has_parking_evidence=True,
    )
    cand = generate_candidates(topic, g)

    assert len(cand.primary_candidates) + len(cand.secondary_candidates) <= max_total


def test_yukatem_core_gets_no_place_modifier():
    """육아템 제품 핵심어에는 장소 모디파이어가 붙지 않는다('흡착식판 비오는날' 금지)."""
    g = load_growth_config()
    topic = TopicExtraction(
        input_folder="job2",
        category="육아템",
        product_type="흡착식판",
        content_type="제품 리뷰",
        is_product_review=True,
    )
    cand = generate_candidates(topic, g)

    all_kw = _all_candidates(cand)
    for nonsense in ("흡착식판 비오는날", "흡착식판비오는날", "흡착식판 데이트", "흡착식판 주차"):
        assert nonsense not in all_kw, f"제품형에 장소 모디파이어가 결합됨: {nonsense!r}"
