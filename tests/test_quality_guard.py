"""quality_guard.check_quality 기계적 품질 점검 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blog_automation.seo.config import load_growth_config  # noqa: E402
from blog_automation.seo.models import QualityResult, SeoBrief  # noqa: E402
from blog_automation.seo.quality_guard import check_quality  # noqa: E402

PRIMARY = "흡착식판 후기"
TITLE = "흡착식판 후기 장단점 정리"


def _brief(**over):
    kw = dict(
        brief_id="b1",
        primary_keyword=PRIMARY,
        recommended_title=TITLE,
        selected_tags=["흡착식판", "육아템", "이유식"],
    )
    kw.update(over)
    return SeoBrief(**kw)


def _good_body():
    """공백 제외 1500자 이상, 1차 키워드는 첫 문단/제목에만 등장(과다반복 아님)."""
    # 첫 문단: 1차 키워드 1회 포함.
    first = (
        f"오늘은 {PRIMARY} 를 남겨봅니다. 아이가 이유식을 시작하면서 새로 들인 식판을 "
        "한 달 넘게 써보고 솔직하게 적어봅니다. 처음엔 반신반의했는데 생각보다 만족스러워서 "
        "장단점을 꼼꼼히 정리해 봤어요.\n"
    )
    # 나머지 문단: 키워드 없이 길게 채운다(과다 반복 방지).
    filler = (
        "테이블에 딱 붙어서 아이가 아무리 잡아당겨도 떨어지지 않는 점이 가장 좋았습니다. "
        "실리콘 재질이라 세척도 간편하고 식기세척기에도 넣을 수 있어서 손이 덜 갔어요. "
        "칸이 넉넉하게 나뉘어 있어서 밥과 반찬을 따로 담기 좋았고 색감도 자연스러워 보기 좋았습니다. "
        "다만 처음 사용할 때 특유의 냄새가 조금 났는데 몇 번 삶고 나니 사라졌습니다. "
        "무게가 가벼운 편이라 보관할 때도 부담이 없었고 외출할 때 챙기기도 편했어요. "
    )
    body = first + (filler * 10)
    return body


def test_good_post_passes():
    g = load_growth_config()
    body = _good_body()
    layout = {
        "title": TITLE,
        "blocks": [
            {"type": "text", "content": body},
            {"type": "image", "file": "a.jpg"},
            {"type": "tags", "items": ["흡착식판"]},
        ],
    }
    res = check_quality(post_md=body, layout=layout, brief=_brief(), growth_cfg=g)
    assert isinstance(res, QualityResult)
    assert res.passed is True, res.issues
    assert isinstance(res.score, (int, float))
    assert 0 <= res.score <= 100


def test_score_is_number_in_range():
    g = load_growth_config()
    body = _good_body()
    res = check_quality(post_md=body, layout=None, brief=_brief(), growth_cfg=g)
    assert isinstance(res.score, (int, float))
    assert 0.0 <= float(res.score) <= 100.0


def test_primary_keyword_over_repeated_flagged_and_fails():
    """(a) 1차 키워드를 max_primary_keyword_repeats 보다 많이 반복하면 이슈 + 통과 X.

    과다 반복 감점만으로 통과선 아래로 떨어지도록 통과 임계값을 살짝 올려둔다
    (현재 코드의 단일 감점=10점 한도를 건드리지 않고 결정적으로 검증).
    """
    g = load_growth_config()
    g.raw["quality_guard"]["min_score_to_pass"] = 95
    max_rep = int(g.quality_guard.get("max_primary_keyword_repeats", 4))
    # 첫 문단 1회 + 본문 곳곳에 max_rep 회 더 → 총 max_rep+1 회(> 한도).
    body = _good_body()
    body += ("\n" + f"{PRIMARY} 정말 추천합니다. ") * max_rep
    res = check_quality(post_md=body, layout=None, brief=_brief(), growth_cfg=g)
    assert any(PRIMARY in iss and "반복" in iss for iss in res.issues), res.issues
    assert res.passed is False


def test_body_too_short_flagged():
    """(b) 본문이 min_body_length_chars 보다 짧으면 이슈 플래그."""
    g = load_growth_config()
    short = f"{PRIMARY} 짧은 글입니다. 정말 좋아요."
    layout = {"title": TITLE, "blocks": [{"type": "text", "content": short}]}
    res = check_quality(post_md=short, layout=layout, brief=_brief(), growth_cfg=g)
    assert any("짧" in iss for iss in res.issues), res.issues
    assert res.passed is False


def test_dash_or_middot_flagged():
    """(c) 대시/가운뎃점(— · --)이 있으면 이슈 플래그."""
    g = load_growth_config()
    for token in ("—", "·", "--"):
        body = _good_body() + f"\n구분 기호 {token} 가 들어간 줄입니다."
        res = check_quality(post_md=body, layout=None, brief=_brief(), growth_cfg=g)
        assert any("가로선" in iss or "기호" in iss for iss in res.issues), (token, res.issues)


def test_three_consecutive_text_blocks_flagged():
    """(d) text 블록 3개 이상 연속이면 이슈 플래그."""
    g = load_growth_config()
    body = _good_body()
    layout = {
        "title": TITLE,
        "blocks": [
            {"type": "text", "content": body},
            {"type": "text", "content": "두 번째 텍스트 블록입니다."},
            {"type": "text", "content": "세 번째 텍스트 블록입니다."},
        ],
    }
    res = check_quality(post_md=body, layout=layout, brief=_brief(), growth_cfg=g)
    assert any("연속" in iss for iss in res.issues), res.issues


def test_primary_missing_from_title_critical_and_fails():
    """(e) 1차 키워드가 제목에 없으면 치명적 → 통과 X."""
    g = load_growth_config()
    body = _good_body()
    brief = _brief(recommended_title="그냥 육아템 정리 글이에요")
    res = check_quality(post_md=body, layout=None, brief=brief, growth_cfg=g)
    assert any("제목" in iss and PRIMARY in iss for iss in res.issues), res.issues
    assert res.passed is False
