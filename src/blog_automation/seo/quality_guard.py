from __future__ import annotations

"""발행 전 기계적 품질 점검(quality_guard).

작성된 본문(post.md)과 배치도(layout.json)를 brief 의 SEO 결정과 대조해
'사람 판단 없이도 잡을 수 있는' 결함만 체크한다(의미/문체 평가는 하지 않는다).

점검 항목:
  - 1차 키워드가 제목에 있는가(없으면 치명적)
  - 1차 키워드가 첫 문단에 있는가
  - 2차 키워드 과다 반복 / 1차 키워드 과다 반복
  - 본문 길이가 [min,max] 범위인가(벗어나면 치명적)
  - 태그 개수 초과
  - 대시/가운뎃점(-- — – ·) 포함 → 네이버가 글 위에 가로선 생성
  - layout 이 주어지면 text 블록 3개 이상 연속

길이/반복 계산 시 {{photo: ...}} 자리표시자와 마크다운 기호는 제거한다.
점수는 100 에서 시작해 항목별 가중치를 빼며, 결정적(deterministic)이다.
"""

import re

from ..logging_setup import get_logger
from .config import GrowthConfig
from .models import QualityResult, SeoBrief

log = get_logger()

# ── 항목별 감점 가중치 ──
_W_PRIMARY_NOT_IN_TITLE = 25      # 치명적
_W_PRIMARY_NOT_IN_FIRST = 10
_W_SECONDARY_OVER_REPEAT = 8      # 2차 키워드 1개당
_W_PRIMARY_OVER_REPEAT = 10
_W_LENGTH_OUT_OF_RANGE = 20       # 치명적
_W_TOO_MANY_TAGS = 5
_W_DASH_CHARS = 8
_W_CONSECUTIVE_TEXT = 6

# 네이버가 글 위에 가로선을 그리는 대시/구분 기호.
_DASH_TOKENS = ("--", "—", "–", "·")

# {{photo: 파일명}} 자리표시자.
_PHOTO_RE = re.compile(r"\{\{\s*photo\s*:[^}]*\}\}", re.IGNORECASE)


def _strip_markdown(text: str) -> str:
    """마크다운 기호/자리표시자를 제거해 순수 본문 텍스트만 남긴다(길이·반복 계산용)."""
    if not text:
        return ""
    out = _PHOTO_RE.sub(" ", text)
    # 코드펜스/인라인코드
    out = re.sub(r"```.*?```", " ", out, flags=re.DOTALL)
    out = re.sub(r"`([^`]*)`", r"\1", out)
    # 이미지 ![alt](url) → alt
    out = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", out)
    # 링크 [text](url) → text
    out = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", out)
    # 헤딩/인용/리스트 머리 기호
    out = re.sub(r"^[ \t]*#{1,6}[ \t]*", "", out, flags=re.MULTILINE)
    out = re.sub(r"^[ \t]*>[ \t]?", "", out, flags=re.MULTILINE)
    out = re.sub(r"^[ \t]*[-*+][ \t]+", "", out, flags=re.MULTILINE)
    # 강조 기호(*, _, ~)
    out = re.sub(r"[*_~]+", "", out)
    return out


def _first_paragraph(post_md: str, layout: dict | None) -> str:
    """첫 문단 = 첫 비어있지 않은 텍스트 블록/라인."""
    # layout 의 첫 text 블록을 우선 사용(있으면 더 정확).
    if isinstance(layout, dict):
        for blk in layout.get("blocks", []) or []:
            if not isinstance(blk, dict):
                continue
            if blk.get("type") == "text":
                content = _strip_markdown(str(blk.get("content", "")))
                content = content.strip()
                if content:
                    # 블록 안 줄바꿈은 첫 문단 한 덩어리로 본다.
                    return content
    # layout 이 없거나 text 블록이 없으면 post.md 의 첫 비어있지 않은 라인.
    stripped = _strip_markdown(post_md or "")
    for line in stripped.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _count_occurrences(haystack: str, needle: str) -> int:
    """대소문자 무시, 단순 부분문자열 등장 횟수(겹치지 않게)."""
    if not haystack or not needle:
        return 0
    return haystack.lower().count(needle.lower())


def _title_from(brief: SeoBrief, layout: dict | None) -> str:
    """제목 출처: brief.recommended_title → layout['title']."""
    title = (brief.recommended_title or "").strip() if brief else ""
    if title:
        return title
    if isinstance(layout, dict):
        return str(layout.get("title", "") or "").strip()
    return ""


def _count_consecutive_text_blocks(layout: dict | None) -> int:
    """text 블록이 연속으로 나타나는 최대 길이."""
    if not isinstance(layout, dict):
        return 0
    best = 0
    run = 0
    for blk in layout.get("blocks", []) or []:
        if isinstance(blk, dict) and blk.get("type") == "text":
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def check_quality(
    *,
    post_md: str,
    layout: dict | None,
    brief: SeoBrief,
    growth_cfg: GrowthConfig,
) -> QualityResult:
    """본문/배치도를 brief 와 대조해 기계적 결함을 점검하고 QualityResult 반환.

    예외를 던지지 않는다(호출자가 fallback 할 수 있게). 결정적.
    """
    qg = growth_cfg.quality_guard if growth_cfg else {}
    min_pass = int(qg.get("min_score_to_pass", 80))
    max_primary_rep = int(qg.get("max_primary_keyword_repeats", 4))
    max_secondary_rep = int(qg.get("max_secondary_keyword_repeats", 3))
    min_len = int(qg.get("min_body_length_chars", 1500))
    max_len = int(qg.get("max_body_length_chars", 8000))
    max_tags = int(growth_cfg.seo.get("max_tags", 10)) if growth_cfg else 10

    issues: list[str] = []
    fixes: list[str] = []
    score = 100.0
    has_critical = False

    primary = (brief.primary_keyword or "").strip() if brief else ""
    secondaries = [s.strip() for s in (brief.secondary_keywords or []) if s and s.strip()] if brief else []
    tags = [t for t in (brief.selected_tags or []) if t] if brief else []
    title = _title_from(brief, layout)

    body_text = _strip_markdown(post_md or "")
    first_para = _first_paragraph(post_md, layout)
    body_len = len(re.sub(r"\s", "", body_text))   # 공백 제외 글자수

    # ── 1) 1차 키워드가 제목에 있는가(치명적) ──
    if primary:
        if _count_occurrences(title, primary) < 1:
            issues.append(f"제목에 1차 키워드 '{primary}' 가 없습니다(치명적).")
            fixes.append(f"제목 앞쪽에 '{primary}' 를 자연스럽게 포함하세요.")
            score -= _W_PRIMARY_NOT_IN_TITLE
            has_critical = True
        # ── 2) 1차 키워드가 첫 문단에 있는가 ──
        if _count_occurrences(first_para, primary) < 1:
            issues.append(f"첫 문단에 1차 키워드 '{primary}' 가 없습니다.")
            fixes.append(f"도입부 첫 문단에 '{primary}' 를 한 번 넣으세요.")
            score -= _W_PRIMARY_NOT_IN_FIRST
    else:
        issues.append("brief 에 1차 키워드가 비어 있습니다.")
        fixes.append("SEO brief 의 primary_keyword 를 채우세요.")

    # ── 3) 1차 키워드 과다 반복 — 초과량에 비례해 감점(심할수록 통과 못 하게) ──
    if primary:
        prim_count = _count_occurrences(body_text, primary)
        if prim_count > max_primary_rep:
            excess = prim_count - max_primary_rep
            pen = min(40.0, _W_PRIMARY_OVER_REPEAT + (excess - 1) * 8)
            issues.append(
                f"1차 키워드 '{primary}' 가 {prim_count}회로 과다 반복입니다(최대 {max_primary_rep}회)."
            )
            fixes.append(f"'{primary}' 반복을 {max_primary_rep}회 이하로 줄이고 유의어로 대체하세요.")
            score -= pen

    # ── 4) 2차 키워드 과다 반복(1개당, 초과량 비례 감점) ──
    for kw in secondaries:
        cnt = _count_occurrences(body_text, kw)
        if cnt > max_secondary_rep:
            excess = cnt - max_secondary_rep
            pen = min(24.0, _W_SECONDARY_OVER_REPEAT + (excess - 1) * 5)
            issues.append(
                f"2차 키워드 '{kw}' 가 {cnt}회로 과다 반복입니다(최대 {max_secondary_rep}회)."
            )
            fixes.append(f"'{kw}' 반복을 {max_secondary_rep}회 이하로 줄이세요.")
            score -= pen

    # ── 5) 본문 길이 범위(치명적) ──
    if body_len < min_len:
        issues.append(f"본문이 너무 짧습니다({body_len}자, 최소 {min_len}자).")
        fixes.append(f"본문을 최소 {min_len}자 이상으로 보강하세요.")
        score -= _W_LENGTH_OUT_OF_RANGE
        has_critical = True
    elif body_len > max_len:
        issues.append(f"본문이 너무 깁니다({body_len}자, 최대 {max_len}자).")
        fixes.append(f"본문을 최대 {max_len}자 이하로 줄이세요.")
        score -= _W_LENGTH_OUT_OF_RANGE
        has_critical = True

    # ── 6) 태그 개수 초과 ──
    if len(tags) > max_tags:
        issues.append(f"태그가 {len(tags)}개로 너무 많습니다(최대 {max_tags}개).")
        fixes.append(f"태그를 {max_tags}개 이하로 줄이세요.")
        score -= _W_TOO_MANY_TAGS

    # ── 7) 대시/가운뎃점(네이버 가로선) ──
    found_dash = [d for d in _DASH_TOKENS if d in (post_md or "")]
    if found_dash:
        issues.append(
            "대시/구분 기호(" + " ".join(found_dash) + ")가 있어 네이버가 글 위에 가로선을 만들 수 있습니다."
        )
        fixes.append("대시(-- — –)·가운뎃점(·) 을 제거하거나 다른 표현으로 바꾸세요.")
        score -= _W_DASH_CHARS

    # ── 8) text 블록 3개 이상 연속(layout 이 있을 때만) ──
    if layout is not None:
        run = _count_consecutive_text_blocks(layout)
        if run >= 3:
            issues.append(f"텍스트 블록이 {run}개 연속입니다(사진 없이 3개 이상 연속).")
            fixes.append("연속된 텍스트 블록 사이에 사진/움짤을 넣어 끊어주세요.")
            score -= _W_CONSECUTIVE_TEXT

    # ── 점수 클램프 & 통과 판정 ──
    score = max(0.0, min(100.0, score))
    passed = (score >= min_pass) and not has_critical

    final_title = (brief.recommended_title or "").strip() if brief else ""
    final_tags = list(tags)

    log.info(
        "[QUALITY_GUARD] score=%.0f passed=%s critical=%s issues=%d",
        score, passed, has_critical, len(issues),
    )

    return QualityResult(
        passed=passed,
        score=score,
        issues=issues,
        suggested_fixes=fixes,
        final_title=final_title,
        final_tags=final_tags,
    )
