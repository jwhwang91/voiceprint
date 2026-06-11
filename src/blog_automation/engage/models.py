"""자동 답방 데이터 모델."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class TargetPost:
    """답방 대상 글 1개 (댓글 단 사람의 최근 글)."""
    blog_id: str            # 댓글 작성자의 블로그 주소 아이디
    nickname: str           # 댓글에 표시된 닉네임
    log_no: str
    url: str
    title: str
    body_excerpt: str       # 댓글 생성을 위한 본문 발췌
    their_comment: str = ""  # 그 사람이 내 글에 남긴 댓글(맥락 참고용)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CommentPlan:
    """생성된 댓글 1개 (Claude Code 가 채움)."""
    blog_id: str
    log_no: str
    url: str
    nickname: str
    comment: str

    def to_dict(self) -> dict:
        return asdict(self)
