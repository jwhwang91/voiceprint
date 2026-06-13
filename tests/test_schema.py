"""배치도 검증 로직 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blog_automation.content.schema import (  # noqa: E402
    validate_layout,
    representative_block_index,
    first_image_block_index,
    representative_warnings,
)


def test_validate_layout_detects_missing_image(tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    layout = {"blocks": [
        {"type": "text", "content": "안녕하세요"},
        {"type": "image", "file": "nope.jpg"},
    ]}
    errors = validate_layout(layout, photos)
    assert any("nope.jpg" in e for e in errors)


def test_validate_layout_ok(tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "a.jpg").write_bytes(b"x")
    layout = {"blocks": [
        {"type": "text", "content": "본문"},
        {"type": "image", "file": "a.jpg", "caption": "사진"},
        {"type": "tags", "items": ["맛집"]},
    ]}
    assert validate_layout(layout, photos) == []


# --- 대표 이미지(썸네일) 헬퍼 ---

def test_representative_picks_flagged_single_block():
    layout = {"blocks": [
        {"type": "text", "content": "도입"},
        {"type": "image", "file": "hero.jpg", "representative": True},
        {"type": "image", "files": ["b.jpg", "c.jpg"]},
    ]}
    assert representative_block_index(layout) == 1
    assert first_image_block_index(layout) == 1
    assert representative_warnings(layout) == []  # 대표=첫 이미지 → 경고 없음


def test_representative_ignores_group_flag_and_warns():
    layout = {"blocks": [
        {"type": "image", "files": ["a.jpg", "b.jpg"], "representative": True},
        {"type": "text", "content": "x"},
    ]}
    # 그룹엔 대표를 못 단다 → 단독 대표 없음
    assert representative_block_index(layout) is None
    warns = representative_warnings(layout)
    assert any("그룹" in w for w in warns)
    assert any("지정 없음" in w for w in warns)


def test_representative_multiple_singles_uses_first_and_warns():
    layout = {"blocks": [
        {"type": "image", "file": "a.jpg", "representative": True},
        {"type": "image", "file": "b.jpg", "representative": True},
    ]}
    assert representative_block_index(layout) == 0
    assert any("2개" in w for w in representative_warnings(layout))


def test_representative_not_first_image_warns():
    layout = {"blocks": [
        {"type": "image", "files": ["g1.jpg", "g2.jpg"]},   # 첫 이미지(그룹)
        {"type": "image", "file": "hero.jpg", "representative": True},  # 대표는 뒤
    ]}
    assert representative_block_index(layout) == 1
    assert first_image_block_index(layout) == 0
    assert any("첫 이미지" in w for w in representative_warnings(layout))


def test_representative_none_flagged_warns_when_images_exist():
    layout = {"blocks": [
        {"type": "image", "file": "a.jpg"},
        {"type": "text", "content": "x"},
    ]}
    assert representative_block_index(layout) is None
    assert any("지정 없음" in w for w in representative_warnings(layout))


def test_representative_no_images_no_warning():
    layout = {"blocks": [{"type": "text", "content": "글만 있음"}]}
    assert representative_block_index(layout) is None
    assert first_image_block_index(layout) is None
    assert representative_warnings(layout) == []
