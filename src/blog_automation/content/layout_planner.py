"""배치도 보조 유틸.

배치 '계획'은 Claude Code 가 페르소나의 사진 배치 패턴을 보고 직접 세운다.
이 모듈은 발행 전에 사람이 빠르게 검토할 수 있도록 배치도를 텍스트로 미리보기 해준다.
"""
from __future__ import annotations

from typing import Any


def preview(layout: dict[str, Any]) -> str:
    lines = [f"# {layout.get('title', '(제목 없음)')}  [persona: {layout.get('persona', '?')}]", ""]
    for blk in layout.get("blocks", []):
        t = blk["type"]
        if t == "text":
            txt = blk["content"].replace("\n", " ")
            lines.append(f"  P {txt[:60]}{'...' if len(txt) > 60 else ''}")
        elif t == "image":
            cap = f' -- "{blk["caption"]}"' if blk.get("caption") else ""
            if "files" in blk:
                names = " + ".join(blk["files"])
                lines.append(f"  [{len(blk['files'])}] {names}{cap}")
            else:
                grp = f" (group {blk['group']})" if blk.get("group") else ""
                lines.append(f"  [1] {blk.get('file', '?')}{grp}{cap}")
        elif t == "tags":
            lines.append(f"  # {' '.join('#' + x for x in blk.get('items', []))}")
        elif t == "heading":
            lines.append(f"  > {blk.get('content', '')}")
        elif t == "quote":
            lines.append(f"  | {blk.get('content', '')}")
    return "\n".join(lines)
