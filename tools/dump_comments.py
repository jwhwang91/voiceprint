"""댓글 영역 전용 덤프: 모든 프레임을 훑어 댓글(cbox) DOM 을 찾아 저장.

사용: python tools/dump_comments.py --url <댓글 달린 글 URL>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blog_automation.config import load_config            # noqa: E402
from blog_automation.utils.browser import browser_context  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "_inspect"
HINTS = ["cbox", "comment", "댓글", "u_cbox", "reply"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_config()

    with browser_context(cfg, profile=cfg.section("engage").get("my_blog_id", "naver")) as (ctx, page):
        page.goto(args.url)
        page.wait_for_timeout(3000)
        # 댓글 cbox 로드를 위해 천천히 끝까지 스크롤
        for _ in range(12):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(700)
        page.wait_for_timeout(2500)

        report = []
        for fr in page.frames:
            try:
                html = fr.content()
            except Exception:  # noqa: BLE001
                continue
            score = sum(html.count(h) for h in HINTS)
            if score < 3:
                continue
            name = f"comments_frame_{abs(hash(fr.url)) % 10000}"
            (OUT / f"{name}.html").write_text(html, encoding="utf-8")
            # 후보 셀렉터: 댓글/입력/등록 관련
            cand = fr.evaluate("""() => {
              const out=[]; const seen=new Set();
              for (const el of document.querySelectorAll('a,button,textarea,div,span,li,strong')) {
                const cls=(el.className&&el.className.toString)?el.className.toString():'';
                const id=el.id||'';
                const hay=(cls+' '+id).toLowerCase();
                if (!/cbox|comment|reply|btn_upload|u_cbox/.test(hay)) continue;
                const sig=el.tagName+'|'+cls; if(seen.has(sig))continue; seen.add(sig);
                out.push({tag:el.tagName.toLowerCase(),id,cls,
                  text:(el.innerText||el.value||'').trim().slice(0,30)});
              }
              return out.slice(0,120);
            }""")
            lines = [f"# frame url: {fr.url}", f"# hint score: {score}", ""]
            for c in cand:
                sel = f"#{c['id']}" if c["id"] else ("." + ".".join(c["cls"].split()) if c["cls"] else c["tag"])
                lines.append(f"{c['tag']:9} {sel:60} text='{c['text']}'")
            (OUT / f"{name}.candidates.txt").write_text("\n".join(lines), encoding="utf-8")
            report.append((name, fr.url, score, len(cand)))

        print("\n=== 댓글 관련 프레임 ===")
        for name, url, score, n in report:
            print(f"  {name}: score={score} cands={n}\n     {url}")
        if not report:
            print("  댓글 프레임을 못 찾음 — 스크롤/로그인 확인 필요")
        print(f"\n저장 위치: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
