"""Blog Growth DB 초기화 스크립트.

사용:
    python scripts/init_blog_growth_db.py
또는 CLI:
    python main.py seo-init-db

config/blog_growth.yaml 의 blog_growth.db_path(기본 data/blog_growth/blog_growth.db)에
모든 테이블/인덱스를 멱등 생성한다. 여러 번 실행해도 안전(IF NOT EXISTS).
"""
from __future__ import annotations

import sys
from pathlib import Path

# src/ 를 import 경로에 추가(main.py 와 동일 방식)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blog_automation.seo.config import load_growth_config
from blog_automation.seo.db import init_db_file


def main() -> int:
    cfg = load_growth_config()
    path = init_db_file(cfg.db_path)
    print(f"[OK] blog_growth DB initialized → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
