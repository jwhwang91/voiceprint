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
    """폴더 내 이미지들을 파일명 순으로(보통 촬영 순) 정렬해 반환.

    카테고리 하위폴더(photos/메뉴/…)까지 재귀 검색한다. 수동 ZIP 다운로드 시
    사진이 photos/<카테고리>/ 안에 들어오기 때문.
    """
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_EXTS)


def resolve_images(photos_dir: Path, name: str) -> list[Path]:
    """layout.json의 file 값을 photos/ 아래에서 해석한다(카테고리 하위폴더 지원).

    수동 ZIP 다운로드 시 사진은 photos/<카테고리>/<파일> 형태로 들어온다.
      1) photos_dir/name 직접 경로 우선 — 평탄 구조와 "카테고리/파일" 명시를 모두 지원.
      2) 없으면 파일명(basename)으로 재귀 검색.
    반환: 매치된 경로 목록(0=없음, 1=정상, 2+=여러 폴더에 동일 파일명 → 모호).
    """
    direct = photos_dir / name
    if direct.is_file():
        return [direct]
    base = Path(name).name
    return sorted(p for p in photos_dir.rglob(base) if p.is_file())
