"""발행 후 성과 추적기.

생성된 brief(generated_briefs)를 실제 발행글(posts)·성과(post_metrics)와 연결해
1d/3d/7d/30d 누적 조회수·검색유입을 채운다(post_outcomes). 이 데이터가 다음 사이클의
my_blog_fit 학습 신호가 된다.

흐름:
  1) (선택) BlogStatsCrawler 로 최근 통계 갱신 — 실패해도 계속.
  2) 최근 brief 들을 순회하며 recommended_title ↔ posts.title 정규화 매칭.
  3) post_metrics 에서 published_at 기준 days 에 가장 가까운 지평(1/3/7/30)의 누적값 계산.
  4) 유입 키워드 상위 수집 → post_outcomes upsert.

네트워크/통계 부재에도 죽지 않는다(graceful). 매칭 실패 brief 는 건너뛴다.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from ..logging_setup import get_logger
from .config import GrowthConfig
from .models import PostMetric, PostOutcome, PostRecord, SeoBrief
from .repository import Repository

log = get_logger()

# 지원하는 성과 지평(일)
_HORIZONS = (1, 3, 7, 30)


def _normalize_title(title: str | None) -> str:
    """제목 비교용 정규화 — 공백/문장부호 제거 후 소문자."""
    if not title:
        return ""
    # 한글/영문/숫자만 남기고 모두 제거(이모지·공백·구분기호 무시)
    cleaned = re.sub(r"[^0-9A-Za-z가-힣]", "", str(title))
    return cleaned.lower()


def _closest_horizon(days: int) -> int:
    """days 에 가장 가까운 지평을 고른다(동률이면 작은 쪽)."""
    try:
        d = int(days)
    except (TypeError, ValueError):
        d = 7
    return min(_HORIZONS, key=lambda h: (abs(h - d), h))


def _parse_date(value: str | None) -> date | None:
    """'YYYY-MM-DD' 또는 ISO 타임스탬프에서 date 추출(실패 시 None)."""
    if not value:
        return None
    s = str(value).strip()
    # 앞 10자가 날짜인 흔한 케이스 우선
    head = s[:10]
    for fmt in ("%Y-%m-%d",):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            pass
    # 점/슬래시 구분 등 폴백
    m = re.match(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _build_title_index(posts: list[PostRecord]) -> dict[str, PostRecord]:
    """정규화 제목 → PostRecord(먼저 본 글 우선 유지)."""
    index: dict[str, PostRecord] = {}
    for p in posts:
        key = _normalize_title(p.title)
        if key and key not in index:
            index[key] = p
    return index


def _match_post(brief: SeoBrief, posts: list[PostRecord],
                title_index: dict[str, PostRecord]) -> PostRecord | None:
    """brief 에 대응하는 발행글을 찾는다.

    우선순위: 정규화 제목 완전일치 → 부분포함(한쪽이 다른쪽을 포함).
    """
    target = _normalize_title(brief.recommended_title)
    if not target:
        return None
    exact = title_index.get(target)
    if exact:
        return exact
    # 부분 포함 매칭(제목이 발행 과정에서 살짝 바뀐 경우)
    for p in posts:
        key = _normalize_title(p.title)
        if not key:
            continue
        if target in key or key in target:
            return p
    return None


def _cumulative_at_horizon(metrics: list[PostMetric], published: date | None,
                           horizon_days: int) -> tuple[int | None, int | None]:
    """published_at + horizon_days 까지의 누적 조회수·검색유입.

    post_metrics 가 일자별 '누적' 스냅샷인지 '증분'인지 알 수 없으므로,
    지평 안쪽 마지막 스냅샷의 views(누적값으로 가정)를 우선 쓰되,
    그게 없으면 증분 합으로 폴백한다. published_at 이 없으면 가장 최근 스냅샷 사용.
    """
    if not metrics:
        return None, None

    rows: list[tuple[date | None, PostMetric]] = [
        (_parse_date(m.metric_date), m) for m in metrics
    ]

    if published is not None:
        cutoff_ord = published.toordinal() + max(0, int(horizon_days))
        in_window = [
            (d, m) for (d, m) in rows
            if d is not None and published.toordinal() <= d.toordinal() <= cutoff_ord
        ]
    else:
        # 발행일 모르면 전체를 윈도로 본다.
        in_window = [(d, m) for (d, m) in rows]

    if not in_window:
        return None, None

    # 일자 오름차순(날짜 없는 건 뒤로)
    in_window.sort(key=lambda x: (x[0] is None, x[0].toordinal() if x[0] else 0))

    # 누적 스냅샷 가정: 윈도 내 '최댓값'(=최신 누적값)을 그 구간 값으로 본다.
    #   ⚠️ 합산(sum)하면 매일 수집한 누적 스냅샷이 중복 합산돼 과대 집계된다(예: [10,30,70]→110).
    #   max 가 누적의 최신값에 해당하므로 max 를 쓴다.
    snap_views = max((int(m.views or 0) for _, m in in_window), default=0)
    snap_inflow = max((int(m.search_inflow or 0) for _, m in in_window), default=0)

    # 스냅샷이 전부 0 이면(증분 데이터만 있는 경우) 증분 합으로 폴백.
    if snap_views == 0:
        snap_views = sum(int(m.views or 0) for _, m in in_window)
    if snap_inflow == 0:
        snap_inflow = sum(int(m.search_inflow or 0) for _, m in in_window)
    return int(snap_views), int(snap_inflow)


def _top_inflow_keywords(repo: Repository, post_id: str, limit: int = 10) -> list[str]:
    """글의 유입 키워드 상위(중복 제거, 유입수 내림차순)."""
    try:
        rows = repo.get_inflow_keywords_for_post(post_id)
    except Exception:  # noqa: BLE001
        return []
    # 같은 키워드가 일자별로 여러 행 → 유입 합산
    agg: dict[str, int] = {}
    for k in rows:
        kw = (k.keyword or "").strip()
        if not kw:
            continue
        agg[kw] = agg.get(kw, 0) + int(k.inflow_count or 0)
    ranked = sorted(agg.items(), key=lambda x: (-x[1], x[0]))
    return [kw for kw, _ in ranked[:limit]]


def _refresh_stats(cfg: Any, growth_cfg: GrowthConfig, repo: Repository,
                   *, blog_id: str | None, days: int) -> None:
    """BlogStatsCrawler 로 통계 갱신 시도(실패·미구현이어도 무시)."""
    try:
        from .blog_stats_crawler import BlogStatsCrawler  # 지연 임포트(미구현/누락 대비)
    except Exception as e:  # noqa: BLE001
        log.info("outcome_tracker: 통계 크롤러 임포트 생략(%s)", type(e).__name__)
        return
    try:
        crawler = BlogStatsCrawler(cfg, growth_cfg, repo)
        result = crawler.collect_stats(blog_id=blog_id, days=days)
        if isinstance(result, dict):
            log.info("outcome_tracker: 통계 갱신 result=%s", result.get("note") or result.get("ok"))
    except Exception as e:  # noqa: BLE001
        log.warning("outcome_tracker: 통계 갱신 실패, 기존 DB로 진행(%s)", type(e).__name__)


def collect_outcomes(cfg: Any, growth_cfg: GrowthConfig, *, days: int,
                     blog_id: str | None = None) -> dict[str, Any]:
    """최근 brief 들의 발행 성과를 집계해 post_outcomes 에 기록한다.

    Args:
        cfg: blog_automation.config.Config (통계 크롤러용 — 세션/셀렉터).
        growth_cfg: SEO 레이어 설정(GrowthConfig). db_path 제공.
        days: 성과 지평(1/3/7/30 중 가장 가까운 값으로 매핑).
        blog_id: 통계 대상 블로그 주소(없으면 크롤러 기본값).

    Returns:
        {"updated": int, "note": str} — 매칭/기록 못 해도 죽지 않는다.
    """
    horizon = _closest_horizon(days)
    updated = 0
    notes: list[str] = []

    try:
        repo = Repository(growth_cfg.db_path)
    except Exception as e:  # noqa: BLE001
        log.warning("outcome_tracker: DB 열기 실패(%s)", type(e).__name__)
        return {"updated": 0, "note": f"db_open_failed:{type(e).__name__}"}

    try:
        # 1) 최근 brief 먼저 확인 — 회수할 대상(brief)이 없으면 통계 크롤러(브라우저/로그인)를
        #    띄우지 않고 일찍 끝낸다(빈 DB 에서 불필요한 로그인 방지).
        try:
            briefs = repo.get_recent_briefs(limit=20)
        except Exception as e:  # noqa: BLE001
            log.warning("outcome_tracker: brief 조회 실패(%s)", type(e).__name__)
            briefs = []
        if not briefs:
            return {"updated": 0, "note": "no_briefs"}

        # 2) (선택) 통계 신선도 확보 — 실패해도 기존 DB로 진행.
        _refresh_stats(cfg, growth_cfg, repo, blog_id=blog_id, days=days)

        # 3) 매칭 대상 글 로드.
        try:
            posts = repo.get_all_posts()
        except Exception as e:  # noqa: BLE001
            log.warning("outcome_tracker: posts 조회 실패(%s)", type(e).__name__)
            posts = []
        if not posts:
            return {"updated": 0, "note": "no_posts_to_match"}

        title_index = _build_title_index(posts)
        matched = 0

        # 3) brief 별 매칭 + 성과 계산 + upsert.
        for brief in briefs:
            try:
                post = _match_post(brief, posts, title_index)
                if post is None:
                    continue
                matched += 1

                published = _parse_date(post.published_at)
                metrics = repo.get_metrics_for_post(post.post_id)
                views, inflow = _cumulative_at_horizon(metrics, published, horizon)
                top_kws = _top_inflow_keywords(repo, post.post_id) if post.post_id else []

                outcome = PostOutcome(
                    brief_id=brief.brief_id,
                    post_id=post.post_id,
                    post_url=post.url,
                    published_at=post.published_at,
                    top_inflow_keywords=top_kws,
                )
                # days 에 해당하는 지평 컬럼만 채운다(나머지는 None → COALESCE 보존).
                setattr(outcome, f"views_{horizon}d", views)
                setattr(outcome, f"search_inflow_{horizon}d", inflow)

                repo.upsert_post_outcome(outcome)
                updated += 1
            except Exception as e:  # noqa: BLE001
                log.warning("outcome_tracker: brief=%s 처리 실패(%s)",
                            getattr(brief, "brief_id", "?"), type(e).__name__)
                continue

        notes.append(f"horizon={horizon}d")
        notes.append(f"matched={matched}/{len(briefs)}")
        log.info("outcome_tracker: updated=%d matched=%d/%d horizon=%dd",
                 updated, matched, len(briefs), horizon)
        return {"updated": updated, "note": " ".join(notes)}
    finally:
        repo.close()
