"""네이버 검색광고(SearchAd) keywordstool API 어댑터(선택).

키워드별 월간 검색량(PC/모바일)과 경쟁도(compIdx)를 가져와 검색 수요 점수를 보강한다.
credential(3종)이 없거나 토글이 꺼져 있으면 비활성으로 동작하며, 모든 실패는 잡아서 None 을 돌려준다.

⚠️ access license / secret key / customer id 등 어떤 비밀값도 로그로 찍지 않는다(존재 여부만).
인증 서명은 HMAC-SHA256(secret, "{timestamp}.{method}.{uri}") → base64 로 만든다.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Any

import requests

from ..logging_setup import get_logger
from .config import GrowthConfig

log = get_logger()

_SOURCE = "naver_searchad_api"
_URI = "/keywordstool"


def _coerce_count(val: Any) -> int:
    """monthlyQcCnt 값을 정수로 강제 변환.

    네이버는 검색량이 적으면 '< 10' 같은 문자열을 준다 → 0 으로 본다.
    숫자/숫자문자열은 콤마 제거 후 int. 변환 불가면 0.
    """
    if isinstance(val, bool):  # bool 은 int 의 하위형이라 먼저 거른다
        return 0
    if isinstance(val, (int, float)):
        return max(0, int(val))
    if isinstance(val, str):
        s = val.strip().replace(",", "")
        if not s or s.startswith("<"):  # '< 10' 류
            return 0
        try:
            return max(0, int(float(s)))
        except (TypeError, ValueError):
            return 0
    return 0


class NaverSearchAdClient:
    """SearchAd keywordstool 어댑터. 미구성 시 모든 메서드가 None 을 반환한다."""

    def __init__(self, growth_cfg: GrowthConfig) -> None:
        self.cfg = growth_cfg
        self._timeout = int(growth_cfg.naver_api.get("request_timeout_seconds", 15))
        self._skip_logged = False

    # ── 구성 여부 ──
    def is_configured(self) -> bool:
        """yaml/env 토글 + credential 3종이 모두 갖춰졌을 때만 True."""
        return self.cfg.use_searchad_api()

    # ── 내부: 서명 헤더 ──
    def _signed_headers(self, method: str, uri: str) -> dict[str, str] | None:
        """X-Timestamp/X-API-KEY/X-Customer/X-Signature 헤더 구성. 값은 로깅 금지."""
        access = self.cfg.env("NAVER_SEARCHAD_ACCESS_LICENSE")
        secret = self.cfg.env("NAVER_SEARCHAD_SECRET_KEY")
        customer = self.cfg.env("NAVER_SEARCHAD_CUSTOMER_ID")
        if not (access and secret and customer):
            return None
        timestamp = str(int(time.time() * 1000))
        message = f"{timestamp}.{method}.{uri}"
        signature = base64.b64encode(
            hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")
        return {
            "X-Timestamp": timestamp,
            "X-API-KEY": access,
            "X-Customer": str(customer),
            "X-Signature": signature,
        }

    # ── 공개: 키워드 데이터 ──
    def get_keyword_data(self, keyword: str) -> dict[str, Any] | None:
        """단일 키워드의 월간 검색량/경쟁도 조회. 미구성·실패 시 None(예외 안 던짐)."""
        if not self.is_configured():
            if not self._skip_logged:  # 비활성 안내는 한 번만(비밀값 노출 없음)
                log.info("SearchAd API 미구성 → keywordstool 조회를 건너뜁니다.")
                self._skip_logged = True
            return None

        kw = (keyword or "").strip()
        if not kw:
            return None

        base = self.cfg.env("NAVER_SEARCHAD_BASE_URL")
        if not base:
            log.warning("SearchAd base URL(NAVER_SEARCHAD_BASE_URL)이 없어 조회를 건너뜁니다.")
            return None

        headers = self._signed_headers("GET", _URI)
        if headers is None:
            log.warning("SearchAd credential 이 불완전해 조회를 건너뜁니다.")
            return None

        url = base.rstrip("/") + _URI
        # hintKeywords 는 공백 제거형을 권장(네이버 keywordstool 관례)
        params = {"hintKeywords": kw.replace(" ", ""), "showDetail": "1"}

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=self._timeout)
            if resp.status_code != 200:
                log.warning("SearchAd keywordstool HTTP %s (kw=%s)", resp.status_code, kw)
                return None
            payload = resp.json()
        except requests.RequestException as exc:  # noqa: BLE001
            # 예외 메시지에 URL/헤더가 섞일 수 있어 클래스명만 남긴다(시크릿 노출 방지).
            log.warning("SearchAd 요청 실패(kw=%s): %s", kw, type(exc).__name__)
            return None
        except ValueError as exc:  # JSON 파싱 실패
            log.warning("SearchAd 응답 JSON 파싱 실패(kw=%s): %s", kw, type(exc).__name__)
            return None
        except Exception as exc:  # noqa: BLE001 — 어떤 경우에도 호출자를 죽이지 않는다
            log.warning("SearchAd 조회 중 예외(kw=%s): %s", kw, type(exc).__name__)
            return None

        return self._normalize(kw, payload)

    # ── 내부: 응답 정규화 ──
    def _normalize(self, keyword: str, payload: Any) -> dict[str, Any] | None:
        """keywordList[0] 에서 검색량/경쟁도를 뽑아 표준 dict 로 변환."""
        try:
            items = (payload or {}).get("keywordList") or []
        except AttributeError:
            log.warning("SearchAd 응답 형식이 예상과 다릅니다(kw=%s).", keyword)
            return None
        if not items:
            log.warning("SearchAd keywordList 가 비어 있습니다(kw=%s).", keyword)
            return None

        first = items[0] if isinstance(items[0], dict) else {}
        pc = _coerce_count(first.get("monthlyPcQcCnt"))
        mobile = _coerce_count(first.get("monthlyMobileQcCnt"))
        comp = first.get("compIdx")
        comp_idx = str(comp).strip() if comp not in (None, "") else ""

        return {
            "keyword": keyword,
            "monthly_pc": pc,
            "monthly_mobile": mobile,
            "monthly_total": pc + mobile,
            "comp_idx": comp_idx,
            "source": _SOURCE,
        }
