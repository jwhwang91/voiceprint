"""배치도 보조 유틸.

배치 '계획'은 Claude Code 가 페르소나의 사진 배치 패턴을 보고 직접 세운다.
이 모듈은 발행 전에 사람이 빠르게 검토할 수 있도록 배치도를 텍스트로 미리보기 해준다.
"""
from __future__ import annotations

from typing import Any

from .schema import representative_block_index


def preview(layout: dict[str, Any]) -> str:
    lines = [f"# {layout.get('title', '(제목 없음)')}  [persona: {layout.get('persona', '?')}]", ""]
    rep_idx = representative_block_index(layout)
    for i, blk in enumerate(layout.get("blocks", [])):
        t = blk["type"]
        if t == "text":
            txt = blk["content"].replace("\n", " ")
            lines.append(f"  P {txt[:60]}{'...' if len(txt) > 60 else ''}")
        elif t == "image":
            cap = f' -- "{blk["caption"]}"' if blk.get("caption") else ""
            if "files" in blk:
                names = " + ".join(blk["files"])
                # 그룹엔 대표를 못 단다(무시됨) — 사람이 잘못된 플래그를 바로 알아채도록 표시.
                bad = " ⚠️대표(그룹-무시됨)" if blk.get("representative") else ""
                lines.append(f"  [{len(blk['files'])}] {names}{cap}{bad}")
            else:
                grp = f" (group {blk['group']})" if blk.get("group") else ""
                if i == rep_idx:
                    star = " ⭐대표"
                elif blk.get("representative"):
                    star = " ⚠️대표(중복-무시됨)"
                else:
                    star = ""
                lines.append(f"  [1] {blk.get('file', '?')}{grp}{cap}{star}")
        elif t == "place":
            label = blk.get("name") or blk.get("query", "?")
            addr = f' ({blk["address"]})' if blk.get("address") else ""
            lines.append(f"  📍 {label}{addr}")
        elif t == "tags":
            lines.append(f"  # {' '.join('#' + x for x in blk.get('items', []))}")
        elif t == "heading":
            lines.append(f"  > {blk.get('content', '')}")
        elif t == "quote":
            lines.append(f"  | {blk.get('content', '')}")
    return "\n".join(lines)
