"""SEO 브리프 조립 + 마크다운 렌더링.

키워드 점수/제목 후보/태그 결과를 받아 SeoBrief 데이터를 채우고(assemble_brief),
글쓰기용 SEO_BRIEF.md(render_brief_md)와 사람이 읽는 SEO_REPORT.md(render_report_md)를
문자열로 만든다. 파일은 여기서 쓰지 않는다(파이프라인이 저장).
"""
from __future__ import annotations

from typing import Any

from ..logging_setup import get_logger
from .models import (
    ScoredKeyword,
    SeoBrief,
    TitleCandidate,
    TopicExtraction,
)

log = get_logger()


# ───────────────────────── 조립 ─────────────────────────

def assemble_brief(
    *,
    brief_id: str,
    topic: TopicExtraction,
    primary: ScoredKeyword | None,
    secondaries: list[ScoredKeyword],
    title_candidates: list[TitleCandidate],
    tag_result: dict[str, Any],
    scored: list[ScoredKeyword],
    strategy_reason: str,
) -> SeoBrief:
    """입력들을 SeoBrief 의 모든 필드로 채운다. 끝에서 seo_brief_md 까지 렌더해 넣는다."""
    secondaries = secondaries or []
    title_candidates = title_candidates or []
    scored = scored or []
    tag_result = tag_result or {}

    # 추천 제목 / 대안 제목
    recommended_title: str | None = None
    title_alternatives: list[dict[str, Any]] = []
    if title_candidates:
        recommended_title = (title_candidates[0].title or "").strip() or None
        for tc in title_candidates[1:]:
            title_alternatives.append(
                {
                    "title": tc.title,
                    "score": round(float(tc.score or 0.0), 1),
                    "reason": tc.reason or "",
                }
            )

    # 회피 키워드: scored 중 감점이 점수를 지배하는 후보 + 토픽 파생(태그 회피)
    avoid_keywords = _derive_avoid_keywords(scored, tag_result, topic)

    brief = SeoBrief(
        brief_id=brief_id,
        input_folder=topic.input_folder,
        category=topic.category,
        detected_topics=list(topic.detected_topics or []),
        primary_keyword=(primary.keyword if primary else None),
        secondary_keywords=[s.keyword for s in secondaries],
        avoid_keywords=avoid_keywords,
        recommended_title=recommended_title,
        title_alternatives=title_alternatives,
        selected_tags=list(tag_result.get("selected_tags") or []),
        keyword_scores=[sk.to_dict() for sk in scored],
        strategy_reason=(strategy_reason or "").strip() or None,
    )

    # seo_brief_md 는 마지막에 채운다(render_brief_md 는 seo_brief_md 에 의존하지 않음).
    try:
        brief.seo_brief_md = render_brief_md(brief, topic, {})
    except Exception:  # noqa: BLE001
        log.warning("render_brief_md 실패 — seo_brief_md 미설정", exc_info=True)
        brief.seo_brief_md = None
    return brief


def _derive_avoid_keywords(
    scored: list[ScoredKeyword],
    tag_result: dict[str, Any],
    topic: TopicExtraction,
) -> list[str]:
    """감점이 점수를 지배하는 후보 + 태그 옵티마이저가 회피로 분류한 것을 합친다(중복 제거)."""
    seen: dict[str, None] = {}
    out: list[str] = []

    def _add(kw: str | None) -> None:
        k = (kw or "").strip()
        if k and k not in seen:
            seen[k] = None
            out.append(k)

    for sk in scored or []:
        penalty = float(sk.competition_penalty or 0.0) + float(sk.mismatch_penalty or 0.0)
        # 감점 합이 충분히 크거나(>=40) 최종점수보다 크면 '회피' 신호로 본다.
        if penalty >= 40.0 or (penalty > 0.0 and penalty >= float(sk.final_score or 0.0)):
            _add(sk.keyword)

    for kw in (tag_result.get("avoid_tags") or []):
        _add(kw)

    return out


# ───────────────────────── 공통 렌더 헬퍼 ─────────────────────────

def _bullet_lines(items: list[str], *, empty: str = "(없음)") -> str:
    """문자열 리스트를 마크다운 불릿으로. 비면 안내 1줄."""
    vals = [str(x).strip() for x in (items or []) if str(x).strip()]
    if not vals:
        return f"- {empty}"
    return "\n".join(f"- {v}" for v in vals)


def _tag_line(tags: list[str], *, empty: str = "(없음)") -> str:
    """태그는 #붙여 한 줄로."""
    vals = [str(x).strip().lstrip("#") for x in (tags or []) if str(x).strip()]
    if not vals:
        return empty
    return " ".join(f"#{v}" for v in vals)


def _fmt_score(value: Any) -> str:
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "-"


def _md_cell(text: Any) -> str:
    """마크다운 표 셀 — 파이프/개행이 표를 깨지 않게 치환."""
    s = "" if text is None else str(text)
    return s.replace("|", "/").replace("\n", " ").strip()


def _required_sections(topic: TopicExtraction) -> list[str]:
    """카테고리/플래그 기반으로 본문에 포함하면 좋은 섹션 가이드."""
    cat = topic.category or "기타"
    secs: list[str] = ["도입(방문/사용 계기, 한 줄 요약)"]
    if cat == "맛집":
        secs += ["위치와 주차/접근", "메뉴와 가격", "맛과 분위기", "재방문 의사/총평"]
    elif cat == "여행":
        secs += ["일정/동선", "볼거리와 즐길거리", "비용/숙소", "꿀팁과 총평"]
    elif cat == "육아":
        secs += ["상황 배경(아이 월령/상황)", "과정과 경험", "느낀 점/팁"]
    elif cat == "육아템":
        secs += ["구매 계기", "실사용 후기", "장점", "단점/아쉬운 점", "추천 대상/총평"]
    else:
        secs += ["본문(경험/기록)", "느낀 점/총평"]

    if topic.has_parking_evidence:
        secs.append("주차 정보(사진으로 확인된 것만)")
    if topic.is_product_review:
        secs.append("솔직한 장단점(과장 금지)")
    return secs


def _intent_lines(topic: TopicExtraction) -> str:
    """검색 의도 — target_intents 우선, 없으면 플래그/카테고리로 보강."""
    intents = [str(x).strip() for x in (topic.target_intents or []) if str(x).strip()]
    if not intents:
        cat = topic.category or "기타"
        if cat == "맛집":
            intents = ["가게 정보 확인", "메뉴/가격 확인", "방문 후기 확인"]
        elif cat == "여행":
            intents = ["가볼만한 곳 탐색", "코스/숙소 정보", "방문 후기 확인"]
        elif cat == "육아":
            intents = ["비슷한 상황 정보 탐색", "경험담/팁 확인"]
        elif cat == "육아템":
            intents = ["실사용 후기 확인", "장단점 비교", "구매 결정 참고"]
        else:
            intents = ["관련 정보/경험 탐색"]
    if topic.has_kid_context and not any("아이" in i or "아기" in i for i in intents):
        intents.append("아이 동반 가능 여부")
    if topic.has_date_mood and not any("데이트" in i for i in intents):
        intents.append("데이트 적합 여부")
    return _bullet_lines(intents)


# ───────────────────────── SEO_BRIEF.md (글쓰기용) ─────────────────────────

def render_brief_md(brief: SeoBrief, topic: TopicExtraction, historical: dict[str, Any]) -> str:
    """글쓰기 단계가 읽는 SEO 브리프. seo_brief_md 에 의존하지 않는다."""
    historical = historical or {}
    primary = (brief.primary_keyword or "").strip()
    primary_disp = primary or "(미정)"

    # 제목 대안
    alt_lines = []
    for alt in (brief.title_alternatives or []):
        t = _md_cell(alt.get("title"))
        sc = _fmt_score(alt.get("score"))
        if t:
            alt_lines.append(f"- {t} (점수 {sc})")
    alt_block = "\n".join(alt_lines) if alt_lines else "- (없음)"

    # 키워드 배치 가이드
    placement_lines = [
        f"- Primary 키워드 `{primary_disp}` 를 제목과 첫 문단에 각각 1회 자연스럽게 넣는다.",
        f"- Primary 키워드를 소제목(중간 제목) 1곳에 1회 반영한다.",
        "- Secondary 키워드는 각각 1~2회만, 문맥에 맞을 때만 넣는다(억지 반복 금지).",
        "- 키워드 욱여넣기(stuffing) 금지 — 어색하면 빼는 게 낫다.",
        "- 글 하단 태그는 아래 'Selected Tags' 를 그대로 사용한다.",
    ]

    # 톤 가이드(고정 원칙)
    tone_lines = [
        "- 기존 페르소나(말투/줄바꿈/이모지)를 그대로 유지한다.",
        "- 키워드를 위해 문장을 비틀지 않는다 — 자연스러움이 우선.",
        "- 사진/영상으로 확인되는 사실만 쓴다(가격·고유명사 날조 금지).",
    ]
    if topic.is_product_review:
        tone_lines.append("- 제품 리뷰는 실사용 경험 + 장단점을 균형 있게(과장/단점 은폐 금지).")

    # 키워드 점수표
    score_rows = _keyword_score_table_rows(brief.keyword_scores)

    persona_line = topic.content_type or topic.category or "기타"

    parts = [
        "# SEO Writing Brief",
        "",
        "## Input Folder",
        f"{brief.input_folder or topic.input_folder or '(미상)'}",
        "",
        "## Category",
        f"{brief.category or topic.category or '기타'}",
        "",
        "## Persona",
        f"{persona_line}",
        "",
        "## Primary Keyword",
        f"{primary_disp}",
        "",
        "## Secondary Keywords",
        _bullet_lines(brief.secondary_keywords),
        "",
        "## Avoid Keywords",
        _bullet_lines(brief.avoid_keywords),
        "",
        "## Recommended Title",
        f"{brief.recommended_title or '(미정)'}",
        "",
        "## Title Alternatives",
        alt_block,
        "",
        "## Selected Tags",
        _tag_line(brief.selected_tags),
        "",
        "## Search Intent",
        _intent_lines(topic),
        "",
        "## Required Sections",
        _bullet_lines(_required_sections(topic)),
        "",
        "## Keyword Placement Guide",
        "\n".join(placement_lines),
        "",
        "## Tone Guide",
        "\n".join(tone_lines),
        "",
        "## Strategy Reason",
        f"{brief.strategy_reason or '(없음)'}",
        "",
        "## Keyword Scores",
        "",
        "| Keyword | Final Score | Reason |",
        "| --- | --- | --- |",
        score_rows,
        "",
    ]
    return "\n".join(parts)


def _keyword_score_table_rows(keyword_scores: list[dict[str, Any]]) -> str:
    """keyword_scores(dict 리스트)를 마크다운 표 행 문자열로."""
    rows = []
    for sk in (keyword_scores or []):
        kw = _md_cell(sk.get("keyword"))
        if not kw:
            continue
        score = _fmt_score(sk.get("final_score"))
        reason = _md_cell(sk.get("reason")) or "-"
        rows.append(f"| {kw} | {score} | {reason} |")
    if not rows:
        return "| (없음) | - | - |"
    return "\n".join(rows)


# ───────────────────────── SEO_REPORT.md (사람용) ─────────────────────────

def render_report_md(
    brief: SeoBrief,
    topic: TopicExtraction,
    historical: dict[str, Any],
    research: dict[str, Any],
    scored: list[ScoredKeyword],
) -> str:
    """사람이 검토하는 리포트. 점수 근거/경쟁글/트렌드/위험요소까지 풀어 쓴다."""
    historical = historical or {}
    research = research or {}
    scored = scored or []
    primary = (brief.primary_keyword or "").strip()
    primary_disp = primary or "(미정)"

    parts: list[str] = [
        f"# SEO Report — {brief.brief_id}",
        "",
        "## 최종 추천 제목",
        f"{brief.recommended_title or '(미정)'}",
    ]
    # 대안 제목도 같이 보여준다.
    alt_lines = []
    for alt in (brief.title_alternatives or []):
        t = _md_cell(alt.get("title"))
        if t:
            alt_lines.append(f"- {t} (점수 {_fmt_score(alt.get('score'))})")
    if alt_lines:
        parts += ["", "대안 제목:", "\n".join(alt_lines)]

    parts += [
        "",
        "## 최종 Primary Keyword",
        f"{primary_disp}",
        "",
        "## 선택 이유",
        f"{brief.strategy_reason or '(없음)'}",
        "",
        "## 키워드 후보 점수표",
        "",
        _report_score_table(scored),
        "",
        "## 내 블로그 과거 유사글",
        _similar_posts_block(historical),
        "",
        "## 경쟁 상위 글 제목 패턴",
        _competitor_titles_block(primary, brief.secondary_keywords, research),
        "",
        "## 검색어 트렌드 분석",
        _trend_block(primary, brief.secondary_keywords, research),
    ]

    # 쇼핑인사이트는 제품형일 때만.
    if topic.is_product_review:
        parts += [
            "",
            "## 쇼핑인사이트 분석",
            _shopping_block(primary, brief.secondary_keywords, research),
        ]

    parts += [
        "",
        "## 추천 태그",
        _tag_line(brief.selected_tags),
        "",
        "## 본문 작성 가이드",
        _bullet_lines(_required_sections(topic)),
        "",
        "## 위험 요소",
        _risk_block(brief, topic, scored),
        "",
    ]
    return "\n".join(parts)


def _report_score_table(scored: list[ScoredKeyword]) -> str:
    """세부 점수까지 보여주는 점수표."""
    header = (
        "| Keyword | Role | Final | Demand | Opp | Fit | Content | Season | Comp- | Mis- |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    )
    rows = []
    for sk in (scored or []):
        kw = _md_cell(sk.keyword)
        if not kw:
            continue
        rows.append(
            "| {kw} | {role} | {fin} | {dem} | {opp} | {fit} | {con} | {sea} | {cmp} | {mis} |".format(
                kw=kw,
                role=_md_cell(sk.role),
                fin=_fmt_score(sk.final_score),
                dem=_fmt_score(sk.search_demand_score),
                opp=_fmt_score(sk.opportunity_score),
                fit=_fmt_score(sk.my_blog_fit_score),
                con=_fmt_score(sk.content_fit_score),
                sea=_fmt_score(sk.seasonality_score),
                cmp=_fmt_score(sk.competition_penalty),
                mis=_fmt_score(sk.mismatch_penalty),
            )
        )
    if not rows:
        return header + "\n| (없음) | - | - | - | - | - | - | - | - | - |"
    return header + "\n" + "\n".join(rows)


def _similar_posts_block(historical: dict[str, Any]) -> str:
    """과거 유사글 요약 — 조회/유입/키워드."""
    cat = historical.get("category")
    avg7 = historical.get("category_avg_views_7d")
    avg30 = historical.get("category_avg_views_30d")
    avg_inflow = historical.get("category_avg_search_inflow_30d")
    lines: list[str] = []
    if cat or avg30 is not None:
        lines.append(
            "카테고리 `{c}` 평균 조회 7일 {a7} / 30일 {a30}, 검색유입 30일 {ai}".format(
                c=cat or "-",
                a7=_fmt_score(avg7) if avg7 is not None else "-",
                a30=_fmt_score(avg30) if avg30 is not None else "-",
                ai=_fmt_score(avg_inflow) if avg_inflow is not None else "-",
            )
        )

    similar = historical.get("similar_posts") or []
    if similar:
        lines.append("")
        lines.append("| 제목 | 조회(30일) | 검색유입(30일) | 주요 키워드 |")
        lines.append("| --- | --- | --- | --- |")
        for p in similar[:10]:
            title = _md_cell(p.get("title")) or "(제목없음)"
            v30 = p.get("views_30d")
            si30 = p.get("search_inflow_30d")
            kws = ", ".join(str(k) for k in (p.get("main_keywords") or []))
            lines.append(
                f"| {title} | {v30 if v30 is not None else '-'} | "
                f"{si30 if si30 is not None else '-'} | {_md_cell(kws) or '-'} |"
            )

    strong = historical.get("strong_keywords") or []
    if strong:
        lines.append("")
        lines.append("강한 키워드: " + ", ".join(str(k) for k in strong[:15]))

    if not lines:
        return "(과거 데이터 없음 — 누적되면 채워집니다.)"
    return "\n".join(lines)


def _research_for(kw: str, research: dict[str, Any]) -> Any:
    """research dict 에서 키워드 레코드를 꺼낸다(없으면 None)."""
    if not kw:
        return None
    return research.get(kw)


def _competitor_titles_block(
    primary: str,
    secondaries: list[str],
    research: dict[str, Any],
) -> str:
    """Primary(없으면 secondary) 의 상위 노출 글 제목."""
    targets = [primary] + list(secondaries or [])
    for kw in targets:
        rec = _research_for(kw, research)
        titles = getattr(rec, "top_titles", None) if rec is not None else None
        if titles:
            head = f"`{kw}` 검색 상위 글 제목:"
            body = _bullet_lines([str(t) for t in titles[:10]])
            return head + "\n" + body
    return "(경쟁 글 데이터 없음 — API/크롤링 미수집)"


def _trend_block(primary: str, secondaries: list[str], research: dict[str, Any]) -> str:
    """검색어 트렌드(방향/점수) 요약."""
    lines: list[str] = []
    for kw in [primary] + list(secondaries or []):
        rec = _research_for(kw, research)
        if rec is None:
            continue
        direction = getattr(rec, "trend_direction", None)
        trend = getattr(rec, "trend_score", None)
        demand = getattr(rec, "search_demand_score", None)
        docs = getattr(rec, "blog_document_count", None)
        opp = getattr(rec, "opportunity_score", None)
        lines.append(
            "- `{kw}` — 수요 {dem} / 트렌드 {tr}({dir}) / 경쟁문서 {docs} / 기회 {opp}".format(
                kw=kw,
                dem=_fmt_score(demand) if demand is not None else "-",
                tr=_fmt_score(trend) if trend is not None else "-",
                dir=direction or "-",
                docs=docs if docs is not None else "-",
                opp=_fmt_score(opp) if opp is not None else "-",
            )
        )
    if not lines:
        return "(트렌드 데이터 없음 — DataLab/검색 API 미수집)"
    return "\n".join(lines)


def _shopping_block(primary: str, secondaries: list[str], research: dict[str, Any]) -> str:
    """쇼핑인사이트(제품형) — 쇼핑 트렌드 점수가 있으면 표시."""
    lines: list[str] = []
    for kw in [primary] + list(secondaries or []):
        rec = _research_for(kw, research)
        if rec is None:
            continue
        shop = getattr(rec, "shopping_trend_score", None)
        shop_cat = getattr(rec, "shopping_category", None)
        if shop is not None:
            lines.append(
                f"- `{kw}` — 쇼핑 트렌드 {_fmt_score(shop)}"
                + (f" (카테고리 {shop_cat})" if shop_cat else "")
            )
    if not lines:
        return "(쇼핑인사이트 데이터 없음 — 제품 카테고리 코드 미매핑이거나 미수집)"
    return "\n".join(lines)


def _risk_block(
    brief: SeoBrief,
    topic: TopicExtraction,
    scored: list[ScoredKeyword],
) -> str:
    """발행 전 사람이 확인할 위험 요소 체크리스트."""
    risks: list[str] = []

    if not brief.primary_keyword:
        risks.append("Primary 키워드가 정해지지 않음 — 주제/키워드 데이터 부족.")
    if not brief.recommended_title:
        risks.append("추천 제목이 비어 있음.")
    if not brief.selected_tags:
        risks.append("선택된 태그가 없음.")

    # 미스매치 감점이 큰 키워드는 콘텐츠와 안 맞을 수 있음.
    for sk in (scored or []):
        if float(sk.mismatch_penalty or 0.0) > 0.0 and sk.keyword in (
            [brief.primary_keyword] + list(brief.secondary_keywords or [])
        ):
            risks.append(
                f"`{sk.keyword}` 는 콘텐츠 근거와 어긋날 수 있음(사진/메모로 확인 필요)."
            )

    if topic.is_product_review:
        risks.append("제품 리뷰 — 장단점 균형/과장 금지, 가격·스펙은 확인된 것만.")
    if brief.avoid_keywords:
        risks.append("회피 키워드 사용 금지: " + ", ".join(brief.avoid_keywords))

    risks.append("대시/가운뎃점(-- — – ·)·연속 짧은 텍스트 블록은 네이버 가로선/가독성 위험.")

    return _bullet_lines(risks)
