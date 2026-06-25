"""SEO 브리프 조립 + 마크다운 렌더링 테스트 (additive SEO layer)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blog_automation.seo.models import (  # noqa: E402
    ScoredKeyword,
    TitleCandidate,
    TopicExtraction,
)
from blog_automation.seo.seo_brief_generator import (  # noqa: E402
    assemble_brief,
    render_brief_md,
    render_report_md,
)


# ───────────────────────── 입력 빌더 ─────────────────────────

def _product_topic() -> TopicExtraction:
    """육아템(제품 리뷰) 토픽."""
    return TopicExtraction(
        input_folder="data/input/job-baby-001",
        category="육아템",
        detected_topics=["아기 손수건", "육아템 추천"],
        product_type="손수건",
        brand="베베앙",
        age_group="신생아",
        content_type="제품 리뷰",
        target_intents=["실사용 후기 확인", "장단점 비교"],
        is_product_review=True,
        has_kid_context=True,
    )


def _matjip_topic() -> TopicExtraction:
    """맛집(비제품) 토픽."""
    return TopicExtraction(
        input_folder="data/input/job-matjip-002",
        category="맛집",
        detected_topics=["강남 파스타", "데이트 맛집"],
        location="강남",
        content_type="방문 후기",
        target_intents=["메뉴/가격 확인", "방문 후기 확인"],
        is_product_review=False,
        has_date_mood=True,
    )


def _scored() -> list[ScoredKeyword]:
    return [
        ScoredKeyword(
            keyword="아기 손수건 추천",
            role="primary",
            final_score=82.5,
            search_demand_score=70.0,
            opportunity_score=65.0,
            my_blog_fit_score=80.0,
            content_fit_score=90.0,
            seasonality_score=10.0,
            competition_penalty=5.0,
            mismatch_penalty=0.0,
            reason="검색 수요 양호, 콘텐츠 적합도 높음",
        ),
        ScoredKeyword(
            keyword="신생아 손수건",
            role="secondary",
            final_score=61.0,
            search_demand_score=55.0,
            opportunity_score=50.0,
            reason="보조 키워드",
        ),
        ScoredKeyword(
            keyword="육아템",
            role="secondary",
            final_score=40.0,
            search_demand_score=80.0,
            competition_penalty=45.0,
            mismatch_penalty=0.0,
            reason="경쟁 과열",
        ),
    ]


def _titles() -> list[TitleCandidate]:
    return [
        TitleCandidate(
            title="신생아 아기 손수건 추천 베베앙 실사용 후기",
            score=88.0,
            reason="primary 키워드 + 브랜드 포함",
        ),
        TitleCandidate(
            title="아기 손수건 추천 솔직 장단점",
            score=80.0,
            reason="장단점 강조",
        ),
    ]


def _tag_result() -> dict:
    return {
        "selected_tags": ["아기손수건", "육아템추천", "신생아준비물", "베베앙"],
        "avoid_tags": ["광고"],
    }


def _assemble_product():
    topic = _product_topic()
    scored = _scored()
    primary = scored[0]
    secondaries = scored[1:]
    brief = assemble_brief(
        brief_id="brief-product-001",
        topic=topic,
        primary=primary,
        secondaries=secondaries,
        title_candidates=_titles(),
        tag_result=_tag_result(),
        scored=scored,
        strategy_reason="실사용 근거가 충분해 제품 리뷰 키워드를 primary 로 채택.",
    )
    return brief, topic, scored


# ───────────────────────── assemble_brief ─────────────────────────

def test_assembled_brief_core_fields():
    brief, topic, scored = _assemble_product()

    assert brief.primary_keyword == "아기 손수건 추천"

    assert isinstance(brief.secondary_keywords, list)
    assert brief.secondary_keywords == ["신생아 손수건", "육아템"]

    assert isinstance(brief.selected_tags, list)
    assert "아기손수건" in brief.selected_tags

    # 추천 제목은 첫 후보의 title 로 채워진다.
    assert brief.recommended_title == "신생아 아기 손수건 추천 베베앙 실사용 후기"

    # 대안 제목 = 나머지 후보들.
    assert len(brief.title_alternatives) == 1
    assert brief.title_alternatives[0]["title"] == "아기 손수건 추천 솔직 장단점"

    # keyword_scores 는 비어 있지 않다 (dict 리스트).
    assert brief.keyword_scores
    assert all(isinstance(sk, dict) for sk in brief.keyword_scores)
    assert brief.keyword_scores[0]["keyword"] == "아기 손수건 추천"


def test_assembled_brief_avoid_keywords_from_penalty_and_tags():
    brief, topic, scored = _assemble_product()
    # 경쟁 감점 45 >= 40 인 '육아템' + avoid_tags '광고' 가 회피로 들어간다.
    assert "육아템" in brief.avoid_keywords
    assert "광고" in brief.avoid_keywords


def test_assembled_brief_seo_brief_md_populated():
    brief, topic, scored = _assemble_product()
    # assemble_brief 끝에서 render_brief_md 를 채워 넣는다.
    assert brief.seo_brief_md
    assert "# SEO Writing Brief" in brief.seo_brief_md


# ───────────────────────── SEO_BRIEF.md 헤딩 ─────────────────────────

REQUIRED_HEADINGS = [
    "# SEO Writing Brief",
    "## Input Folder",
    "## Category",
    "## Primary Keyword",
    "## Secondary Keywords",
    "## Avoid Keywords",
    "## Recommended Title",
    "## Title Alternatives",
    "## Selected Tags",
    "## Search Intent",
    "## Required Sections",
    "## Keyword Placement Guide",
    "## Tone Guide",
    "## Strategy Reason",
    "## Keyword Scores",
]


def test_brief_md_contains_all_required_headings():
    brief, topic, scored = _assemble_product()
    md = render_brief_md(brief, topic, {})
    for heading in REQUIRED_HEADINGS:
        assert heading in md, f"missing heading: {heading}"


def test_brief_md_shows_primary_and_tags():
    brief, topic, scored = _assemble_product()
    md = render_brief_md(brief, topic, {})
    assert "아기 손수건 추천" in md
    assert "#아기손수건" in md
    # 키워드 점수표 행에 primary 키워드가 들어간다.
    assert "| 아기 손수건 추천 |" in md


# ───────────────────────── SEO_REPORT.md ─────────────────────────

def test_report_md_product_topic_includes_shopping_insight():
    brief, topic, scored = _assemble_product()
    report = render_report_md(brief, topic, {}, {}, scored)
    # 제품형(is_product_review=True) 이면 쇼핑인사이트 섹션이 들어간다.
    assert "쇼핑인사이트" in report


def test_report_md_matjip_topic_omits_shopping_insight():
    topic = _matjip_topic()
    scored = [
        ScoredKeyword(
            keyword="강남 파스타 맛집",
            role="primary",
            final_score=75.0,
            reason="지역+업종 조합",
        ),
    ]
    brief = assemble_brief(
        brief_id="brief-matjip-002",
        topic=topic,
        primary=scored[0],
        secondaries=[],
        title_candidates=[TitleCandidate(title="강남 데이트 파스타 맛집 후기", score=70.0)],
        tag_result={"selected_tags": ["강남맛집", "파스타맛집"]},
        scored=scored,
        strategy_reason="지역 검색 의도가 뚜렷해 지역+업종 키워드 채택.",
    )
    report = render_report_md(brief, topic, {}, {}, scored)
    # 비제품(맛집) 이면 현재 동작상 쇼핑인사이트 섹션 자체가 없다.
    assert "쇼핑인사이트" not in report
    # 산출물 자체는 정상 렌더된다 (다른 섹션은 존재).
    assert "## 검색어 트렌드 분석" in report
    assert "강남 파스타 맛집" in report
