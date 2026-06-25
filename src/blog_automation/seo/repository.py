"""Blog Growth DB DAO.

모든 SQL 접근은 이 Repository 를 통한다. 모델(models.py) ↔ row 변환을 담당하고,
JSON 컬럼(*_json)을 자동 직렬화/역직렬화한다. UNIQUE 제약이 있는 테이블은 upsert.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .db import connect, init_db
from .models import (
    InflowKeyword,
    KeywordRanking,
    KeywordResearch,
    PostMetric,
    PostOutcome,
    PostRecord,
    SeoBrief,
)


def _dumps(val: Any) -> str:
    return json.dumps(val if val is not None else [], ensure_ascii=False)


def _loads(val: Any, default: Any) -> Any:
    if not val:
        return default
    try:
        return json.loads(val)
    except (TypeError, ValueError):
        return default


def _today() -> str:
    return date.today().isoformat()


class Repository:
    """SQLite 위 thin DAO. with Repository(path) as repo: 로 쓰거나 직접 .close()."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.conn: sqlite3.Connection = connect(self.db_path)
        init_db(self.conn)

    # 컨텍스트 매니저 지원
    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass

    # ───────────────────────── posts ─────────────────────────
    def upsert_post(self, post: PostRecord) -> None:
        self.conn.execute(
            """
            INSERT INTO posts (post_id, title, url, category, published_at, updated_at,
                               content_md, content_text, tags_json, media_count,
                               image_count, gif_count, video_count)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(post_id) DO UPDATE SET
                title=excluded.title, url=excluded.url, category=excluded.category,
                published_at=excluded.published_at, updated_at=excluded.updated_at,
                content_md=excluded.content_md, content_text=excluded.content_text,
                tags_json=excluded.tags_json, media_count=excluded.media_count,
                image_count=excluded.image_count, gif_count=excluded.gif_count,
                video_count=excluded.video_count
            """,
            (post.post_id, post.title, post.url, post.category, post.published_at,
             post.updated_at, post.content_md, post.content_text, _dumps(post.tags),
             post.media_count, post.image_count, post.gif_count, post.video_count),
        )
        self.conn.commit()

    @staticmethod
    def _row_to_post(r: sqlite3.Row) -> PostRecord:
        return PostRecord(
            post_id=r["post_id"], title=r["title"], url=r["url"], category=r["category"],
            published_at=r["published_at"], updated_at=r["updated_at"],
            content_md=r["content_md"], content_text=r["content_text"],
            tags=_loads(r["tags_json"], []), media_count=r["media_count"] or 0,
            image_count=r["image_count"] or 0, gif_count=r["gif_count"] or 0,
            video_count=r["video_count"] or 0,
        )

    def get_post(self, post_id: str) -> PostRecord | None:
        r = self.conn.execute("SELECT * FROM posts WHERE post_id=?", (post_id,)).fetchone()
        return self._row_to_post(r) if r else None

    def get_all_posts(self) -> list[PostRecord]:
        rows = self.conn.execute("SELECT * FROM posts ORDER BY published_at DESC").fetchall()
        return [self._row_to_post(r) for r in rows]

    def get_posts_by_category(self, category: str) -> list[PostRecord]:
        rows = self.conn.execute(
            "SELECT * FROM posts WHERE category=? ORDER BY published_at DESC", (category,)
        ).fetchall()
        return [self._row_to_post(r) for r in rows]

    def count_posts(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS n FROM posts").fetchone()["n"]

    # ───────────────────────── post_metrics ─────────────────────────
    def upsert_post_metric(self, m: PostMetric) -> None:
        self.conn.execute(
            """
            INSERT INTO post_metrics (post_id, metric_date, views, visitors, search_inflow,
                                      likes, comments, new_neighbors, avg_duration_seconds, source_json)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(post_id, metric_date) DO UPDATE SET
                views=excluded.views, visitors=excluded.visitors,
                search_inflow=excluded.search_inflow, likes=excluded.likes,
                comments=excluded.comments, new_neighbors=excluded.new_neighbors,
                avg_duration_seconds=excluded.avg_duration_seconds, source_json=excluded.source_json
            """,
            (m.post_id, m.metric_date, m.views, m.visitors, m.search_inflow, m.likes,
             m.comments, m.new_neighbors, m.avg_duration_seconds, _dumps(m.source)),
        )
        self.conn.commit()

    @staticmethod
    def _row_to_metric(r: sqlite3.Row) -> PostMetric:
        return PostMetric(
            post_id=r["post_id"], metric_date=r["metric_date"], views=r["views"] or 0,
            visitors=r["visitors"] or 0, search_inflow=r["search_inflow"] or 0,
            likes=r["likes"] or 0, comments=r["comments"] or 0,
            new_neighbors=r["new_neighbors"] or 0, avg_duration_seconds=r["avg_duration_seconds"],
            source=_loads(r["source_json"], {}),
        )

    def get_metrics_for_post(self, post_id: str) -> list[PostMetric]:
        rows = self.conn.execute(
            "SELECT * FROM post_metrics WHERE post_id=? ORDER BY metric_date", (post_id,)
        ).fetchall()
        return [self._row_to_metric(r) for r in rows]

    def get_latest_metric_for_post(self, post_id: str) -> PostMetric | None:
        r = self.conn.execute(
            "SELECT * FROM post_metrics WHERE post_id=? ORDER BY metric_date DESC LIMIT 1",
            (post_id,),
        ).fetchone()
        return self._row_to_metric(r) if r else None

    # ───────────────────────── inflow_keywords ─────────────────────────
    def upsert_inflow_keyword(self, k: InflowKeyword) -> None:
        self.conn.execute(
            """
            INSERT INTO inflow_keywords (post_id, metric_date, keyword, inflow_count, source_json)
            VALUES (?,?,?,?,?)
            ON CONFLICT(post_id, metric_date, keyword) DO UPDATE SET
                inflow_count=excluded.inflow_count, source_json=excluded.source_json
            """,
            (k.post_id, k.metric_date, k.keyword, k.inflow_count, _dumps(k.source)),
        )
        self.conn.commit()

    def get_inflow_keywords_for_post(self, post_id: str) -> list[InflowKeyword]:
        rows = self.conn.execute(
            "SELECT * FROM inflow_keywords WHERE post_id=? ORDER BY inflow_count DESC", (post_id,)
        ).fetchall()
        return [InflowKeyword(post_id=r["post_id"], metric_date=r["metric_date"],
                              keyword=r["keyword"], inflow_count=r["inflow_count"] or 0,
                              source=_loads(r["source_json"], {})) for r in rows]

    def get_all_inflow_keywords(self) -> list[InflowKeyword]:
        rows = self.conn.execute("SELECT * FROM inflow_keywords").fetchall()
        return [InflowKeyword(post_id=r["post_id"], metric_date=r["metric_date"],
                              keyword=r["keyword"], inflow_count=r["inflow_count"] or 0,
                              source=_loads(r["source_json"], {})) for r in rows]

    # ───────────────────────── keyword_research ─────────────────────────
    def upsert_keyword_research(self, kr: KeywordResearch) -> None:
        self.conn.execute(
            """
            INSERT INTO keyword_research (keyword, collected_date, search_demand_score, trend_score,
                trend_direction, shopping_trend_score, shopping_category, blog_document_count,
                competition_score, opportunity_score, top_titles_json, top_urls_json,
                related_keywords_json, source_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(keyword, collected_date) DO UPDATE SET
                search_demand_score=excluded.search_demand_score, trend_score=excluded.trend_score,
                trend_direction=excluded.trend_direction, shopping_trend_score=excluded.shopping_trend_score,
                shopping_category=excluded.shopping_category, blog_document_count=excluded.blog_document_count,
                competition_score=excluded.competition_score, opportunity_score=excluded.opportunity_score,
                top_titles_json=excluded.top_titles_json, top_urls_json=excluded.top_urls_json,
                related_keywords_json=excluded.related_keywords_json, source_json=excluded.source_json
            """,
            (kr.keyword, kr.collected_date, kr.search_demand_score, kr.trend_score,
             kr.trend_direction, kr.shopping_trend_score, kr.shopping_category,
             kr.blog_document_count, kr.competition_score, kr.opportunity_score,
             _dumps(kr.top_titles), _dumps(kr.top_urls), _dumps(kr.related_keywords),
             _dumps(kr.source)),
        )
        self.conn.commit()

    @staticmethod
    def _row_to_research(r: sqlite3.Row) -> KeywordResearch:
        return KeywordResearch(
            keyword=r["keyword"], collected_date=r["collected_date"],
            search_demand_score=r["search_demand_score"], trend_score=r["trend_score"],
            trend_direction=r["trend_direction"], shopping_trend_score=r["shopping_trend_score"],
            shopping_category=r["shopping_category"], blog_document_count=r["blog_document_count"],
            competition_score=r["competition_score"], opportunity_score=r["opportunity_score"],
            top_titles=_loads(r["top_titles_json"], []), top_urls=_loads(r["top_urls_json"], []),
            related_keywords=_loads(r["related_keywords_json"], []),
            source=_loads(r["source_json"], {}),
        )

    def get_fresh_keyword_research(self, keyword: str, fresh_within_days: int) -> KeywordResearch | None:
        """fresh_within_days 이내 가장 최근 조사 결과(없으면 None) — 캐시 재사용용."""
        cutoff = (date.today() - timedelta(days=max(0, fresh_within_days))).isoformat()
        r = self.conn.execute(
            "SELECT * FROM keyword_research WHERE keyword=? AND collected_date>=? "
            "ORDER BY collected_date DESC LIMIT 1",
            (keyword, cutoff),
        ).fetchone()
        return self._row_to_research(r) if r else None

    def get_keyword_research_history(self, keyword: str) -> list[KeywordResearch]:
        rows = self.conn.execute(
            "SELECT * FROM keyword_research WHERE keyword=? ORDER BY collected_date DESC", (keyword,)
        ).fetchall()
        return [self._row_to_research(r) for r in rows]

    # ───────────────────────── keyword_rankings ─────────────────────────
    def insert_keyword_ranking(self, kr: KeywordRanking) -> None:
        self.conn.execute(
            """
            INSERT INTO keyword_rankings (keyword, post_id, post_url, checked_date, is_exposed,
                rank, page, search_result_url, source_json)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (kr.keyword, kr.post_id, kr.post_url, kr.checked_date, 1 if kr.is_exposed else 0,
             kr.rank, kr.page, kr.search_result_url, _dumps(kr.source)),
        )
        self.conn.commit()

    def get_keyword_rankings(self, keyword: str) -> list[KeywordRanking]:
        rows = self.conn.execute(
            "SELECT * FROM keyword_rankings WHERE keyword=? ORDER BY checked_date DESC", (keyword,)
        ).fetchall()
        return [KeywordRanking(
            keyword=r["keyword"], checked_date=r["checked_date"], post_id=r["post_id"],
            post_url=r["post_url"], is_exposed=bool(r["is_exposed"]), rank=r["rank"],
            page=r["page"], search_result_url=r["search_result_url"],
            source=_loads(r["source_json"], {})) for r in rows]

    # ───────────────────────── generated_briefs ─────────────────────────
    def insert_brief(self, b: SeoBrief) -> None:
        self.conn.execute(
            """
            INSERT INTO generated_briefs (brief_id, input_folder, category, detected_topics_json,
                primary_keyword, secondary_keywords_json, avoid_keywords_json, recommended_title,
                title_alternatives_json, selected_tags_json, keyword_scores_json, strategy_reason,
                seo_brief_md)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(brief_id) DO UPDATE SET
                input_folder=excluded.input_folder, category=excluded.category,
                detected_topics_json=excluded.detected_topics_json,
                primary_keyword=excluded.primary_keyword,
                secondary_keywords_json=excluded.secondary_keywords_json,
                avoid_keywords_json=excluded.avoid_keywords_json,
                recommended_title=excluded.recommended_title,
                title_alternatives_json=excluded.title_alternatives_json,
                selected_tags_json=excluded.selected_tags_json,
                keyword_scores_json=excluded.keyword_scores_json,
                strategy_reason=excluded.strategy_reason, seo_brief_md=excluded.seo_brief_md
            """,
            (b.brief_id, b.input_folder, b.category, _dumps(b.detected_topics),
             b.primary_keyword, _dumps(b.secondary_keywords), _dumps(b.avoid_keywords),
             b.recommended_title, _dumps(b.title_alternatives), _dumps(b.selected_tags),
             _dumps(b.keyword_scores), b.strategy_reason, b.seo_brief_md),
        )
        self.conn.commit()

    @staticmethod
    def _row_to_brief(r: sqlite3.Row) -> SeoBrief:
        return SeoBrief(
            brief_id=r["brief_id"], input_folder=r["input_folder"], category=r["category"],
            detected_topics=_loads(r["detected_topics_json"], []),
            primary_keyword=r["primary_keyword"],
            secondary_keywords=_loads(r["secondary_keywords_json"], []),
            avoid_keywords=_loads(r["avoid_keywords_json"], []),
            recommended_title=r["recommended_title"],
            title_alternatives=_loads(r["title_alternatives_json"], []),
            selected_tags=_loads(r["selected_tags_json"], []),
            keyword_scores=_loads(r["keyword_scores_json"], []),
            strategy_reason=r["strategy_reason"], seo_brief_md=r["seo_brief_md"],
        )

    def get_brief(self, brief_id: str) -> SeoBrief | None:
        r = self.conn.execute("SELECT * FROM generated_briefs WHERE brief_id=?", (brief_id,)).fetchone()
        return self._row_to_brief(r) if r else None

    def get_latest_brief_for_folder(self, input_folder: str) -> SeoBrief | None:
        r = self.conn.execute(
            "SELECT * FROM generated_briefs WHERE input_folder=? ORDER BY created_at DESC LIMIT 1",
            (input_folder,),
        ).fetchone()
        return self._row_to_brief(r) if r else None

    def get_recent_briefs(self, limit: int = 20) -> list[SeoBrief]:
        rows = self.conn.execute(
            "SELECT * FROM generated_briefs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_brief(r) for r in rows]

    # ───────────────────────── post_outcomes ─────────────────────────
    def upsert_post_outcome(self, o: PostOutcome) -> None:
        """brief_id 를 논리 키로 1행 유지(1d/3d/7d/30d 컬럼을 점진적으로 채움)."""
        existing = self.conn.execute(
            "SELECT id FROM post_outcomes WHERE brief_id=?", (o.brief_id,)
        ).fetchone()
        if existing:
            self.conn.execute(
                """
                UPDATE post_outcomes SET post_id=?, post_url=?, published_at=?,
                    views_1d=COALESCE(?, views_1d), views_3d=COALESCE(?, views_3d),
                    views_7d=COALESCE(?, views_7d), views_30d=COALESCE(?, views_30d),
                    search_inflow_1d=COALESCE(?, search_inflow_1d),
                    search_inflow_3d=COALESCE(?, search_inflow_3d),
                    search_inflow_7d=COALESCE(?, search_inflow_7d),
                    search_inflow_30d=COALESCE(?, search_inflow_30d),
                    top_inflow_keywords_json=?
                WHERE brief_id=?
                """,
                (o.post_id, o.post_url, o.published_at, o.views_1d, o.views_3d, o.views_7d,
                 o.views_30d, o.search_inflow_1d, o.search_inflow_3d, o.search_inflow_7d,
                 o.search_inflow_30d, _dumps(o.top_inflow_keywords), o.brief_id),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO post_outcomes (brief_id, post_id, post_url, published_at,
                    views_1d, views_3d, views_7d, views_30d, search_inflow_1d, search_inflow_3d,
                    search_inflow_7d, search_inflow_30d, top_inflow_keywords_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (o.brief_id, o.post_id, o.post_url, o.published_at, o.views_1d, o.views_3d,
                 o.views_7d, o.views_30d, o.search_inflow_1d, o.search_inflow_3d,
                 o.search_inflow_7d, o.search_inflow_30d, _dumps(o.top_inflow_keywords)),
            )
        self.conn.commit()

    def get_outcome(self, brief_id: str) -> PostOutcome | None:
        r = self.conn.execute("SELECT * FROM post_outcomes WHERE brief_id=?", (brief_id,)).fetchone()
        if not r:
            return None
        return PostOutcome(
            brief_id=r["brief_id"], post_id=r["post_id"], post_url=r["post_url"],
            published_at=r["published_at"], views_1d=r["views_1d"], views_3d=r["views_3d"],
            views_7d=r["views_7d"], views_30d=r["views_30d"], search_inflow_1d=r["search_inflow_1d"],
            search_inflow_3d=r["search_inflow_3d"], search_inflow_7d=r["search_inflow_7d"],
            search_inflow_30d=r["search_inflow_30d"],
            top_inflow_keywords=_loads(r["top_inflow_keywords_json"], []),
        )
