"""Blog Growth SQLite 스키마 + 연결.

스키마는 사양(README/CLAUDE 작업지시) 그대로다. init_db 는 멱등(IF NOT EXISTS)이라
여러 번 호출해도 안전하다.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id TEXT UNIQUE,
        title TEXT NOT NULL,
        url TEXT,
        category TEXT,
        published_at TEXT,
        updated_at TEXT,
        content_md TEXT,
        content_text TEXT,
        tags_json TEXT,
        media_count INTEGER DEFAULT 0,
        image_count INTEGER DEFAULT 0,
        gif_count INTEGER DEFAULT 0,
        video_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS post_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id TEXT NOT NULL,
        metric_date TEXT NOT NULL,
        views INTEGER DEFAULT 0,
        visitors INTEGER DEFAULT 0,
        search_inflow INTEGER DEFAULT 0,
        likes INTEGER DEFAULT 0,
        comments INTEGER DEFAULT 0,
        new_neighbors INTEGER DEFAULT 0,
        avg_duration_seconds REAL,
        source_json TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(post_id, metric_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS inflow_keywords (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id TEXT NOT NULL,
        metric_date TEXT NOT NULL,
        keyword TEXT NOT NULL,
        inflow_count INTEGER DEFAULT 0,
        source_json TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(post_id, metric_date, keyword)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS keyword_research (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword TEXT NOT NULL,
        collected_date TEXT NOT NULL,
        search_demand_score REAL,
        trend_score REAL,
        trend_direction TEXT,
        shopping_trend_score REAL,
        shopping_category TEXT,
        blog_document_count INTEGER,
        competition_score REAL,
        opportunity_score REAL,
        top_titles_json TEXT,
        top_urls_json TEXT,
        related_keywords_json TEXT,
        source_json TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(keyword, collected_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS keyword_rankings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword TEXT NOT NULL,
        post_id TEXT,
        post_url TEXT,
        checked_date TEXT NOT NULL,
        is_exposed INTEGER DEFAULT 0,
        rank INTEGER,
        page INTEGER,
        search_result_url TEXT,
        source_json TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS generated_briefs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brief_id TEXT UNIQUE NOT NULL,
        input_folder TEXT,
        category TEXT,
        detected_topics_json TEXT,
        primary_keyword TEXT,
        secondary_keywords_json TEXT,
        avoid_keywords_json TEXT,
        recommended_title TEXT,
        title_alternatives_json TEXT,
        selected_tags_json TEXT,
        keyword_scores_json TEXT,
        strategy_reason TEXT,
        seo_brief_md TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS post_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brief_id TEXT NOT NULL,
        post_id TEXT,
        post_url TEXT,
        published_at TEXT,
        views_1d INTEGER,
        views_3d INTEGER,
        views_7d INTEGER,
        views_30d INTEGER,
        search_inflow_1d INTEGER,
        search_inflow_3d INTEGER,
        search_inflow_7d INTEGER,
        search_inflow_30d INTEGER,
        top_inflow_keywords_json TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
]

# 조회 성능용 인덱스(없어도 동작하지만 과거글 많아지면 유용).
INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_posts_category ON posts(category)",
    "CREATE INDEX IF NOT EXISTS idx_metrics_post ON post_metrics(post_id)",
    "CREATE INDEX IF NOT EXISTS idx_inflow_post ON inflow_keywords(post_id)",
    "CREATE INDEX IF NOT EXISTS idx_research_keyword ON keyword_research(keyword)",
    "CREATE INDEX IF NOT EXISTS idx_rankings_keyword ON keyword_rankings(keyword)",
    "CREATE INDEX IF NOT EXISTS idx_outcomes_brief ON post_outcomes(brief_id)",
]


def connect(db_path: Path | str) -> sqlite3.Connection:
    """DB 연결(부모 폴더 자동 생성, Row factory, 외래키 OFF=의도적 느슨 결합)."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """모든 테이블/인덱스를 멱등 생성."""
    cur = conn.cursor()
    for ddl in SCHEMA:
        cur.execute(ddl)
    for ddl in INDEXES:
        cur.execute(ddl)
    conn.commit()


def init_db_file(db_path: Path | str) -> Path:
    """파일 경로로 DB 초기화(편의). 생성된 경로 반환."""
    conn = connect(db_path)
    try:
        init_db(conn)
    finally:
        conn.close()
    return Path(db_path)
