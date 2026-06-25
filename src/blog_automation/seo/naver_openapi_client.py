"""네이버 Open API 클라이언트 — 블로그 검색 + 데이터랩(검색어/쇼핑인사이트) 트렌드.

키워드 수요·경쟁·트렌드를 무료 공식 API 로 수집한다(크롤링은 fallback 모듈 담당).
인증 헤더는 X-Naver-Client-Id / X-Naver-Client-Secret 이며, 값은 .env 에서 읽고 **절대 로깅하지 않는다**.

세 엔드포인트:
  - 블로그 검색: GET, params(query/display/start/sort). 응답 title/description 의 <b> 등 HTML 태그 제거.
  - 데이터랩 검색어 트렌드: POST JSON(startDate/endDate/timeUnit/keywordGroups[, device/ages/gender]).
  - 데이터랩 쇼핑인사이트: POST JSON(위 + category=쇼핑 cat_id). 제품리뷰 글에서만 호출(상위 호출부 책임).

graceful failure 원칙: credential 없음 / HTTP!=200 / JSON 오류 / 네트워크 예외는 모두
경고 로그(시크릿 제외) 후 None 반환 → 호출부가 fallback 으로 우회한다. 절대 raise 하지 않는다.
"""
from __future__ import annotations

from typing import Any

import requests
from bs4 import BeautifulSoup

from ..logging_setup import get_logger
from .config import GrowthConfig

log = get_logger()


def _strip_html(text: str | None) -> str:
    """네이버 응답의 <b></b> 등 HTML 태그/엔티티를 제거해 순수 텍스트로 반환."""
    if not text:
        return ""
    try:
        return BeautifulSoup(text, "html.parser").get_text().strip()
    except Exception:  # noqa: BLE001
        return str(text).strip()


def _to_int(val: Any, default: int = 0) -> int:
    """문자열/숫자 혼재 응답을 안전하게 int 로(파싱 실패 시 default)."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _to_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


class NaverOpenApiClient:
    """네이버 Open API(블로그 검색 + 데이터랩) 호출 래퍼.

    is_available() 가 False(키 없음/토글 off)면 모든 public 메서드는 None 을 돌려준다.
    """

    def __init__(self, growth_cfg: GrowthConfig) -> None:
        self.cfg = growth_cfg
        self._naver_api: dict[str, Any] = growth_cfg.naver_api or {}
        self._timeout = _to_int(self._naver_api.get("request_timeout_seconds", 15), 15)

    # ── 가용성 ──
    def is_available(self) -> bool:
        """Open API 사용 가능 여부(yaml/env 토글 + credential 존재)."""
        try:
            return bool(self.cfg.use_open_api())
        except Exception:  # noqa: BLE001
            return False

    def _auth_headers(self) -> dict[str, str] | None:
        """인증 헤더 생성. 키가 하나라도 없으면 None(값은 로깅 금지)."""
        client_id = self.cfg.env("NAVER_CLIENT_ID")
        client_secret = self.cfg.env("NAVER_CLIENT_SECRET")
        if not client_id or not client_secret:
            return None
        return {
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        }

    # ── 블로그 검색 ──
    def search_blog(
        self,
        query: str,
        display: int = 20,
        start: int = 1,
        sort: str = "sim",
    ) -> dict[str, Any] | None:
        """블로그 검색(GET). 총 문서수(total)와 상위 글 제목/링크를 반환.

        반환: {"keyword","total":int,"items":[{title,link,description,
               bloggername,bloggerlink,postdate}],"source":"naver_blog_search_api"}
        실패 시 None.
        """
        if not self.is_available():
            return None
        url = self.cfg.search_blog_api_url()
        if not url:
            log.warning("[SEO][openapi] 블로그 검색 URL 미설정(NAVER_SEARCH_BLOG_API_URL).")
            return None
        headers = self._auth_headers()
        if not headers:
            log.warning("[SEO][openapi] NAVER_CLIENT_ID/SECRET 없음 — 블로그 검색 생략.")
            return None

        # 네이버 제약: display 1~100, start 1~1000, sort sim|date.
        display = max(1, min(_to_int(display, 20), 100))
        start = max(1, min(_to_int(start, 1), 1000))
        sort = sort if sort in {"sim", "date"} else "sim"
        params = {"query": query, "display": display, "start": start, "sort": sort}

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=self._timeout)
        except requests.RequestException as exc:  # 네트워크/타임아웃
            log.warning("[SEO][openapi] 블로그 검색 네트워크 오류(%s): %s", query, exc.__class__.__name__)
            return None
        except Exception as exc:  # noqa: BLE001
            log.warning("[SEO][openapi] 블로그 검색 예외(%s): %s", query, exc.__class__.__name__)
            return None

        if resp.status_code != 200:
            log.warning("[SEO][openapi] 블로그 검색 HTTP %s (%s).", resp.status_code, query)
            return None

        try:
            data = resp.json()
        except ValueError:
            log.warning("[SEO][openapi] 블로그 검색 JSON 파싱 실패(%s).", query)
            return None
        if not isinstance(data, dict):
            log.warning("[SEO][openapi] 블로그 검색 응답 형식 이상(%s).", query)
            return None

        items: list[dict[str, str]] = []
        for raw in data.get("items", []) or []:
            if not isinstance(raw, dict):
                continue
            items.append(
                {
                    "title": _strip_html(raw.get("title")),
                    "link": (raw.get("link") or "").strip(),
                    "description": _strip_html(raw.get("description")),
                    "bloggername": (raw.get("bloggername") or "").strip(),
                    "bloggerlink": (raw.get("bloggerlink") or "").strip(),
                    "postdate": (raw.get("postdate") or "").strip(),
                }
            )

        return {
            "keyword": query,
            "total": _to_int(data.get("total"), 0),
            "items": items,
            "source": "naver_blog_search_api",
        }

    # ── 데이터랩 공통 ──
    def _datalab_post(
        self,
        url: str | None,
        body: dict[str, Any],
        *,
        source: str,
        label: str,
    ) -> dict[str, Any] | None:
        """데이터랩(검색어/쇼핑) 공통 POST + 정규화. 실패 시 None."""
        if not url:
            log.warning("[SEO][openapi] %s URL 미설정.", label)
            return None
        headers = self._auth_headers()
        if not headers:
            log.warning("[SEO][openapi] NAVER_CLIENT_ID/SECRET 없음 — %s 생략.", label)
            return None
        headers = {**headers, "Content-Type": "application/json"}

        try:
            resp = requests.post(url, headers=headers, json=body, timeout=self._timeout)
        except requests.RequestException as exc:
            log.warning("[SEO][openapi] %s 네트워크 오류: %s", label, exc.__class__.__name__)
            return None
        except Exception as exc:  # noqa: BLE001
            log.warning("[SEO][openapi] %s 예외: %s", label, exc.__class__.__name__)
            return None

        if resp.status_code != 200:
            log.warning("[SEO][openapi] %s HTTP %s.", label, resp.status_code)
            return None

        try:
            data = resp.json()
        except ValueError:
            log.warning("[SEO][openapi] %s JSON 파싱 실패.", label)
            return None
        if not isinstance(data, dict):
            log.warning("[SEO][openapi] %s 응답 형식 이상.", label)
            return None

        results: list[dict[str, Any]] = []
        for grp in data.get("results", []) or []:
            if not isinstance(grp, dict):
                continue
            points: list[dict[str, Any]] = []
            for pt in grp.get("data", []) or []:
                if not isinstance(pt, dict):
                    continue
                points.append(
                    {
                        "period": (pt.get("period") or "").strip(),
                        "ratio": _to_float(pt.get("ratio"), 0.0),
                    }
                )
            results.append({"title": (grp.get("title") or "").strip(), "data": points})

        return {"results": results, "source": source}

    # ── 데이터랩 검색어 트렌드 ──
    def get_search_trend(
        self,
        keyword_groups: list[dict[str, Any]],
        start_date: str,
        end_date: str,
        time_unit: str = "month",
        device: str | None = None,
        ages: list[str] | None = None,
        gender: str | None = None,
    ) -> dict[str, Any] | None:
        """데이터랩 검색어 트렌드(POST).

        keyword_groups = [{"groupName":str,"keywords":[str]}]
        반환: {"results":[{"title","data":[{"period","ratio"}]}],
               "source":"naver_datalab_search_api"} / 실패 None.
        """
        if not self.is_available():
            return None
        if not keyword_groups:
            return None
        body = self._build_datalab_body(
            start_date, end_date, time_unit, keyword_groups,
            device=device, ages=ages, gender=gender,
        )
        return self._datalab_post(
            self.cfg.datalab_search_api_url(),
            body,
            source="naver_datalab_search_api",
            label="데이터랩 검색어트렌드",
        )

    # ── 데이터랩 쇼핑인사이트 ──
    def get_shopping_trend(
        self,
        category: str,
        keyword_groups: list[dict[str, Any]],
        start_date: str,
        end_date: str,
        time_unit: str = "month",
        device: str | None = None,
        ages: list[str] | None = None,
        gender: str | None = None,
    ) -> dict[str, Any] | None:
        """데이터랩 쇼핑인사이트 키워드 트렌드(POST).

        category = 네이버 쇼핑 cat_id(constants.SHOPPING_CATEGORY_CODES 값).
        반환: {"results":[...],"source":"naver_datalab_shopping_api"} / 실패 None.
        """
        if not self.is_available():
            return None
        if not category or not keyword_groups:
            return None
        body = self._build_datalab_body(
            start_date, end_date, time_unit, keyword_groups,
            category=category, device=device, ages=ages, gender=gender,
        )
        return self._datalab_post(
            self.cfg.datalab_shopping_api_url(),
            body,
            source="naver_datalab_shopping_api",
            label="데이터랩 쇼핑인사이트",
        )

    # ── 데이터랩 요청 바디 빌더 ──
    @staticmethod
    def _build_datalab_body(
        start_date: str,
        end_date: str,
        time_unit: str,
        keyword_groups: list[dict[str, Any]],
        *,
        category: str | None = None,
        device: str | None = None,
        ages: list[str] | None = None,
        gender: str | None = None,
    ) -> dict[str, Any]:
        """네이버 데이터랩 스펙에 맞춘 POST 바디 생성(선택 필드는 값 있을 때만 포함)."""
        time_unit = time_unit if time_unit in {"date", "week", "month"} else "month"
        body: dict[str, Any] = {
            "startDate": start_date,
            "endDate": end_date,
            "timeUnit": time_unit,
            "keywordGroups": keyword_groups,
        }
        if category:
            body["category"] = category
        if device:
            body["device"] = device
        if ages:
            body["ages"] = ages
        if gender:
            body["gender"] = gender
        return body
