"""블로그 통계 수집기(Playwright, best-effort).

내 블로그 관리자(통계) 화면에서 글별 조회수/방문자/검색유입/유입 키워드를 긁어
repository(PostMetric / InflowKeyword)에 upsert 한다. SEO 점수의 'my_blog_fit'·
historical_performance·outcome_tracker 가 이 데이터를 먹는다.

⚠️ 통계 화면의 실제 DOM 셀렉터는 **미확정**이다(config/selectors.yaml 에 blog_stats 섹션이
   아직 없거나 값이 전부 null/TODO). 그래서 이 모듈은 place_inserter 와 동일한
   self-healing 관례로 동작한다:
     1) selectors.yaml 의 blog_stats.* 가 있으면 그걸 우선 사용.
     2) 없거나(=null) 추출이 실패하면, 그 시점의 sanitize 된 HTML 스냅샷 + 스크린샷 +
        실패 셀렉터 메모를 growth_cfg.failure_log_dir() 아래에 떨어뜨리고(_dump_failure)
        로그만 남긴 뒤 **계속 진행**한다(통계 1개 못 긁었다고 죽지 않는다).
   그 [STATS_DUMP] 산출물로 selectors.yaml 의 blog_stats.* 를 확정하면 된다.

설계 불변식:
  · playwright 는 **메서드 안에서 지연 import** — playwright 미설치여도 모듈 import 는 성공.
  · 모든 네트워크/파싱은 try/except 로 감싸 **호출자를 절대 죽이지 않는다**.
  · 캡차 우회 금지 — 로그인은 ensure_login(사용자 세션)에만 의존한다.
  · 캡차/추가인증 페이지를 만나면 멈추고 스냅샷만 남긴다.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any

from ..config import load_selectors
from ..logging_setup import get_logger
from .config import GrowthConfig
from .html_sanitizer import sanitize_html_snapshot
from .models import InflowKeyword, PostMetric
from .repository import Repository

log = get_logger()

# 관리자 통계 진입 후보 URL(미확정 — best-effort). 앞에서부터 차례로 시도한다.
# {blog_id} = 블로그 주소 아이디(로그인 ID 아님. 예: cloudy43_).
# TODO: 실제 통계 URL 확정되면 selectors.yaml blog_stats.stats_url_templates 로 옮긴다.
_DEFAULT_STATS_URL_TEMPLATES = (
    "https://blog.naver.com/BlogStatistics.naver?blogId={blog_id}",
    "https://blog.naver.com/admin/dashboard/Dashboard.naver?blogId={blog_id}",
    "https://m.blog.naver.com/Stat.naver?blogId={blog_id}",
)

# 캡차/추가인증으로 보이는 URL 조각(만나면 수집 중단).
_BLOCKED_URL_HINTS = ("captcha", "nidlogin", "deny", "blocked")

# 정수 추출용(쉼표·공백 섞인 '1,234 회' → 1234).
_INT_RE = re.compile(r"[\d,]+")


def _today_str() -> str:
    return _dt.date.today().isoformat()


def _to_int(text: Any) -> int:
    """'1,234 회' 같은 문자열에서 정수만 뽑는다. 실패 시 0."""
    if text is None:
        return 0
    m = _INT_RE.search(str(text))
    if not m:
        return 0
    try:
        return int(m.group(0).replace(",", ""))
    except (TypeError, ValueError):
        return 0


class BlogStatsCrawler:
    """내 블로그 관리자 통계 → PostMetric/InflowKeyword 수집(best-effort)."""

    def __init__(self, cfg, growth_cfg: GrowthConfig, repo: Repository) -> None:
        self.cfg = cfg
        self.growth_cfg = growth_cfg
        self.repo = repo
        # selectors.yaml 의 blog_stats 섹션(대부분 null/TODO). 없으면 {}.
        try:
            self.sel: dict[str, Any] = load_selectors().get("blog_stats", {}) or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("selectors.yaml 로드 실패 — 빈 blog_stats 로 진행: %s", exc)
            self.sel = {}

    # ────────────────────────── 공개 API ──────────────────────────
    def collect_stats(
        self,
        *,
        blog_id: str | None = None,
        days: int = 7,
        recent_post_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """관리자 통계에서 글별 성과를 긁어 repo 에 upsert. 호출자를 절대 죽이지 않는다.

        반환: {"ok": bool, "collected_posts": int, "note": str}
        """
        blog_id = blog_id or self._resolve_blog_id()
        if not blog_id:
            note = "blog_id 미설정(engage.my_blog_id / publish.blog_id) — 통계 수집 건너뜀"
            log.warning(note)
            return {"ok": False, "collected_posts": 0, "note": note}

        try:
            return self._collect_stats_inner(
                blog_id=blog_id, days=days, recent_post_ids=recent_post_ids or [],
            )
        except Exception as exc:  # noqa: BLE001
            # 어떤 예외도 호출자(파이프라인)로 전파하지 않는다.
            log.warning("통계 수집 중 예외 — 비치명적으로 종료: %s", exc)
            return {"ok": False, "collected_posts": 0, "note": f"수집 실패: {exc}"}

    # ────────────────────────── 내부 구현 ──────────────────────────
    def _resolve_blog_id(self) -> str | None:
        """engage.my_blog_id → publish.blog_id 순서로 블로그 주소 아이디를 찾는다."""
        try:
            engage = self.cfg.section("engage") or {}
            publish = self.cfg.section("publish") or {}
        except Exception:  # noqa: BLE001
            return None
        return engage.get("my_blog_id") or publish.get("blog_id") or None

    def _stats_url_templates(self) -> tuple[str, ...]:
        """selectors.yaml 우선, 없으면 코드 기본 후보."""
        urls = self.sel.get("stats_url_templates")
        if isinstance(urls, str) and urls.strip():
            return (urls,)
        if isinstance(urls, (list, tuple)) and urls:
            return tuple(u for u in urls if isinstance(u, str) and u.strip())
        return _DEFAULT_STATS_URL_TEMPLATES

    def _collect_stats_inner(
        self, *, blog_id: str, days: int, recent_post_ids: list[str],
    ) -> dict[str, Any]:
        """browser_context + ensure_login 으로 통계 화면 진입 후 best-effort 추출."""
        # playwright 는 여기서 지연 import — 미설치여도 모듈 import 는 성공해야 한다.
        try:
            from ..utils.browser import browser_context
            from ..collector.naver_login import ensure_login
        except Exception as exc:  # noqa: BLE001
            note = f"playwright/브라우저 환경 불가 — 통계 수집 건너뜀: {exc}"
            log.warning(note)
            return {"ok": False, "collected_posts": 0, "note": note}

        collected = 0
        note = ""
        with browser_context(self.cfg) as (context, page):  # noqa: F841
            # 로그인은 사용자 세션에만 의존(캡차 우회 절대 금지).
            try:
                ensure_login(self.cfg, page)
            except Exception as exc:  # noqa: BLE001
                self._dump_failure(page, "ensure-login-failed")
                note = f"로그인 미완료 — 통계 수집 건너뜀: {exc}"
                log.warning(note)
                return {"ok": False, "collected_posts": 0, "note": note}

            # 통계 화면 진입(여러 후보 URL 시도).
            if not self._open_stats_page(page, blog_id):
                self._dump_failure(page, "open-stats-page-failed")
                note = ("통계 화면 진입 실패(URL 미확정) — [STATS_DUMP] 스냅샷으로 "
                        "selectors.yaml blog_stats.stats_url_templates 확정 필요")
                log.warning(note)
                return {"ok": False, "collected_posts": 0, "note": note}

            # 캡차/추가인증 페이지면 중단(우회 금지).
            if self._looks_blocked(page):
                self._dump_failure(page, "blocked-or-captcha")
                note = "캡차/추가인증 감지 — 우회 금지, 수집 중단"
                log.warning(note)
                return {"ok": False, "collected_posts": 0, "note": note}

            metric_date = _today_str()

            # 1) 글별 조회수/방문자/검색유입 행 추출(best-effort).
            try:
                collected += self._extract_post_metrics(page, metric_date, recent_post_ids)
            except Exception as exc:  # noqa: BLE001
                self._dump_failure(page, "extract-post-metrics-failed")
                log.warning("글별 지표 추출 실패(비치명적): %s", exc)

            # 2) 유입 키워드 추출(best-effort).
            try:
                self._extract_inflow_keywords(page, metric_date, recent_post_ids)
            except Exception as exc:  # noqa: BLE001
                self._dump_failure(page, "extract-inflow-keywords-failed")
                log.warning("유입 키워드 추출 실패(비치명적): %s", exc)

        ok = collected > 0
        if not note:
            note = (f"통계 {collected}건 수집"
                    if ok else
                    "수집된 글 지표 없음 — DOM 미확정([STATS_DUMP] 스냅샷 참고)")
        return {"ok": ok, "collected_posts": collected, "note": note}

    def _open_stats_page(self, page, blog_id: str) -> bool:
        """통계 후보 URL 들을 차례로 열어, 차단/에러가 아니면 True."""
        for tmpl in self._stats_url_templates():
            try:
                url = tmpl.format(blog_id=blog_id)
            except Exception:  # noqa: BLE001
                continue
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
            except Exception as exc:  # noqa: BLE001
                log.warning("통계 URL 진입 실패(%s): %s", url, exc)
                continue
            if self._looks_blocked(page):
                # 차단 URL 은 스킵하고 다음 후보 시도.
                continue
            log.info("통계 화면 진입 시도: %s", url)
            return True
        return False

    def _looks_blocked(self, page) -> bool:
        """현재 URL 이 캡차/로그인/차단으로 보이면 True."""
        try:
            cur = (page.url or "").lower()
        except Exception:  # noqa: BLE001
            return False
        return any(h in cur for h in _BLOCKED_URL_HINTS)

    def _extract_post_metrics(
        self, page, metric_date: str, recent_post_ids: list[str],
    ) -> int:
        """통계 표에서 글별 (post_id, 조회수, 방문자, 검색유입) 행을 긁어 upsert.

        ⚠️ DOM 미확정. selectors.yaml blog_stats.* 가 있으면 그걸 쓰고, 없으면
           그 즉시 _dump_failure 로 스냅샷만 남기고 0 을 반환한다(추측 클릭/파싱 금지).
        """
        row_sel = self.sel.get("post_row")
        if not row_sel:
            # TODO: selectors.yaml blog_stats.post_row 미확정 — 스냅샷만 남기고 빠진다.
            self._dump_failure(page, "post-metrics-selector-missing")
            log.warning("blog_stats.post_row 셀렉터 미확정 — 글별 지표 추출 건너뜀 "
                        "([STATS_DUMP]로 확정 필요)")
            return 0

        # 셀렉터가 채워진 뒤의 실제 추출 경로(현 시점엔 미실행).
        id_sel = self.sel.get("post_id_attr") or "data-log-no"
        views_sel = self.sel.get("views_cell")
        visitors_sel = self.sel.get("visitors_cell")
        inflow_sel = self.sel.get("search_inflow_cell")

        count = 0
        try:
            rows = page.locator(row_sel)
            n = rows.count()
        except Exception as exc:  # noqa: BLE001
            self._dump_failure(page, "post-metrics-rows-failed")
            log.warning("통계 행 조회 실패: %s", exc)
            return 0

        for i in range(n):
            try:
                row = rows.nth(i)
                post_id = (row.get_attribute(id_sel) or "").strip()
                if not post_id:
                    continue
                if recent_post_ids and post_id not in recent_post_ids:
                    continue
                views = self._cell_int(row, views_sel)
                visitors = self._cell_int(row, visitors_sel)
                search_inflow = self._cell_int(row, inflow_sel)
                self.repo.upsert_post_metric(PostMetric(
                    post_id=post_id,
                    metric_date=metric_date,
                    views=views,
                    visitors=visitors,
                    search_inflow=search_inflow,
                    source={"collector": "blog_stats_crawler"},
                ))
                count += 1
            except Exception as exc:  # noqa: BLE001
                # 한 행 실패는 다음 행으로 — 전체를 막지 않는다.
                log.warning("통계 행 %d 파싱 실패(건너뜀): %s", i, exc)
                continue
        if count:
            log.info("글별 지표 %d건 upsert(date=%s)", count, metric_date)
        return count

    def _cell_int(self, row, cell_sel: str | None) -> int:
        """행 안의 셀 텍스트를 정수로. 셀렉터 없으면 0."""
        if not cell_sel:
            return 0
        try:
            cell = row.locator(cell_sel)
            if cell.count() == 0:
                return 0
            return _to_int(cell.first.inner_text(timeout=2000))
        except Exception:  # noqa: BLE001
            return 0

    def _extract_inflow_keywords(
        self, page, metric_date: str, recent_post_ids: list[str],
    ) -> int:
        """유입 키워드 표에서 (post_id, keyword, count) 를 긁어 upsert.

        ⚠️ DOM 미확정. blog_stats.inflow_row 가 없으면 스냅샷만 남기고 0.
        """
        row_sel = self.sel.get("inflow_row")
        if not row_sel:
            # TODO: selectors.yaml blog_stats.inflow_row 미확정 — 스냅샷만.
            self._dump_failure(page, "inflow-keywords-selector-missing")
            log.warning("blog_stats.inflow_row 셀렉터 미확정 — 유입 키워드 추출 건너뜀 "
                        "([STATS_DUMP]로 확정 필요)")
            return 0

        kw_sel = self.sel.get("inflow_keyword_cell")
        cnt_sel = self.sel.get("inflow_count_cell")
        id_sel = self.sel.get("inflow_post_id_attr") or "data-log-no"

        count = 0
        try:
            rows = page.locator(row_sel)
            n = rows.count()
        except Exception as exc:  # noqa: BLE001
            self._dump_failure(page, "inflow-rows-failed")
            log.warning("유입 키워드 행 조회 실패: %s", exc)
            return 0

        for i in range(n):
            try:
                row = rows.nth(i)
                post_id = (row.get_attribute(id_sel) or "").strip()
                if recent_post_ids and post_id and post_id not in recent_post_ids:
                    continue
                keyword = ""
                if kw_sel:
                    kc = row.locator(kw_sel)
                    if kc.count() > 0:
                        keyword = (kc.first.inner_text(timeout=2000) or "").strip()
                if not keyword:
                    continue
                inflow_count = self._cell_int(row, cnt_sel)
                self.repo.upsert_inflow_keyword(InflowKeyword(
                    post_id=post_id or "unknown",
                    metric_date=metric_date,
                    keyword=keyword,
                    inflow_count=inflow_count,
                    source={"collector": "blog_stats_crawler"},
                ))
                count += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("유입 키워드 행 %d 파싱 실패(건너뜀): %s", i, exc)
                continue
        if count:
            log.info("유입 키워드 %d건 upsert(date=%s)", count, metric_date)
        return count

    # ────────────────────────── self-healing 스냅샷 ──────────────────────────
    def _dump_failure(self, page, name: str) -> Path | None:
        """실패 시점의 sanitize 된 HTML + 스크린샷 + 메모를 failure_log_dir 에 저장.

        place_inserter 의 self-healing 정신과 동일 — 이 산출물로 selectors.yaml 의
        blog_stats.* 를 확정한다. 저장 자체가 실패해도 조용히 None 을 반환(비치명적).
        ⚠️ HTML 은 반드시 sanitize_html_snapshot 으로 쿠키/토큰/이메일을 가린 뒤 저장.
        """
        try:
            out_dir = self.growth_cfg.failure_log_dir()
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("[STATS_DUMP] 실패 로그 디렉터리 생성 실패: %s", exc)
            return None

        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:60] or "stats"
        stem = f"blog_stats_{ts}_{safe}"
        html_path = out_dir / f"{stem}.html"
        shot_path = out_dir / f"{stem}.png"
        note_path = out_dir / f"{stem}.note.txt"

        # 현재 URL(메모용). ⚠️ 캡차/로그인 redirect URL 의 쿼리스트링에 토큰이 실릴 수 있어
        #   쿼리스트링을 떼고 경로까지만 기록한다(민감정보 노출 방지).
        try:
            cur_url = (page.url or "").split("?", 1)[0]
        except Exception:  # noqa: BLE001
            cur_url = ""

        # 1) HTML (반드시 sanitize 후 저장).
        try:
            raw = page.content()
            html_path.write_text(sanitize_html_snapshot(raw), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            log.warning("[STATS_DUMP] HTML 저장 실패(%s): %s", name, exc)
            html_path = None  # type: ignore[assignment]

        # 2) 스크린샷(bytes).
        try:
            shot_bytes = page.screenshot(full_page=True)
            shot_path.write_bytes(shot_bytes)
        except Exception as exc:  # noqa: BLE001
            log.warning("[STATS_DUMP] 스크린샷 저장 실패(%s): %s", name, exc)
            shot_path = None  # type: ignore[assignment]

        # 3) 실패 셀렉터 메모(어떤 단계에서, 어떤 셀렉터가 비었는지).
        try:
            lines = [
                f"name: {name}",
                f"url: {cur_url}",
                "blog_stats selectors (현재 값; null=미확정 → 채워야 함):",
            ]
            for key in (
                "stats_url_templates", "post_row", "post_id_attr",
                "views_cell", "visitors_cell", "search_inflow_cell",
                "inflow_row", "inflow_keyword_cell", "inflow_count_cell",
                "inflow_post_id_attr",
            ):
                lines.append(f"  {key}: {self.sel.get(key)!r}")
            note_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            log.warning("[STATS_DUMP] 메모 저장 실패(%s): %s", name, exc)
            note_path = None  # type: ignore[assignment]

        log.warning(
            "[STATS_DUMP] name=%s 저장 — html=%s shot=%s note=%s "
            "(이 산출물로 selectors.yaml blog_stats.* 확정)",
            name, html_path, shot_path, note_path,
        )
        return html_path or note_path or shot_path
