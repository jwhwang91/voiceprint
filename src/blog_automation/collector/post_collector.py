"""과거 글 수집 (페르소나 학습용).

방식: Playwright DOM 스크래핑 대신 네이버 비공식 API + HTML 파싱(로그인 불필요, 안정적).
  1) PostTitleListAsync.naver  → 글 목록(logNo/제목/카테고리/날짜) JSON
  2) PostView.naver            → 개별 글 본문 HTML (SmartEditor ONE)
본문은 컴포넌트(텍스트/이미지) 순서를 보존해 저장한다 → 사진 배치 패턴 학습의 핵심.

공개 글만 대상으로 한다(비공개 글은 로그인 세션이 필요 — 추후 확장).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

from ..config import Config, load_selectors
from ..logging_setup import get_logger
from ..utils.files import write_json
from .models import CollectedPost

log = get_logger()

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _session(blog_id: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(_HEADERS)
    s.headers["Referer"] = f"https://blog.naver.com/{blog_id}"
    return s


def _field(obj: str, key: str) -> str:
    m = re.search(rf'"{key}":"([^"]*)"', obj)
    return m.group(1) if m else ""


def fetch_post_list(sess: requests.Session, sel: dict, blog_id: str,
                    max_posts: int, per_page: int = 30) -> list[dict]:
    """글 목록(logNo/제목/카테고리/날짜)을 max_posts 개까지 모은다.

    네이버 응답이 엄격한 JSON 이 아니라(잘못된 escape 포함) json.loads 대신
    정규식으로 필드를 추출한다. 제목은 URL 인코딩이라 따옴표가 없어 안전하다.
    """
    out: list[dict] = []
    page = 1
    while len(out) < max_posts:
        url = sel["blog"]["post_list_api"].format(
            blog_id=blog_id, page=page, count=per_page)
        text = sess.get(url, timeout=20).text
        # 리스트 항목은 중첩 중괄호가 없는 평면 객체
        objs = re.findall(r'\{[^{}]*"logNo":"\d+"[^{}]*\}', text)
        if not objs:
            break
        for o in objs:
            out.append({
                "logNo": _field(o, "logNo"),
                "title": unquote(_field(o, "title").replace("+", " ")),
                "categoryNo": _field(o, "categoryNo"),
                "addDate": _field(o, "addDate"),
                "commentCount": _field(o, "commentCount"),
            })
            if len(out) >= max_posts:
                break
        page += 1
    return out


def fetch_tags(sess: requests.Session, sel: dict, blog_id: str, log_no: str) -> list[str]:
    """해시태그를 전용 API로 가져온다(정적 HTML엔 없음)."""
    try:
        url = sel["blog"]["post_tags_api"].format(blog_id=blog_id, log_no=log_no)
        text = sess.get(url, timeout=15).text
        m = re.search(r'"tagName":"([^"]*)"', text)
        if not m or not m.group(1):
            return []
        raw = unquote(m.group(1).replace("+", " "))
        return [t.strip() for t in raw.split(",") if t.strip()]
    except Exception as e:  # noqa: BLE001
        log.warning("태그 조회 실패 logNo=%s: %s", log_no, e)
        return []


def _clean_img_url(url: str) -> str:
    """네이버 이미지 썸네일 파라미터 제거 → 원본 화질."""
    return re.sub(r"\?type=w\d+.*$", "", url)


def parse_post(html: str, sel: dict) -> dict:
    """PostView.naver HTML → 제목/본문블록/이미지/태그. 블록 순서 보존."""
    sv = sel["post_view"]
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.select_one(sv["title"])
    title = title_el.get_text(" ", strip=True) if title_el else ""

    container = soup.select_one(sv["container"])
    blocks: list[dict] = []
    image_urls: list[str] = []
    body_parts: list[str] = []

    if container:
        for comp in container.select(sv["component"]):
            cls = " ".join(comp.get("class", []))
            if sv["image_group_component"] in cls or sv["image_component"] in cls:
                imgs = comp.select(sv["image_resource"])
                files = []
                for img in imgs:
                    src = img.get("data-lazy-src") or img.get("src") or ""
                    if src:
                        src = _clean_img_url(src)
                        image_urls.append(src)
                        files.append(src)
                grouped = sv["image_group_component"] in cls
                blocks.append({"type": "image", "srcs": files, "group": grouped})
            elif sv["section_title_component"] in cls:
                t = comp.get_text(" ", strip=True)
                blocks.append({"type": "heading", "text": t})
                body_parts.append("# " + t)
            elif sv["text_component"] in cls:
                t = comp.get_text("\n", strip=True)
                if t:
                    blocks.append({"type": "text", "text": t})
                    body_parts.append(t)

    # 폴백: 구버전 에디터(se-main-container 없음)
    if not blocks:
        area = soup.select_one("#postViewArea, .post-view, .se_doc_viewer")
        if area:
            body_parts.append(area.get_text("\n", strip=True))
            for img in area.select("img"):
                src = img.get("src") or ""
                if src:
                    image_urls.append(_clean_img_url(src))

    tags = [t.get_text(strip=True).lstrip("#")
            for t in soup.select(sv["tags"]) if t.get_text(strip=True)]

    return {
        "title": title,
        "body_text": "\n\n".join(body_parts),
        "body_blocks": blocks,
        "image_urls": image_urls,
        "tags": tags,
    }


def _guess_category(cfg: Config, text: str) -> str:
    for cat, kws in cfg.section("persona").get("categories", {}).items():
        if any(kw in text for kw in kws):
            return cat
    return "미분류"


def _download_images(sess: requests.Session, urls: list[str], out_dir: Path,
                     post_id: str) -> list[str]:
    files: list[str] = []
    for i, u in enumerate(urls):
        try:
            r = sess.get(u, timeout=20)
            ext = ".jpg" if "jpg" in u.lower() or "jpeg" in u.lower() else ".png"
            fp = out_dir / f"{post_id}_{i:02d}{ext}"
            fp.write_bytes(r.content)
            files.append(str(fp))
        except Exception as e:  # noqa: BLE001
            log.warning("이미지 다운로드 실패 %s: %s", u, e)
    return files


def run_collect(cfg: Config, blog_id: str, manual_login: bool = False,
                max_posts: int | None = None) -> None:
    """blog_id = 블로그 주소 아이디(로그인 ID 아님!). 예: cloudy43_"""
    sel = load_selectors()
    coll = cfg.section("collect")
    max_posts = max_posts or coll.get("max_posts", 50)
    download_images = coll.get("download_images", True)

    out_dir = cfg.collected_dir / blog_id
    img_dir = out_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    sess = _session(blog_id)

    log.info("글 목록 조회: %s (최대 %d개)", blog_id, max_posts)
    posts = fetch_post_list(sess, sel, blog_id, max_posts)
    log.info("총 %d개 글 발견", len(posts))
    if not posts:
        log.error("글이 없습니다. 블로그 주소 아이디가 맞는지 확인하세요(로그인 ID와 다를 수 있음).")
        return

    for idx, meta in enumerate(posts):
        log_no = meta["logNo"]
        log.info("[%d/%d] %s", idx + 1, len(posts), meta["title"][:40])
        url = sel["blog"]["post_view_url"].format(blog_id=blog_id, log_no=log_no)
        try:
            html = sess.get(url, timeout=20).text
            parsed = parse_post(html, sel)
        except Exception as e:  # noqa: BLE001
            log.warning("글 수집 실패 logNo=%s: %s", log_no, e)
            continue

        image_files = (_download_images(sess, parsed["image_urls"], img_dir, log_no)
                       if download_images else [])
        tags = fetch_tags(sess, sel, blog_id, log_no)

        post = CollectedPost(
            post_id=log_no,
            url=f"https://blog.naver.com/{blog_id}/{log_no}",
            title=meta["title"] or parsed["title"],   # 목록 API 제목이 깨끗함(본문 제목은 UI 오염)
            body_text=parsed["body_text"],
            body_blocks=parsed["body_blocks"],
            image_urls=parsed["image_urls"],
            image_files=image_files,
            tags=tags,
            category_guess=_guess_category(cfg, meta["title"] + parsed["body_text"]),
            posted_at=meta["addDate"],
        )
        write_json(out_dir / f"{log_no}.json", post.to_dict())

    log.info("수집 완료 → %s", out_dir)
    log.info("다음: Claude Code 에게 'prompts/analyze_persona.md 따라 분석해줘' 라고 요청하세요.")
