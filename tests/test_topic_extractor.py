"""topic_extractor 의 카테고리/지역/제품/플래그 추출 테스트.

입력 파일(photo_tags.json / description.txt)을 tmp_path 로 위조해
extract_topics 의 휴리스틱 결과를 검증한다. 네트워크/실 .env 의존 없음.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blog_automation.seo.config import load_growth_config  # noqa: E402
from blog_automation.seo.models import TopicExtraction  # noqa: E402
from blog_automation.seo.topic_extractor import extract_topics  # noqa: E402


# ───────────────────────── 헬퍼: 입력 위조 ─────────────────────────

def _make_job(tmp_path, job, *, photos=None, memo=None):
    """input_dir/<job>/description.txt 와 drafts_dir/<job>/photo_tags.json 를 만든다.

    반환: (input_dir, drafts_dir) — extract_topics 에 그대로 넘긴다.
    photos=None 또는 memo=None 이면 해당 파일을 만들지 않는다(누락 모드).
    """
    input_dir = tmp_path / "input"
    drafts_dir = tmp_path / "drafts"

    if memo is not None:
        memo_path = input_dir / job / "description.txt"
        memo_path.parent.mkdir(parents=True, exist_ok=True)
        memo_path.write_text(memo, encoding="utf-8")

    if photos is not None:
        tags_path = drafts_dir / job / "photo_tags.json"
        tags_path.parent.mkdir(parents=True, exist_ok=True)
        tags_path.write_text(
            json.dumps({"photos": photos}, ensure_ascii=False),
            encoding="utf-8",
        )

    return input_dir, drafts_dir


# ───────────────────────── Case A: 맛집(방문형) ─────────────────────────

def test_case_a_restaurant(tmp_path):
    """Case A 맛집: category=='맛집', location=='성수', date/parking 플래그."""
    g = load_growth_config()
    job = "0624_pasta"
    photos = [
        {"category": "외관", "subject": "와인바 입구 간판"},
        {"category": "내부", "subject": "테이블과 조명"},
        {"category": "메뉴음식", "subject": "파스타 한 접시"},
        {"category": "디테일", "subject": "건물 앞 주차 공간"},
    ]
    memo = "성수동 데이트로 다녀온 파스타 와인바, 주차 가능"
    input_dir, drafts_dir = _make_job(tmp_path, job, photos=photos, memo=memo)

    topic = extract_topics(
        g, job=job, input_dir=input_dir, drafts_dir=drafts_dir
    )

    assert isinstance(topic, TopicExtraction)
    assert topic.category == "맛집"
    assert topic.location == "성수"
    assert topic.has_date_mood is True
    assert topic.has_parking_evidence is True
    # 맛집은 제품리뷰가 아니며, 방문 후기 content_type 이어야 한다.
    assert topic.is_product_review is False
    assert topic.content_type == "방문 후기"


def test_case_a_parking_from_subject_only(tmp_path):
    """주차 근거가 메모가 아닌 subject 에만 있어도 잡혀야 한다."""
    g = load_growth_config()
    job = "0624_pasta2"
    photos = [
        {"category": "메뉴음식", "subject": "파스타"},
        {"category": "외관", "subject": "발렛 주차 안내판"},
    ]
    memo = "성수 데이트 와인바 방문"
    input_dir, drafts_dir = _make_job(tmp_path, job, photos=photos, memo=memo)

    topic = extract_topics(g, job=job, input_dir=input_dir, drafts_dir=drafts_dir)

    assert topic.category == "맛집"
    assert topic.has_parking_evidence is True


# ───────────────────────── Case B: 육아템(제품 리뷰) ─────────────────────────

def test_case_b_baby_product(tmp_path):
    """Case B 육아템: 돌아기 흡착식판 내돈내산, 브랜드 마더케이."""
    g = load_growth_config()
    job = "0624_plate"
    memo = "돌아기 흡착식판 내돈내산 후기, 브랜드는 마더케이"
    # 사진 태그는 비전 단독에 가깝게 최소만(제품 컷).
    photos = [
        {"category": "제품", "subject": "흡착식판 단독 컷"},
        {"category": "인물상황", "subject": "아기가 식판으로 식사"},
    ]
    input_dir, drafts_dir = _make_job(tmp_path, job, photos=photos, memo=memo)

    topic = extract_topics(g, job=job, input_dir=input_dir, drafts_dir=drafts_dir)

    assert topic.category == "육아템"          # '육아' 가 아니라 '육아템'
    assert topic.category != "육아"
    assert topic.is_product_review is True
    assert topic.product_type == "흡착식판"
    assert topic.brand == "마더케이"
    assert topic.age_group is not None
    assert "돌아기" in topic.age_group
    # 육아템은 제품 리뷰 content_type.
    assert topic.content_type == "제품 리뷰"
    # 아이 맥락 플래그도 켜져야 한다(나이대/육아템 카테고리).
    assert topic.has_kid_context is True


def test_case_b_no_photos_memo_only(tmp_path):
    """photo_tags 가 없어도(메모 단독) 제품/브랜드를 메모에서 뽑는다."""
    g = load_growth_config()
    job = "0624_plate_memoonly"
    memo = "돌아기 흡착식판 내돈내산 후기, 브랜드는 마더케이"
    input_dir, drafts_dir = _make_job(tmp_path, job, photos=None, memo=memo)

    topic = extract_topics(g, job=job, input_dir=input_dir, drafts_dir=drafts_dir)

    assert topic.category == "육아템"
    assert topic.product_type == "흡착식판"
    assert topic.brand == "마더케이"
    # photo_tags 누락 → extra.has_memo True, photo_count 0.
    assert topic.extra["has_memo"] is True
    assert topic.extra["photo_count"] == 0


# ───────────────────────── Case C: 전부 누락(graceful) ─────────────────────────

def test_case_c_all_missing(tmp_path):
    """존재하지 않는 job — 어떤 입력 파일도 없을 때 죽지 않고 기본값."""
    g = load_growth_config()
    job = "does_not_exist"
    # 어떤 파일도 만들지 않는다(input/drafts 디렉터리 자체가 비어 있거나 없음).
    input_dir = tmp_path / "input"
    drafts_dir = tmp_path / "drafts"

    topic = extract_topics(g, job=job, input_dir=input_dir, drafts_dir=drafts_dir)

    assert isinstance(topic, TopicExtraction)
    assert topic.input_folder == job
    assert topic.category == "기타"
    # 날조 금지: 근거 없는 필드는 비어 있어야 한다.
    assert topic.location is None
    assert topic.product_type is None
    assert topic.brand is None
    assert topic.age_group is None
    assert topic.is_product_review is False
    assert topic.has_parking_evidence is False
    assert topic.has_date_mood is False
    assert topic.extra["photo_count"] == 0
    assert topic.extra["has_memo"] is False
