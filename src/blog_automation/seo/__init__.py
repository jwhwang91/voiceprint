"""Naver Blog Growth Agent — SEO/키워드/성과 분석 레이어.

기존 자동 글쓰기/발행 파이프라인(blog_automation 의 collect/publish 등)을 **건드리지 않고**,
글 작성 *앞단*에 검색 유입 전략(키워드·제목·태그)을 결정하는 부가 레이어다.

역할 분리(이 프로젝트의 하이브리드 철학 그대로):
  - Python(이 패키지) = 기계적 작업: 네이버 Open API/크롤링 수집, SQLite 적재, 점수 계산,
    SEO_BRIEF.md / SEO_REPORT.md 생성, 기계적 품질검사.
  - Claude Code(너) = 인지적 작업: SEO_BRIEF.md 를 읽어 페르소나 말투로 본문/배치 작성.

산출물:
  - data/drafts/<job>/SEO_BRIEF.md   — 작성 프롬프트(prompts/write_post.md)에 주입되는 전략
  - data/drafts/<job>/SEO_REPORT.md  — 사람이 검토하는 리포트
  - data/blog_growth/blog_growth.db  — 과거글/성과/키워드 조사/생성 brief 적재

절대 규칙: 자동 발행 금지, 로그인/캡차 우회 금지, API key 로깅 금지, 기존 파이프라인 backward-compat.
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
