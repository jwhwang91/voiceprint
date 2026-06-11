"""수집 데이터 모델."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class CollectedPost:
    """수집된 과거 글 1개. 페르소나 분석(Claude Code)의 입력이 된다."""
    post_id: str
    url: str
    title: str
    body_text: str                       # 본문 평문
    body_blocks: list[dict] = field(default_factory=list)  # 문단/이미지 순서 보존(배치 패턴 학습용)
    image_urls: list[str] = field(default_factory=list)
    image_files: list[str] = field(default_factory=list)    # 로컬 저장 경로
    tags: list[str] = field(default_factory=list)
    category_guess: str = ""              # settings.yaml 키워드 기반 1차 분류(참고용)
    posted_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
