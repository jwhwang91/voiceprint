"""Phase 1: 내 글에 댓글 단 사람 수집 + 각자 최근 글 본문 수집.

- 댓글 작성자 추출: 로그인 세션으로 내 글을 열어 댓글 영역의 작성자 블로그 링크를 모은다(Playwright).
- 각 작성자의 최근 글: 공개 API(PostTitleListAsync/PostView)로 빠르게 본문 발췌만 가져온다(브라우저 불필요).
산출물: data/engage/<job>/targets.json  → Claude Code 가 읽고 댓글을 생성한다.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from ..config import Config, load_selectors
from ..collector import naver_login
from ..collector.post_collector import _session, fetch_post_list, parse_post
from ..logging_setup import get_logger
from ..utils.browser import browser_context
from ..utils.files import write_json
from .models import TargetPost

log = get_logger()


def _blog_id_from_href(href: str) -> str | None:
    """https://blog.naver.com/<id>(/...) → <id>"""
    m = re.search(r"blog\.naver\.com/([A-Za-z0-9_\-]+)", href or "")
    return m.group(1) if m else None


def _my_post_url(cfg: Config, post: str) -> str:
    if post.startswith("http"):
        return post
    blog_id = cfg.section("engage").get("my_blog_id")
    return f"https://blog.naver.com/{blog_id}/{post}"


def collect_commenters(cfg: Config, post: str) -> list[dict]:
    """내 글 댓글 영역에서 (blog_id, nickname) 목록을 수집."""
    sel = load_selectors()["comments"]
    url = _my_post_url(cfg, post)
    my_id = cfg.section("engage").get("my_blog_id")
    excluded = set(cfg.section("engage").get("exclude_blog_ids", [])) | {my_id}

    found: dict[str, str] = {}  # blog_id -> nickname
    # 댓글 읽기는 공개 — 로그인 불필요.
    with browser_context(cfg, profile=my_id or "naver") as (ctx, page):
        page.goto(url)
        page.wait_for_timeout(4000)

        scope = page
        if sel.get("main_frame"):
            fr_el = page.query_selector(sel["main_frame"])
            if fr_el and fr_el.content_frame():
                scope = fr_el.content_frame()

        # 댓글(cbox)은 스크롤만으론 렌더 안 됨 → 댓글 영역 스크롤 + 댓글 버튼 JS 클릭으로 트리거
        try:
            scope.eval_on_selector(sel["comment_area"],
                                   "e => e.scrollIntoView({block:'center'})")
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1000)
        try:
            scope.evaluate("""() => {
              const t = document.querySelector('[id^=Comi]'); if (t) t.click();
              const w = document.querySelector('.btn_write_comment'); if (w) w.click();
            }""")
        except Exception:  # noqa: BLE001
            pass
        for _ in range(10):
            if scope.query_selector(sel["commenter_link"]):
                break
            page.wait_for_timeout(700)
        page.wait_for_timeout(1500)

        for a in scope.query_selector_all(sel["commenter_link"]):
            bid = _blog_id_from_href(a.get_attribute("href") or "")
            if bid and bid not in excluded:
                found.setdefault(bid, (a.inner_text() or bid).strip()[:40])

    log.info("댓글 작성자 %d명 수집", len(found))
    return [{"blog_id": b, "nickname": n} for b, n in found.items()]


def build_targets(cfg: Config, post: str, job: str) -> Path:
    eng = cfg.section("engage")
    commenters = collect_commenters(cfg, post)[: eng.get("max_commenters", 5)]

    sel = load_selectors()
    targets: list[dict] = []
    for c in commenters:
        bid = c["blog_id"]
        sess = _session(bid)
        try:
            recent = fetch_post_list(sess, sel, bid,
                                     max_posts=eng.get("posts_per_commenter", 2))
        except Exception as e:  # noqa: BLE001
            log.warning("최근 글 목록 실패 %s: %s", bid, e)
            continue
        for meta in recent:
            view = sel["blog"]["post_view_url"].format(blog_id=bid, log_no=meta["logNo"])
            try:
                parsed = parse_post(sess.get(view, timeout=20).text, sel)
            except Exception as e:  # noqa: BLE001
                log.warning("본문 수집 실패 %s/%s: %s", bid, meta["logNo"], e)
                continue
            t = TargetPost(
                blog_id=bid, nickname=c["nickname"], log_no=meta["logNo"],
                url=f"https://blog.naver.com/{bid}/{meta['logNo']}",
                title=meta["title"] or parsed["title"],
                body_excerpt=parsed["body_text"][:500],
            )
            targets.append(t.to_dict())

    out = Path(cfg.collected_dir).parent / "engage" / job
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "targets.json", {"my_post": _my_post_url(cfg, post), "targets": targets})
    log.info("답방 대상 %d개 글 → %s", len(targets), out / "targets.json")
    log.info("다음: Claude Code 에게 'prompts/write_comments.md 따라 %s 댓글 생성해줘' 라고 요청하세요.", job)
    return out / "targets.json"


def run_scan(cfg: Config, post: str, job: str) -> None:
    build_targets(cfg, post, job)
