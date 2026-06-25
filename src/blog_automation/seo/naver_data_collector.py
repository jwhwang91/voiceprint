from __future__ import annotations

"""키워드별 수요/경쟁도/트렌드 수집 오케스트레이터.

소스 우선순위(키워드 1개당):
  캐시(repo) → 블로그 검색 API(총건수+상위제목) → DataLab 검색 트렌드
  → (제품리뷰일 때만) 쇼핑인사이트 트렌드 → (설정 시) 검색광고 키워드 도구
  → 부족분 크롤링 fallback → 0~100 정규화 → repo.upsert_keyword_research.

한 키워드가 실패해도 전체가 죽지 않게 try/except 로 감싸고 다음 키워드로 넘어간다.
⚠️ API key/secret/cookie 는 절대 로깅하지 않는다(키워드 문자열만 로깅).
"""

import math
from datetime import date, timedelta
from typing import Any

from ..logging_setup import get_logger
from . import constants
from .config import GrowthConfig
from .crawling_fallback import CrawlingFallback
from .models import KeywordResearch, TopicExtraction
from .naver_openapi_client import NaverOpenApiClient
from .naver_searchad_client import NaverSearchAdClient
from .repository import Repository

log = get_logger()


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """0~100(기본) 범위로 클램프."""
    return max(lo, min(hi, v))


def _safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class NaverDataCollector:
    """OpenAPI/검색광고/크롤링 fallback 을 묶어 키워드 리서치를 수집·정규화한다."""

    def __init__(
        self,
        growth_cfg: GrowthConfig,
        repo: Repository,
        openapi: NaverOpenApiClient | None = None,
        searchad: NaverSearchAdClient | None = None,
        fallback: CrawlingFallback | None = None,
    ) -> None:
        self.cfg = growth_cfg
        self.repo = repo
        # 주입 안 된 클라이언트는 내부에서 생성(생성 자체는 실패하지 않는 설계).
        self.openapi = openapi if openapi is not None else NaverOpenApiClient(growth_cfg)
        self.searchad = searchad if searchad is not None else NaverSearchAdClient(growth_cfg)
        self.fallback = fallback if fallback is not None else CrawlingFallback(growth_cfg)

        api = growth_cfg.naver_api
        self._display = int(api.get("search_blog_display", 20) or 20)
        self._lookback_months = int(api.get("trend_lookback_months", 12) or 12)
        self._cache_fresh_days = int(api.get("keyword_cache_fresh_days", 7) or 7)

    # ───────────────────────── 공개 API ─────────────────────────

    def collect(
        self,
        keywords: list[str],
        topic: TopicExtraction | None = None,
        use_cache: bool = True,
    ) -> list[KeywordResearch]:
        """여러 키워드를 순차 수집. 개별 실패는 건너뛰고 나머지는 진행."""
        out: list[KeywordResearch] = []
        seen: set[str] = set()
        for kw in keywords or []:
            k = (kw or "").strip()
            if not k or k in seen:
                continue
            seen.add(k)
            try:
                out.append(self.collect_one(k, topic=topic, use_cache=use_cache))
            except Exception as exc:  # noqa: BLE001
                # 여기까지 예외가 올라오면 안 되지만 최후 방어선.
                log.warning("[SEO] 키워드 수집 실패(스킵): %s (%s)", k, type(exc).__name__)
        return out

    def collect_one(
        self,
        keyword: str,
        topic: TopicExtraction | None = None,
        use_cache: bool = True,
    ) -> KeywordResearch:
        """키워드 1개 수집. 어떤 단계가 실패해도 가능한 데이터로 정규화해 반환."""
        kw = (keyword or "").strip()
        today = date.today().isoformat()
        log.info("[SEO] 키워드 리서치 시작: %s", kw)

        # ── 0) 캐시 ──
        if use_cache:
            cached = self._read_cache(kw)
            if cached is not None:
                log.info("[SEO] 캐시 사용: %s", kw)
                return cached

        # 누적 수집 상태(소스별 성공 여부 → provenance 로 기록).
        provenance: dict[str, Any] = {"sources": []}
        blog_total: int | None = None
        top_titles: list[str] = []
        top_urls: list[str] = []
        related: list[str] = []
        trend_ratios: list[float] = []
        shopping_ratios: list[float] = []
        searchad_total: int | None = None
        searchad_comp: str | None = None
        shopping_cat_id: str | None = None

        # ── 1) 블로그 검색(총건수 + 상위 제목/URL) ──
        blog = self._blog_search(kw)
        if blog is not None:
            blog_total = blog.get("total")
            for it in (blog.get("items") or [])[: self._display]:
                t = (it.get("title") or "").strip()
                u = (it.get("link") or "").strip()
                if t:
                    top_titles.append(t)
                if u:
                    top_urls.append(u)
            provenance["sources"].append("blog_search")
            provenance["blog_total"] = blog_total

        # ── 2) DataLab 검색 트렌드 ──
        trend = self._search_trend(kw)
        if trend:
            trend_ratios = trend
            provenance["sources"].append("datalab_search")

        # ── 3) 쇼핑인사이트(제품 리뷰일 때만) ──
        if topic is not None and getattr(topic, "is_product_review", False):
            shopping_cat_id = self._resolve_shopping_cat_id(topic)
            if shopping_cat_id:
                shop = self._shopping_trend(kw, shopping_cat_id)
                if shop:
                    shopping_ratios = shop
                    provenance["sources"].append("datalab_shopping")
                    provenance["shopping_cat_id"] = shopping_cat_id

        # ── 4) 검색광고 키워드 도구(설정 시) ──
        ad = self._searchad(kw)
        if ad is not None:
            searchad_total = ad.get("monthly_total")
            searchad_comp = ad.get("comp_idx")
            provenance["sources"].append("searchad")
            provenance["searchad_monthly_total"] = searchad_total

        # ── 5) 부족분 크롤링 fallback ──
        # 블로그 총건수 또는 상위 제목이 비었을 때만 보충 시도.
        if blog_total is None or not top_titles:
            fb = self._fallback_counts(kw)
            if fb is not None:
                if blog_total is None and fb.get("total") is not None:
                    blog_total = fb.get("total")
                if not top_titles and fb.get("top_titles"):
                    top_titles = list(fb.get("top_titles") or [])[: self._display]
                if not top_urls and fb.get("top_urls"):
                    top_urls = list(fb.get("top_urls") or [])[: self._display]
                provenance["sources"].append("crawl_blog_counts")
        if not related:
            rel = self._fallback_related(kw)
            if rel:
                related = rel
                provenance["sources"].append("crawl_related")

        # ── 6) 정규화 → KeywordResearch ──
        research = self._normalize(
            keyword=kw,
            collected_date=today,
            blog_total=blog_total,
            top_titles=top_titles,
            top_urls=top_urls,
            related=related,
            trend_ratios=trend_ratios,
            shopping_ratios=shopping_ratios,
            shopping_cat_id=shopping_cat_id,
            searchad_total=searchad_total,
            searchad_comp=searchad_comp,
            provenance=provenance,
        )

        # ── 7) 저장(실패해도 결과는 반환) ──
        try:
            self.repo.upsert_keyword_research(research)
        except Exception as exc:  # noqa: BLE001
            log.warning("[SEO] 리서치 저장 실패(무시): %s (%s)", kw, type(exc).__name__)

        log.info("[SEO] 키워드 리서치 완료: %s (sources=%s)", kw, ",".join(provenance["sources"]) or "none")
        return research

    # ───────────────────────── 단계별 래퍼(모두 graceful) ─────────────────────────

    def _read_cache(self, kw: str) -> KeywordResearch | None:
        try:
            return self.repo.get_fresh_keyword_research(kw, self._cache_fresh_days)
        except Exception as exc:  # noqa: BLE001
            log.warning("[SEO] 캐시 조회 실패(무시): %s (%s)", kw, type(exc).__name__)
            return None

    def _blog_search(self, kw: str) -> dict | None:
        try:
            if not self.openapi.is_available():
                return None
            return self.openapi.search_blog(kw, display=self._display)
        except Exception as exc:  # noqa: BLE001
            log.warning("[SEO] 블로그 검색 실패(무시): %s (%s)", kw, type(exc).__name__)
            return None

    def _search_trend(self, kw: str) -> list[float]:
        """DataLab 검색 트렌드 → ratio 리스트(시간순). 실패/없음 시 []."""
        try:
            if not self.openapi.is_available():
                return []
            start, end = self._trend_window()
            groups = [{"groupName": kw, "keywords": [kw]}]
            res = self.openapi.get_search_trend(groups, start, end, time_unit="month")
            return self._extract_ratios(res)
        except Exception as exc:  # noqa: BLE001
            log.warning("[SEO] 검색 트렌드 실패(무시): %s (%s)", kw, type(exc).__name__)
            return []

    def _shopping_trend(self, kw: str, cat_id: str) -> list[float]:
        try:
            if not self.openapi.is_available():
                return []
            start, end = self._trend_window()
            groups = [{"groupName": kw, "keywords": [kw]}]
            res = self.openapi.get_shopping_trend(cat_id, groups, start, end, time_unit="month")
            return self._extract_ratios(res)
        except Exception as exc:  # noqa: BLE001
            log.warning("[SEO] 쇼핑 트렌드 실패(무시): %s (%s)", kw, type(exc).__name__)
            return []

    def _searchad(self, kw: str) -> dict | None:
        try:
            if not self.searchad.is_configured():
                return None
            return self.searchad.get_keyword_data(kw)
        except Exception as exc:  # noqa: BLE001
            log.warning("[SEO] 검색광고 조회 실패(무시): %s (%s)", kw, type(exc).__name__)
            return None

    def _fallback_counts(self, kw: str) -> dict | None:
        try:
            if not self.fallback.is_enabled() or self.fallback.remaining_budget() <= 0:
                return None
            return self.fallback.blog_search_counts(kw)
        except Exception as exc:  # noqa: BLE001
            log.warning("[SEO] fallback 카운트 실패(무시): %s (%s)", kw, type(exc).__name__)
            return None

    def _fallback_related(self, kw: str) -> list[str]:
        try:
            if not self.fallback.is_enabled() or self.fallback.remaining_budget() <= 0:
                return []
            return list(self.fallback.related_keywords(kw) or [])
        except Exception as exc:  # noqa: BLE001
            log.warning("[SEO] fallback 연관검색어 실패(무시): %s (%s)", kw, type(exc).__name__)
            return []

    # ───────────────────────── 보조 계산 ─────────────────────────

    def _trend_window(self) -> tuple[str, str]:
        """트렌드 조회 구간(end=오늘, start=오늘 - 약 30*lookback 일). 'YYYY-MM-DD'."""
        end_d = date.today()
        start_d = end_d - timedelta(days=30 * max(1, self._lookback_months))
        return start_d.isoformat(), end_d.isoformat()

    @staticmethod
    def _extract_ratios(res: dict | None) -> list[float]:
        """정규화된 DataLab 응답에서 첫 결과의 ratio 시계열을 시간순으로 추출."""
        if not res:
            return []
        results = res.get("results") or []
        if not results:
            return []
        data = results[0].get("data") or []
        ratios: list[float] = []
        for pt in data:
            r = _safe_float(pt.get("ratio"))
            if r is not None:
                ratios.append(r)
        return ratios

    @staticmethod
    def _resolve_shopping_cat_id(topic: TopicExtraction) -> str | None:
        """topic.category → 쇼핑 카테고리명 → cat_id 문자열(없으면 None)."""
        cat = getattr(topic, "category", None)
        shop_name = constants.CATEGORY_TO_SHOPPING.get(cat or "")
        if not shop_name:
            return None
        return constants.SHOPPING_CATEGORY_CODES.get(shop_name)

    # ───────────────────────── 정규화(0~100) ─────────────────────────

    def _normalize(
        self,
        *,
        keyword: str,
        collected_date: str,
        blog_total: int | None,
        top_titles: list[str],
        top_urls: list[str],
        related: list[str],
        trend_ratios: list[float],
        shopping_ratios: list[float],
        shopping_cat_id: str | None,
        searchad_total: int | None,
        searchad_comp: str | None,
        provenance: dict[str, Any],
    ) -> KeywordResearch:
        """수집 원자료 → 0~100 점수로 정규화. 부족한 값은 None 으로 둔다."""

        # ── trend_score / trend_direction (검색 트렌드 ratio 기반) ──
        trend_score: float | None = None
        trend_direction: str | None = None
        if trend_ratios:
            recent = trend_ratios[-3:] if len(trend_ratios) >= 3 else trend_ratios
            avg_recent = sum(recent) / len(recent)
            peak = max(trend_ratios) or 0.0
            # DataLab ratio 는 그룹 내 최대=100 스케일이라 그대로 0~100 으로 본다.
            trend_score = _clamp(avg_recent if peak else 0.0)
            first, last = trend_ratios[0], trend_ratios[-1]
            if first <= 0:
                trend_direction = "up" if last > 0 else "flat"
            elif last > first * 1.1:
                trend_direction = "up"
            elif last < first * 0.9:
                trend_direction = "down"
            else:
                trend_direction = "flat"

        # ── shopping_trend_score ──
        shopping_trend_score: float | None = None
        if shopping_ratios:
            recent = shopping_ratios[-3:] if len(shopping_ratios) >= 3 else shopping_ratios
            shopping_trend_score = _clamp(sum(recent) / len(recent))

        # ── competition_score (블로그 문서 수 ↑ → 경쟁 ↑, 0~100) ──
        competition_score: float | None = None
        if blog_total is not None and blog_total >= 0:
            # log10 스케일: 1만건≈40, 10만≈53, 100만≈67, 1000만≈80.
            competition_score = _clamp(math.log10(blog_total + 1) * (100.0 / 7.0))

        # ── search_demand_score (검색광고 월검색량 우선, 없으면 블로그+트렌드 proxy) ──
        search_demand_score: float | None = None
        demand_parts: list[float] = []
        if searchad_total is not None and searchad_total >= 0:
            # 월검색량 log 스케일: 1천≈37, 1만≈50, 10만≈62, 100만≈75.
            demand_parts.append(_clamp(math.log10(searchad_total + 1) * (100.0 / 8.0)))
        if blog_total is not None and blog_total >= 0:
            # 문서가 어느 정도 쌓였다는 건 수요가 있다는 약한 신호(상한 70).
            demand_parts.append(_clamp(math.log10(blog_total + 1) * (100.0 / 10.0), 0.0, 70.0))
        if trend_score is not None:
            demand_parts.append(trend_score)
        if demand_parts:
            search_demand_score = _clamp(sum(demand_parts) / len(demand_parts))

        # ── opportunity_score = 정규화수요 / log(1+문서수) → 0~100 스케일 ──
        opportunity_score: float | None = None
        if search_demand_score is not None:
            docs = blog_total if (blog_total is not None and blog_total >= 0) else 0
            denom = math.log(1 + docs) if docs > 0 else 1.0
            raw = search_demand_score / denom if denom > 0 else search_demand_score
            # raw 는 수요(0~100)를 log(문서수)로 나눈 값 → 약 0~100 범위로 스케일.
            opportunity_score = _clamp(raw * 7.0)

        # ── provenance 마무리(점수 산출에 쓴 원자료 메타) ──
        src = dict(provenance)
        src["competition_comp_idx"] = searchad_comp
        src["trend_points"] = len(trend_ratios)
        src["shopping_points"] = len(shopping_ratios)

        return KeywordResearch(
            keyword=keyword,
            collected_date=collected_date,
            search_demand_score=search_demand_score,
            trend_score=trend_score,
            trend_direction=trend_direction,
            shopping_trend_score=shopping_trend_score,
            shopping_category=shopping_cat_id,
            blog_document_count=blog_total,
            competition_score=competition_score,
            opportunity_score=opportunity_score,
            top_titles=top_titles[: self._display],
            top_urls=top_urls[: self._display],
            related_keywords=related,
            source=src,
        )
