"""SEO/Blog-Growth 설정 로더.

config/blog_growth.yaml + 코드 기본값(DEFAULTS) + .env 플래그를 합쳐 GrowthConfig 로 제공한다.
기존 blog_automation.config(load_config) 와 독립적인 부가 레이어라 기존 동작에 영향이 없다.

⚠️ API key/secret 값은 절대 로그로 찍지 않는다. 여기서는 '존재 여부'만 노출한다.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]          # 프로젝트 루트
GROWTH_CONFIG_FILE = ROOT / "config" / "blog_growth.yaml"

# config/blog_growth.yaml 이 없거나 일부 키가 비어도 죽지 않도록 코드 기본값을 둔다.
DEFAULTS: dict[str, Any] = {
    "blog_growth": {"enabled": True, "db_path": "data/blog_growth/blog_growth.db"},
    "seo": {
        "enabled": True,
        "max_keyword_candidates": 80,
        "max_selected_secondary_keywords": 5,
        "max_tags": 10,
        "max_title_candidates": 10,
        "max_quality_retry": 2,
        "output_subdir": "",
    },
    "naver_api": {
        "use_open_api": True,
        "use_search_blog_api": True,
        "use_datalab_search_api": True,
        "use_datalab_shopping_api": True,
        "use_searchad_api": False,
        "use_crawling_fallback": True,
        "search_blog_api_url_env": "NAVER_SEARCH_BLOG_API_URL",
        "datalab_search_api_url_env": "NAVER_DATALAB_SEARCH_API_URL",
        "datalab_shopping_api_url_env": "NAVER_DATALAB_SHOPPING_API_URL",
        "request_timeout_seconds": 15,
        "search_blog_display": 20,
        "trend_lookback_months": 12,
        "keyword_cache_fresh_days": 7,
    },
    "crawler": {
        "fallback_enabled": True,
        "min_delay_seconds": 3,
        "max_delay_seconds": 8,
        "daily_keyword_limit": 300,
        "max_search_pages_per_keyword": 3,
        "save_html_snapshots_on_failure": True,
        "sanitize_snapshots": True,
        "failure_log_dir": "logs/seo_crawler_failures",
    },
    "scoring": {
        "search_demand_weight": 0.25,
        "opportunity_weight": 0.25,
        "my_blog_fit_weight": 0.25,
        "content_fit_weight": 0.15,
        "seasonality_weight": 0.10,
    },
    "quality_guard": {
        "min_score_to_pass": 80,
        "max_primary_keyword_repeats": 4,
        "max_secondary_keyword_repeats": 3,
        "min_body_length_chars": 1500,
        "max_body_length_chars": 8000,
    },
}

# .env 의 USE_* 플래그명 → naver_api yaml 키 (env 가 yaml 을 덮어쓴다)
_ENV_FLAG_MAP = {
    "NAVER_KEYWORD_USE_OPEN_API": "use_open_api",
    "NAVER_KEYWORD_USE_SEARCHAD_API": "use_searchad_api",
    "NAVER_KEYWORD_USE_CRAWLING_FALLBACK": "use_crawling_fallback",
}


def _deep_merge(base: dict, over: dict) -> dict:
    """over 를 base 위에 깊은 병합(둘 다 dict 인 키만 재귀)."""
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _as_bool(val: Any, default: bool = False) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on", "y"}


@dataclass
class GrowthConfig:
    """SEO 레이어 통합 설정 + .env 접근 헬퍼."""
    raw: dict[str, Any] = field(default_factory=dict)

    # ── 섹션 접근 ──
    def section(self, name: str) -> dict[str, Any]:
        return self.raw.get(name, {}) or {}

    @property
    def enabled(self) -> bool:
        return _as_bool(self.section("blog_growth").get("enabled", True), True) \
            and _as_bool(self.section("seo").get("enabled", True), True)

    @property
    def db_path(self) -> Path:
        from .. import paths
        rel = (self.section("blog_growth").get("db_path") or "").strip()
        # 절대경로면 그대로, 기본값/미설정이면 워크스페이스 기준, 그 외 커스텀 상대경로는 repo 루트 기준(기존 호환).
        if rel:
            p = Path(rel).expanduser()
            if p.is_absolute():
                return p
            if rel == "data/blog_growth/blog_growth.db":
                return paths.get_seo_db_path()
            return paths.REPO_ROOT / p
        return paths.get_seo_db_path()

    @property
    def seo(self) -> dict[str, Any]:
        return self.section("seo")

    @property
    def scoring(self) -> dict[str, Any]:
        return self.section("scoring")

    @property
    def quality_guard(self) -> dict[str, Any]:
        return self.section("quality_guard")

    @property
    def crawler(self) -> dict[str, Any]:
        return self.section("crawler")

    @property
    def naver_api(self) -> dict[str, Any]:
        return self.section("naver_api")

    def failure_log_dir(self) -> Path:
        from .. import paths
        rel = (self.crawler.get("failure_log_dir") or "").strip()
        if rel:
            p = Path(rel).expanduser()
            if p.is_absolute():
                return p
            if rel == "logs/seo_crawler_failures":
                return paths.get_seo_failure_log_dir()
            return paths.REPO_ROOT / p
        return paths.get_seo_failure_log_dir()

    # ── .env 접근(값은 로깅 금지) ──
    @staticmethod
    def env(name: str, default: str | None = None) -> str | None:
        v = os.getenv(name)
        return v if (v is not None and v != "") else default

    def env_int(self, name: str, default: int) -> int:
        try:
            return int(self.env(name) or default)
        except (TypeError, ValueError):
            return default

    def env_float(self, name: str, default: float) -> float:
        try:
            return float(self.env(name) or default)
        except (TypeError, ValueError):
            return default

    # ── API URL(.env 변수명 → 실제 URL) ──
    def search_blog_api_url(self) -> str | None:
        return self.env(self.naver_api.get("search_blog_api_url_env", "NAVER_SEARCH_BLOG_API_URL"))

    def datalab_search_api_url(self) -> str | None:
        return self.env(self.naver_api.get("datalab_search_api_url_env", "NAVER_DATALAB_SEARCH_API_URL"))

    def datalab_shopping_api_url(self) -> str | None:
        return self.env(self.naver_api.get("datalab_shopping_api_url_env", "NAVER_DATALAB_SHOPPING_API_URL"))

    # ── credential 존재 여부(값 노출 금지) ──
    def has_open_api_credentials(self) -> bool:
        return bool(self.env("NAVER_CLIENT_ID") and self.env("NAVER_CLIENT_SECRET"))

    def has_searchad_credentials(self) -> bool:
        return bool(
            self.env("NAVER_SEARCHAD_ACCESS_LICENSE")
            and self.env("NAVER_SEARCHAD_SECRET_KEY")
            and self.env("NAVER_SEARCHAD_CUSTOMER_ID")
        )

    # ── 동작 토글(yaml 위에 .env USE_* 가 우선) ──
    def use_open_api(self) -> bool:
        return _as_bool(self.naver_api.get("use_open_api", True), True) and self.has_open_api_credentials()

    def use_search_blog_api(self) -> bool:
        return self.use_open_api() and _as_bool(self.naver_api.get("use_search_blog_api", True), True)

    def use_datalab_search_api(self) -> bool:
        return self.use_open_api() and _as_bool(self.naver_api.get("use_datalab_search_api", True), True)

    def use_datalab_shopping_api(self) -> bool:
        return self.use_open_api() and _as_bool(self.naver_api.get("use_datalab_shopping_api", True), True)

    def use_searchad_api(self) -> bool:
        """yaml/env 둘 다 켜져 있고 credential 3종이 모두 있을 때만 True."""
        return _as_bool(self.naver_api.get("use_searchad_api", False), False) and self.has_searchad_credentials()

    def use_crawling_fallback(self) -> bool:
        return _as_bool(self.naver_api.get("use_crawling_fallback", True), True) \
            and _as_bool(self.crawler.get("fallback_enabled", True), True)


def load_growth_config() -> GrowthConfig:
    """blog_growth.yaml + DEFAULTS + .env 플래그를 합쳐 GrowthConfig 반환."""
    load_dotenv(ROOT / ".env")
    raw = copy.deepcopy(DEFAULTS)   # ⚠️ 얕은 복사면 .env 플래그 주입이 모듈전역 DEFAULTS 를 오염시킴
    if GROWTH_CONFIG_FILE.exists():
        with open(GROWTH_CONFIG_FILE, encoding="utf-8") as f:
            file_raw = yaml.safe_load(f) or {}
        raw = _deep_merge(raw, file_raw)

    # .env USE_* 플래그가 있으면 naver_api 위에 덮어쓴다.
    for env_name, key in _ENV_FLAG_MAP.items():
        val = os.getenv(env_name)
        if val is not None and val != "":
            raw["naver_api"][key] = _as_bool(val)

    return GrowthConfig(raw=raw)
