"""초고/배치도 산출물 스키마.

Claude Code 가 prompts/write_post.md 를 따라 아래 두 파일을 만든다:
  - data/drafts/<job>/post.md      : 본문. 사진 자리는 {{photo: 파일명}} 으로 표시
  - data/drafts/<job>/layout.json  : 아래 LAYOUT_SCHEMA 를 따르는 배치도

publish 단계(naver_editor)가 layout.json 을 그대로 파싱하므로 형식을 정확히 지킬 것.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils.files import read_json, resolve_images

# layout.json 예시/스키마(설명용)
LAYOUT_SCHEMA: dict[str, Any] = {
    "title": "글 제목",
    "persona": "맛집방문",                 # 사용한 페르소나
    "blocks": [                            # 위에서 아래로 순서대로 발행됨
        {"type": "text", "content": "도입부 문단 텍스트..."},
        {"type": "image", "file": "photo_01.jpg", "caption": "외관 사진",
         "group": 1, "align": "center"},   # group 같은 값끼리 연속/그리드 배치
        {"type": "text", "content": "다음 문단..."},
        {"type": "tags", "items": ["맛집", "성수동맛집"]},
    ],
}

VALID_BLOCK_TYPES = {"text", "image", "tags", "heading", "quote"}


def load_layout(drafts_dir: Path, job: str) -> dict[str, Any]:
    return read_json(drafts_dir / job / "layout.json")


def get_image_files(blk: dict) -> list[str]:
    """image 블록에서 파일 목록 반환.
    단독: {"file": "a.jpg"} → ["a.jpg"]
    그룹: {"files": ["a.jpg","b.jpg"]} → ["a.jpg","b.jpg"]
    """
    if "files" in blk:
        return blk["files"]
    if "file" in blk:
        return [blk["file"]]
    return []


def validate_layout(layout: dict[str, Any], photos_dir: Path) -> list[str]:
    """배치도 검증. 문제점 목록을 반환(빈 리스트면 OK)."""
    errors: list[str] = []
    if "blocks" not in layout or not isinstance(layout["blocks"], list):
        return ["'blocks' 배열이 없습니다."]
    for i, blk in enumerate(layout["blocks"]):
        t = blk.get("type")
        if t not in VALID_BLOCK_TYPES:
            errors.append(f"blocks[{i}]: 알 수 없는 type '{t}'")
        if t == "image":
            files = get_image_files(blk)
            if not files:
                errors.append(f"blocks[{i}]: image 블록에 file/files 없음")
            for f in files:
                matches = resolve_images(photos_dir, f)
                if not matches:
                    errors.append(f"blocks[{i}]: 사진 파일 없음 → {f}")
                elif len(matches) > 1:
                    rels = ", ".join(str(m.relative_to(photos_dir)) for m in matches)
                    errors.append(
                        f"blocks[{i}]: 같은 파일명이 여러 폴더에 있음 → {f} ({rels}). "
                        f"layout.json 에 '<카테고리>/{f}' 처럼 폴더를 포함해 지정하세요.")
        if t == "text" and not blk.get("content"):
            errors.append(f"blocks[{i}]: text 블록이 비어 있음")
    return errors
