"""배치도 검증 로직 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blog_automation.content.schema import validate_layout  # noqa: E402


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
