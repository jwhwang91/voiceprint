"""페르소나 분석 보조.

실제 '분석'은 Claude Code 가 prompts/analyze_persona.md 를 따라 수행한다.
이 모듈은 Claude Code 가 읽기 쉽도록 수집 글을 종류별로 묶은 '분석 번들'을 만들어 준다(선택).
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from ..config import Config
from ..logging_setup import get_logger
from ..utils.files import read_json, write_json

log = get_logger()


def build_analysis_bundle(cfg: Config, blog_id: str) -> Path:
    """data/collected/<id>/*.json 을 category_guess 별로 묶어 한 파일로 정리."""
    src = cfg.collected_dir / blog_id
    posts = [read_json(p) for p in src.glob("*.json")]

    grouped: dict[str, list] = defaultdict(list)
    for post in posts:
        grouped[post.get("category_guess") or "미분류"].append({
            "title": post["title"],
            "body_text": post["body_text"],
            "image_count": len(post.get("image_urls", [])),
            "tags": post.get("tags", []),
        })

    out = src / "_analysis_bundle.json"
    write_json(out, {"blog_id": blog_id, "by_category": grouped})
    log.info("분석 번들 생성: %s (종류 %d개)", out, len(grouped))
    return out
