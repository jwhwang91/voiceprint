"""tag_optimizer.optimize_tags 테스트 — SEO 부가 레이어(맛집 토픽 기준)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blog_automation.seo import constants  # noqa: E402
from blog_automation.seo.config import load_growth_config  # noqa: E402
from blog_automation.seo.models import TopicExtraction  # noqa: E402
from blog_automation.seo.tag_optimizer import optimize_tags, _compact  # noqa: E402


def _topic():
    return TopicExtraction(
        input_folder="job1",
        category="맛집",
        detected_topics=["성수동 데이트", "파스타", "분위기 좋은"],
        location="성수동",
        content_type="방문 후기",
    )


def _call():
    """결정적 입력으로 optimize_tags 를 호출."""
    g = load_growth_config()
    topic = _topic()
    primary = "성수동 데이트 맛집"
    secondaries = [
        "성수동 파스타 맛집",
        "맛집",                # 빅키워드 단독 → avoid 로 가야 함
        "서울맛집",            # DEFAULT_AVOID_TAGS[맛집] → avoid
        "성수동 분위기 좋은 맛집",
        "성수동 데이트",
    ]
    return optimize_tags(primary, secondaries, topic, g), g


def test_selected_tags_length_within_bounds():
    result, g = _call()
    selected = result["selected_tags"]
    max_tags = int(g.seo["max_tags"])
    assert 1 <= len(selected) <= max_tags


def test_selected_tags_are_compacted_no_internal_spaces():
    result, _ = _call()
    selected = result["selected_tags"]
    assert selected, "selected_tags 가 비어 있으면 안 됨"
    for tag in selected:
        # 컴팩트 태그는 내부 공백(스페이스/탭/개행)이 없어야 한다.
        assert tag == "".join(tag.split())
        assert " " not in tag
        assert "\t" not in tag
        assert "\n" not in tag


def test_big_head_keyword_excluded_and_in_avoid():
    result, _ = _call()
    selected = result["selected_tags"]
    avoid = result["avoid_tags"]
    big = _compact("맛집")  # 빅키워드, 컴팩트형
    assert big not in selected
    assert big in avoid


def test_default_avoid_tags_for_category_appear_in_avoid():
    result, _ = _call()
    avoid = result["avoid_tags"]
    for raw in constants.DEFAULT_AVOID_TAGS["맛집"]:
        assert _compact(raw) in avoid


def test_deterministic_across_two_calls():
    (r1, _), (r2, _) = _call(), _call()
    assert r1 == r2
    assert r1["selected_tags"] == r2["selected_tags"]
    assert r1["avoid_tags"] == r2["avoid_tags"]


def test_selected_excludes_all_avoid_compact_keywords():
    result, _ = _call()
    selected = result["selected_tags"]
    avoid = set(result["avoid_tags"])
    # selected 와 avoid 는 서로 겹치지 않아야 한다.
    assert not (set(selected) & avoid)
