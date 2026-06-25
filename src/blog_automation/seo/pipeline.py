"""SEO 레이어 오케스트레이션(글루).

CLI(seo-* 서브커맨드)가 호출하는 run_* 진입점. 개별 단계(topic/candidate/collect/scoring/
title/tag/brief/quality)를 순서대로 엮는다. 각 단계는 leaf 모듈이 담당하고, 여기서는 흐름과
입출력 파일(SEO_BRIEF.md/SEO_REPORT.md)·DB 적재만 책임진다.

⚠️ leaf 모듈 import 는 이 파일 import 시점에 일어나므로, cli 는 seo 서브커맨드 안에서만
   pipeline 을 import 한다(leaf 에 문제가 있어도 기존 커맨드는 영향 없음 = backward compat).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import Config
from ..logging_setup import get_logger
from ..utils.files import read_json
from .config import GrowthConfig, load_growth_config
from .models import PostRecord, SeoBrief
from .repository import Repository

log = get_logger()


# ───────────────────────── 공통 헬퍼 ─────────────────────────

def _job_paths(cfg: Config, job: str) -> tuple[Path, Path]:
    """(input_dir/<job>, drafts_dir/<job>) 반환."""
    return cfg.input_dir / job, cfg.drafts_dir / job


def _brief_output_dir(cfg: Config, growth: GrowthConfig, job: str) -> Path:
    """SEO_BRIEF.md/SEO_REPORT.md 를 둘 폴더(기본 data/drafts/<job>/)."""
    sub = (growth.seo.get("output_subdir") or "").strip()
    base = cfg.drafts_dir / job
    out = base / sub if sub else base
    out.mkdir(parents=True, exist_ok=True)
    return out


def _new_brief_id(job: str) -> str:
    return f"{job}__{datetime.now().strftime('%Y%m%d%H%M%S')}"


def _canonical_category(raw: str | None) -> str | None:
    """수집기 분류(맛집방문/제품리뷰)를 SEO 정규 카테고리(맛집/육아템)로 매핑.

    topic_extractor 도 같은 정규 카테고리를 쓰므로, posts.category 를 맞춰 둬야
    historical_performance 의 카테고리별 신호가 제대로 매칭된다.
    """
    from . import constants
    s = (raw or "").strip()
    if not s:
        return None
    for cat, aliases in constants.CATEGORY_ALIASES.items():
        if s == cat or s in aliases:
            return cat
    return s


# ───────────────────────── seo-init-db ─────────────────────────

def run_init_db(growth: GrowthConfig | None = None) -> Path:
    from .db import init_db_file
    growth = growth or load_growth_config()
    path = init_db_file(growth.db_path)
    log.info("blog_growth DB 초기화 완료 → %s", path)
    return path


# ───────────────────────── seo-import-posts ─────────────────────────

def run_import_posts(cfg: Config, growth: GrowthConfig, blog_id: str) -> int:
    """data/collected/<blog_id>/*.json (CollectedPost) → posts 테이블 적재."""
    src = cfg.collected_dir / blog_id
    if not src.exists():
        log.error("수집 폴더가 없습니다: %s (먼저 `python main.py collect --id %s`)", src, blog_id)
        return 0
    files = sorted(p for p in src.glob("*.json") if not p.name.startswith("_"))
    if not files:
        log.error("수집된 글 JSON 이 없습니다: %s", src)
        return 0

    repo = Repository(growth.db_path)
    n = 0
    try:
        for fp in files:
            try:
                d = read_json(fp)
            except Exception as e:  # noqa: BLE001
                log.warning("읽기 실패 %s: %s", fp.name, e)
                continue
            urls = d.get("image_urls", []) or []
            gif_count = sum(1 for u in urls if str(u).lower().endswith(".gif"))
            repo.upsert_post(PostRecord(
                post_id=str(d.get("post_id") or fp.stem),
                title=d.get("title") or "(제목 없음)",
                url=d.get("url"),
                category=_canonical_category(d.get("category_guess")),
                published_at=d.get("posted_at") or None,
                content_text=d.get("body_text") or None,
                content_md=d.get("body_text") or None,
                tags=d.get("tags", []) or [],
                media_count=len(urls),
                image_count=len(urls) - gif_count,
                gif_count=gif_count,
                video_count=0,
            ))
            n += 1
        log.info("posts 적재 완료: %d개 (blog_id=%s)", n, blog_id)
    finally:
        repo.close()
    return n


# ───────────────────────── seo-research-keywords ─────────────────────────

def _extract_and_candidates(cfg: Config, growth: GrowthConfig, job: str):
    """topic 추출 + 후보 생성(공통)."""
    from .keyword_candidate_generator import generate_candidates
    from .topic_extractor import extract_topics
    topic = extract_topics(growth, job=job, input_dir=cfg.input_dir, drafts_dir=cfg.drafts_dir)
    candidates = generate_candidates(topic, growth)
    return topic, candidates


def run_research_keywords(cfg: Config, growth: GrowthConfig, job: str) -> dict[str, Any]:
    """주제 추출 → 후보 생성 → 네이버 데이터 수집 → keyword_research 적재."""
    from .naver_data_collector import NaverDataCollector
    topic, candidates = _extract_and_candidates(cfg, growth, job)
    log.info("주제: category=%s topics=%s", topic.category, ", ".join(topic.detected_topics[:8]))
    targets = candidates.all_research_targets()
    log.info("키워드 후보 %d개 수집 시작(open_api=%s, fallback=%s)",
             len(targets), growth.use_open_api(), growth.use_crawling_fallback())

    repo = Repository(growth.db_path)
    try:
        collector = NaverDataCollector(growth, repo)
        research = collector.collect(targets, topic=topic)
    finally:
        repo.close()
    log.info("수집 완료: %d개 키워드", len(research))
    return {"category": topic.category, "targets": len(targets), "collected": len(research)}


# ───────────────────────── seo-generate-brief ─────────────────────────

def run_generate_brief(cfg: Config, growth: GrowthConfig, job: str) -> dict[str, Any]:
    """전체 SEO 전략 파이프라인 → SEO_BRIEF.md/SEO_REPORT.md + DB.

    반환: {brief_id, primary_keyword, brief_path, report_path}
    """
    from .historical_performance import analyze
    from .keyword_scoring import score_keywords, select_primary_and_secondary
    from .naver_data_collector import NaverDataCollector
    from .seo_brief_generator import assemble_brief, render_brief_md, render_report_md
    from .tag_optimizer import optimize_tags
    from .title_optimizer import optimize_titles
    from ..utils.files import write_json

    topic, candidates = _extract_and_candidates(cfg, growth, job)
    log.info("[SEO] category=%s | topics=%s", topic.category, ", ".join(topic.detected_topics[:8]))

    repo = Repository(growth.db_path)
    try:
        targets = candidates.all_research_targets()
        collector = NaverDataCollector(growth, repo)
        research_list = collector.collect(targets, topic=topic)
        research_by_kw = {r.keyword: r for r in research_list}

        historical = analyze(repo, topic.category, topic)
        scored = score_keywords(candidates, research_by_kw, topic, historical, growth)
        primary, secondaries = select_primary_and_secondary(scored, growth)

        primary_kw = primary.keyword if primary else (
            candidates.primary_candidates[0] if candidates.primary_candidates else None)
        secondary_kws = [s.keyword for s in secondaries]

        titles = optimize_titles(primary_kw or "", secondary_kws, topic, historical, growth)
        tag_result = optimize_tags(primary_kw or "", secondary_kws, topic, growth,
                                   existing_candidates=candidates.tag_candidates)

        strategy_reason = _strategy_reason(primary, secondaries, topic, historical)

        brief = assemble_brief(
            brief_id=_new_brief_id(job), topic=topic, primary=primary, secondaries=secondaries,
            title_candidates=titles, tag_result=tag_result, scored=scored,
            strategy_reason=strategy_reason,
        )
        brief.input_folder = job
        brief.category = topic.category
        # avoid 키워드는 '카테고리 관련성'으로 필터된 candidates.avoid_candidates 를 우선 사용한다.
        # (assemble_brief 의 태그 기반 목록엔 타 카테고리 빅키워드(예: 육아템 글에 '강남맛집')가
        #  섞일 수 있어, 더 깨끗한 후보 목록으로 교체)
        if candidates.avoid_candidates:
            brief.avoid_keywords = candidates.avoid_candidates[:10]

        brief_md = brief.seo_brief_md or render_brief_md(brief, topic, historical)
        brief.seo_brief_md = brief_md
        report_md = render_report_md(brief, topic, historical, research_by_kw, scored)

        out_dir = _brief_output_dir(cfg, growth, job)
        brief_path = out_dir / "SEO_BRIEF.md"
        report_path = out_dir / "SEO_REPORT.md"
        brief_path.write_text(brief_md, encoding="utf-8")
        report_path.write_text(report_md, encoding="utf-8")
        write_json(out_dir / "seo_brief.json", brief.to_dict())

        repo.insert_brief(brief)
    finally:
        repo.close()

    log.info("[SEO] 완료 → %s", brief_path)
    log.info("[SEO] Primary: %s | Title: %s", brief.primary_keyword, brief.recommended_title)
    return {
        "brief_id": brief.brief_id, "primary_keyword": brief.primary_keyword,
        "recommended_title": brief.recommended_title,
        "brief_path": str(brief_path), "report_path": str(report_path),
    }


def _strategy_reason(primary, secondaries, topic, historical) -> str:
    parts: list[str] = []
    if primary is not None:
        parts.append(f"Primary '{primary.keyword}'(점수 {primary.final_score:.0f})는 "
                     f"검색 수요 대비 경쟁이 낮고 콘텐츠/페르소나 적합도가 높아 선택했다.")
    if secondaries:
        parts.append("Secondary 는 " + ", ".join(s.keyword for s in secondaries[:5])
                     + " 로 롱테일 유입을 노린다.")
    sp = (historical or {}).get("strong_patterns") or []
    if sp:
        parts.append("내 블로그 강세 패턴(" + ", ".join(sp[:3]) + ")과도 부합한다.")
    if not parts:
        parts.append(f"입력 콘텐츠(category={topic.category})에서 추출한 주제를 바탕으로 "
                     "검색 의도에 맞는 키워드를 구성했다.")
    return " ".join(parts)


# ───────────────────────── seo-quality-check ─────────────────────────

def run_quality_check(cfg: Config, growth: GrowthConfig, job: str) -> dict[str, Any]:
    """작성된 data/drafts/<job>/post.md + layout.json 을 brief 기준으로 기계 검사."""
    from .quality_guard import check_quality
    _input_dir, drafts = _job_paths(cfg, job)
    post_path = drafts / "post.md"
    layout_path = drafts / "layout.json"
    if not post_path.exists():
        log.error("post.md 가 없습니다: %s (먼저 글을 작성하세요)", post_path)
        return {"passed": False, "issues": ["post.md 없음"]}

    try:
        post_md = post_path.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.error("post.md 읽기 실패: %s (%s)", post_path, type(e).__name__)
        return {"passed": False, "issues": [f"post.md 읽기 실패: {type(e).__name__}"]}
    # layout.json 은 선택 — 깨졌으면 무시하고 본문만 검사(크래시 금지).
    layout = None
    if layout_path.exists():
        try:
            layout = read_json(layout_path)
        except Exception as e:  # noqa: BLE001
            log.warning("layout.json 파싱 실패(무시하고 진행): %s (%s)", layout_path, type(e).__name__)

    repo = Repository(growth.db_path)
    try:
        brief = repo.get_latest_brief_for_folder(job)
    finally:
        repo.close()
    if brief is None:
        log.warning("이 job 의 SEO brief 가 DB 에 없습니다. brief 없이 일반 품질만 검사합니다.")
        brief = SeoBrief(brief_id="(none)", input_folder=job)

    result = check_quality(post_md=post_md, layout=layout, brief=brief, growth_cfg=growth)
    from ..utils.files import write_json
    write_json(drafts / "SEO_QUALITY.json", result.to_dict())
    level = log.info if result.passed else log.warning
    level("[SEO][QualityGuard] passed=%s score=%.0f", result.passed, result.score)
    for issue in result.issues:
        log.warning("  - %s", issue)
    return result.to_dict()
