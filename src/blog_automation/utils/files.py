"""파일 IO 헬퍼."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}


def list_images(folder: Path) -> list[Path]:
    """폴더 내 이미지들을 파일명 순으로(보통 촬영 순) 정렬해 반환."""
    return sorted(p for p in folder.glob("*") if p.suffix.lower() in IMAGE_EXTS)
