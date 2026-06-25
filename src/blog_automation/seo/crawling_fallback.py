from __future__ import annotations

"""크롤링 폴백 — Open API 가 못 주거나(or 실패/레이트리밋) 한 데이터를 가벼운 requests 로 보충.

Open API(블로그 검색/데이터랩)가 1순위이며, 이 모듈은 어디까지나 best-effort 보조다.
  - blog_search_counts(keyword) : 네이버 검색 결과에서 대략적 문서 수 + 상위 제목/URL 몇 개 파싱
  - related_keywords(keyword)   : 연관/자동완성 키워드 best-effort(없으면 [])

⚠️ 셀렉터는 깨지기 쉽다 → try/except 로 감싸고 실패 시 None/[] 반환(절대 예외 전파 금지).
⚠️ 레이트리밋: 인스턴스별 사용 카운터로 daily_keyword_limit 을 지키고, 매 네트워크 호출 전
   random.uniform(min_delay, max_delay) 만큼 쉰다. 예산이 0 이하면 호출하지 않고 None/[] 반환.
⚠️ 실패 스냅샷은 저장 전 반드시 sanitize_html_snapshot 으로 민감정보를 가린다.
"""

import json
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from ..logging_setup import get_logger
from .config import GrowthConfig
from .html_sanitizer import sanitize_html_snapshot

log = get_logger()

# 모바일 검색이 PC 보다 마크업이 단순해 파싱이 안정적 → 모바일 UA + 엔드포인트를 우선 쓴다.
_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": "https://m.search.naver.com/",
}

_MOBILE_BLOG_SEARCH = "https://m.search.naver.com/search.naver?where=m_blog&query={q}"
_PC_BLOG_SEARCH = "https://search.naver.com/search.naver?where=blog&query={q}"
# 연관검색어 자동완성(JSONP). 실패하면 빈 리스트로 떨어진다.
_AUTOCOMPLETE = (
    "https://ac.search.naver.com/nx/ac?q={q}&con=0&frm=nv&ans=2&r_format=json"
    "&r_enc=UTF-8&r_unicode=0&t_koreng=1&st=100"
)

# "블로그 1-10 / 12,345건" 같은 결과 수 표기에서 숫자만 뽑는 후보 패턴들.
_TOTAL_PATTERNS = [
    re.compile(r'약?\s*([\d,]+)\s*건'),
    re.compile(r'총\s*([\d,]+)\s*건'),
    re.compile(r'"total"\s*:\s*([\d,]+)'),
    re.compile(r'검색결과\D{0,20}?([\d,]+)\s*건'),
]


class CrawlingFallback:
    """가벼운 requests 기반 크롤링 폴백(인스턴스별 일일 예산 관리)."""

    def __init__(self, growth_cfg: GrowthConfig) -> None:
        self.cfg = growth_cfg
        self._crawler = growth_cfg.crawler or {}
        self._used = 0  # 이번 실행에서 소비한 키워드(네트워크 라운드) 수
        try:
            self._session = requests.Session()
            self._session.headers.update(_HEADERS)
        except Exception:  # noqa: BLE001
            self._session = None

    # ── 가용성/예산 ──────────────────────────────────────────────
    def is_enabled(self) -> bool:
        """yaml/env 플래그상 크롤링 폴백을 써도 되는지."""
        try:
            return bool(self.cfg.use_crawling_fallback())
        except Exception:  # noqa: BLE001
            return False

    def remaining_budget(self) -> int:
        """daily_keyword_limit 에서 이번 실행 사용분을 뺀 남은 예산(0 미만이면 0)."""
        try:
            limit = int(self._crawler.get("daily_keyword_limit", 300))
        except (TypeError, ValueError):
            limit = 300
        return max(0, limit - self._used)

    # ── 내부 헬퍼 ────────────────────────────────────────────────
    def _delay(self) -> None:
        """매 네트워크 호출 전 사람처럼 랜덤 지연(과도한 요청으로 인한 차단 회피)."""
        try:
            lo = float(self._crawler.get("min_delay_seconds", 3))
            hi = float(self._crawler.get("max_delay_seconds", 8))
        except (TypeError, ValueError):
            lo, hi = 3.0, 8.0
        if hi < lo:
            lo, hi = hi, lo
        try:
            time.sleep(random.uniform(lo, hi))
        except Exception:  # noqa: BLE001
            pass

    def _timeout(self) -> int:
        try:
            return int((self.cfg.naver_api or {}).get("request_timeout_seconds", 15))
        except (TypeError, ValueError):
            return 15

    def _fetch(self, url: str) -> str | None:
        """예산 확인 → 지연 → GET. 실패하면 경고만 남기고 None(예외 전파 금지)."""
        if not self.is_enabled():
            return None
        if self.remaining_budget() <= 0:
            log.warning("[seo-fallback] 일일 크롤링 예산 소진 — 호출 생략")
            return None
        if self._session is None:
            return None
        self._used += 1  # 라운드 단위로 예산 차감(성공/실패 무관하게 시도 1회 = 1소비)
        self._delay()
        try:
            resp = self._session.get(url, timeout=self._timeout())
            if resp.status_code != 200:
                log.warning("[seo-fallback] HTTP %s: %s", resp.status_code, url)
                return None
            return resp.text
        except Exception as e:  # noqa: BLE001
            log.warning("[seo-fallback] 요청 실패(%s): %s", type(e).__name__, url)
            return None

    @staticmethod
    def _parse_total(html: str) -> int | None:
        """결과 페이지 텍스트에서 대략적 문서 수를 추출(못 찾으면 None)."""
        for pat in _TOTAL_PATTERNS:
            m = pat.search(html)
            if m:
                try:
                    return int(m.group(1).replace(",", ""))
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _parse_results(html: str) -> tuple[list[str], list[str]]:
        """검색 결과에서 블로그 글 상위 제목/URL 을 best-effort 로 수집."""
        titles: list[str] = []
        urls: list[str] = []
        try:
            from bs4 import BeautifulSoup  # 지연 임포트(import 시점 실패 방지)
        except Exception:  # noqa: BLE001
            return titles, urls
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:  # noqa: BLE001
            return titles, urls

        # 셀렉터는 깨지기 쉬워 여러 후보를 순차 시도한다.
        selectors = [
            "a.title_link",
            "a.api_txt_lines.total_tit",
            "a.total_tit",
            ".title_area a",
            ".total_wrap a.link_tit",
        ]
        seen: set[str] = set()
        for sel in selectors:
            try:
                anchors = soup.select(sel)
            except Exception:  # noqa: BLE001
                continue
            for a in anchors:
                try:
                    href = (a.get("href") or "").strip()
                    text = a.get_text(strip=True)
                except Exception:  # noqa: BLE001
                    continue
                if not href or not text:
                    continue
                if not href.startswith("http"):
                    continue
                if "blog.naver.com" not in href and "blog.me" not in href:
                    continue
                if href in seen:
                    continue
                seen.add(href)
                titles.append(text)
                urls.append(href)
                if len(urls) >= 5:
                    break
            if urls:
                break
        return titles[:5], urls[:5]

    # ── 공개 API ────────────────────────────────────────────────
    def blog_search_counts(self, keyword: str) -> dict | None:
        """네이버 블로그 검색에서 대략적 문서 수 + 상위 제목/URL 을 best-effort 로 반환.

        반환: {"total": int|None, "top_titles": [str], "top_urls": [str]} 또는 None.
        모바일 결과를 먼저 시도하고, 결과 수가 안 잡히면 PC 결과로 한 번 더 시도한다.
        """
        if not keyword or not keyword.strip():
            return None
        from urllib.parse import quote

        q = quote(keyword.strip())
        html = self._fetch(_MOBILE_BLOG_SEARCH.format(q=q))
        if not html:
            return None

        total = self._parse_total(html)
        titles, urls = self._parse_results(html)

        # 모바일에서 결과 수를 못 잡으면 PC 검색으로 보완(예산 허용 시).
        if total is None and self.remaining_budget() > 0:
            pc_html = self._fetch(_PC_BLOG_SEARCH.format(q=q))
            if pc_html:
                total = self._parse_total(pc_html)
                if not urls:
                    titles, urls = self._parse_results(pc_html)
                if total is None and not urls:
                    self.save_failure_snapshot(f"blog_search_{keyword}", pc_html)

        if total is None and not urls:
            log.warning("[seo-fallback] 블로그 검색 파싱 실패: %s", keyword)
            self.save_failure_snapshot(f"blog_search_{keyword}", html)

        return {"total": total, "top_titles": titles, "top_urls": urls}

    def related_keywords(self, keyword: str) -> list[str]:
        """자동완성/연관검색어 best-effort. 못 가져오면 빈 리스트."""
        if not keyword or not keyword.strip():
            return []
        from urllib.parse import quote

        q = quote(keyword.strip())
        text = self._fetch(_AUTOCOMPLETE.format(q=q))
        if not text:
            return []
        return self._parse_autocomplete(text, keyword)

    @staticmethod
    def _parse_autocomplete(text: str, keyword: str) -> list[str]:
        """네이버 자동완성 JSON(items 중첩 배열)에서 키워드 문자열만 평탄화."""
        out: list[str] = []
        try:
            data: Any = json.loads(text)
        except Exception:  # noqa: BLE001
            return out
        try:
            items = data.get("items") if isinstance(data, dict) else None
            if not items:
                return out
            for group in items:
                if not isinstance(group, list):
                    continue
                for row in group:
                    cand: str | None = None
                    if isinstance(row, list) and row:
                        first = row[0]
                        cand = first if isinstance(first, str) else None
                    elif isinstance(row, str):
                        cand = row
                    if not cand:
                        continue
                    cand = cand.strip()
                    if not cand or cand == keyword.strip():
                        continue
                    if cand not in out:
                        out.append(cand)
        except Exception:  # noqa: BLE001
            return out
        return out[:20]

    # ── 실패 스냅샷(self-healing 진단용) ──────────────────────────
    def save_failure_snapshot(
        self, name: str, html: str, screenshot_bytes: bytes | None = None
    ) -> Path | None:
        """실패 HTML(민감정보 제거) + (있으면) 스크린샷을 failure_log_dir 아래 저장.

        반환: 저장한 HTML 스냅샷 경로(실패 시 None). 절대 예외를 전파하지 않는다.
        """
        try:
            if not (self._crawler.get("save_html_snapshots_on_failure", True)):
                return None
            base_dir = self.cfg.failure_log_dir()
            base_dir.mkdir(parents=True, exist_ok=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            safe = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", str(name or "snapshot")).strip("_") or "snapshot"
            stem = f"{safe}_{ts}"

            html_path = base_dir / f"{stem}.html"
            redacted = sanitize_html_snapshot(html or "")
            html_path.write_text(redacted, encoding="utf-8")

            if screenshot_bytes:
                try:
                    (base_dir / f"{stem}.png").write_bytes(screenshot_bytes)
                except Exception:  # noqa: BLE001
                    pass

            log.warning("[seo-fallback] 실패 스냅샷 저장: %s", html_path)
            return html_path
        except Exception as e:  # noqa: BLE001
            log.warning("[seo-fallback] 스냅샷 저장 실패(%s)", type(e).__name__)
            return None
