"""초고/배치도 산출물 스키마.

Claude Code 가 prompts/write_post.md 를 따라 아래 두 파일을 만든다:
  - data/drafts/<job>/post.md      : 본문. 사진 자리는 {{photo: 파일명}} 으로 표시
  - data/drafts/<job>/layout.json  : 아래 LAYOUT_SCHEMA 를 따르는 배치도

publish 단계(naver_editor)가 layout.json 을 그대로 파싱하므로 형식을 정확히 지킬 것.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils.files import read_json, resolve_images

# layout.json 예시/스키마(설명용)
LAYOUT_SCHEMA: dict[str, Any] = {
    "title": "글 제목",
    "persona": "맛집방문",                 # 사용한 페르소나
    "blocks": [                            # 위에서 아래로 순서대로 발행됨
        {"type": "text", "content": "도입부 한두 줄..."},
        # representative:true → 네이버 '대표 이미지'(썸네일). 글 전체를 대표하는 단독 사진 1장에만.
        # 단독(file) 블록에만, 글당 1개만. 첫 *이미지* 블록이면 됨(앞에 도입 텍스트가 와도 무방).
        # 생략하면 네이버 기본(첫 이미지)이 대표가 된다.
        {"type": "image", "file": "photo_01.jpg", "align": "center",
         "representative": True, "tag": "외관 전경"},
        {"type": "text", "content": "다음 문단..."},
        {"type": "image", "files": ["photo_02.jpg", "photo_03.jpg"],
         "align": "center", "tag": "메뉴"},   # files = 그룹(콜라주)
        # place = 네이버 '장소(지도)' 카드. query 를 장소 검색창에 쳐서 첫 결과를 삽입.
        # 상호는 Claude 가 웹검색으로 정식 지점명·주소를 확정해 넣는다(prompts/write_post.md §3.5).
        {"type": "place", "query": "바오 서울 성수",
         "name": "바오 서울", "address": "서울 성동구 …(검토용)"},
        {"type": "tags", "items": ["맛집", "성수동맛집"]},
    ],
}

VALID_BLOCK_TYPES = {"text", "image", "tags", "heading", "quote", "place"}


def load_layout(drafts_dir: Path, job: str) -> dict[str, Any]:
    return read_json(drafts_dir / job / "layout.json")


def get_image_files(blk: dict) -> list[str]:
    """image 블록에서 파일 목록 반환.
    단독: {"file": "a.jpg"} → ["a.jpg"]
    그룹: {"files": ["a.jpg","b.jpg"]} → ["a.jpg","b.jpg"]
    """
    if "files" in blk:
        return blk["files"]
    if "file" in blk:
        return [blk["file"]]
    return []


def validate_layout(layout: dict[str, Any], photos_dir: Path) -> list[str]:
    """배치도 검증. 문제점 목록을 반환(빈 리스트면 OK)."""
    errors: list[str] = []
    if "blocks" not in layout or not isinstance(layout["blocks"], list):
        return ["'blocks' 배열이 없습니다."]
    for i, blk in enumerate(layout["blocks"]):
        t = blk.get("type")
        if t not in VALID_BLOCK_TYPES:
            errors.append(f"blocks[{i}]: 알 수 없는 type '{t}'")
        if t == "image":
            files = get_image_files(blk)
            if not files:
                errors.append(f"blocks[{i}]: image 블록에 file/files 없음")
            for f in files:
                matches = resolve_images(photos_dir, f)
                if not matches:
                    errors.append(f"blocks[{i}]: 사진 파일 없음 → {f}")
                elif len(matches) > 1:
                    rels = ", ".join(str(m.relative_to(photos_dir)) for m in matches)
                    errors.append(
                        f"blocks[{i}]: 같은 파일명이 여러 폴더에 있음 → {f} ({rels}). "
                        f"layout.json 에 '<카테고리>/{f}' 처럼 폴더를 포함해 지정하세요.")
        if t == "text" and not blk.get("content"):
            errors.append(f"blocks[{i}]: text 블록이 비어 있음")
        if t == "place":
            q = blk.get("query")
            if not (isinstance(q, str) and q.strip()):
                errors.append(f"blocks[{i}]: place 블록에 'query'(장소 검색어) 없음")
    return errors


# ---------------------------------------------------------------------------
# 대표 이미지(썸네일) — '글 전체를 대표하는 단독 사진 1장'
#
# 네이버 SmartEditor ONE 은 따로 지정하지 않으면 **첫(맨 위) 이미지**를 썸네일로 쓴다.
# 그래서 가장 견고한 방식은 '대표로 쓸 단독 사진을 첫 이미지 블록에 두는 것'이고,
# 그 경우 클릭 없이 임시저장에도 그대로 보존된다(아래 publisher 가 클릭을 생략).
# representative 는 layout.json(=발행이 읽는 유일 파일)에만 의미가 있다. photo_tags.json
# 의 representative 는 글쓴이(LLM)의 메모일 뿐 publisher 가 읽지 않는다.
# ---------------------------------------------------------------------------

def _is_single_image(blk: dict) -> bool:
    """단독 image 블록(file 하나, files 없음)인지."""
    return blk.get("type") == "image" and "file" in blk and "files" not in blk


def first_image_block_index(layout: dict[str, Any]) -> int | None:
    """첫 image 블록 인덱스(단독/그룹 무관). 네이버 기본 썸네일=이 블록의 첫 사진."""
    for i, blk in enumerate(layout.get("blocks", [])):
        if blk.get("type") == "image":
            return i
    return None


def representative_block_index(layout: dict[str, Any]) -> int | None:
    """대표로 쓸 '단독 image 블록'의 인덱스(없으면 None).

    규칙(견고·비치명적):
      - representative:true 인 '단독(file)' image 블록 중 **첫 번째**만 채택.
      - 그룹(files) 블록의 representative 는 무시(대표는 단독 사진이어야 하며, 콜라주
        내부 컷의 대표 지정은 네이버 DOM 상 미확인이라 지원하지 않는다).
      - 없으면 None → 발행기는 네이버 기본(첫 이미지=썸네일)에 맡긴다.
    publisher 는 이 '인덱스'로만 동작한다(파일명 매칭 금지 — 같은 파일명이 콜라주에도
    들어 있을 수 있어 엉뚱한 컷을 대표로 잡을 위험).
    """
    for i, blk in enumerate(layout.get("blocks", [])):
        if _is_single_image(blk) and blk.get("representative"):
            return i
    return None


def representative_warnings(layout: dict[str, Any]) -> list[str]:
    """대표 이미지 지정의 '비치명적' 문제(경고)를 반환. 발행을 막지 않는다.

    validate_layout 가 치명 오류(누락 파일/빈 텍스트 등)만 모아 SystemExit 하는 것과
    분리한다 — 썸네일 설정 문제로 발행 전체를 막지 않기 위함. run_publish 가 이 경고들을
    log.warning 으로 띄우고, publisher 는 항상 안전하게 복구(첫 단독 플래그만 채택)한다.
    """
    blocks = layout.get("blocks", [])
    has_image = any(b.get("type") == "image" for b in blocks)
    single_flagged = [i for i, b in enumerate(blocks)
                      if _is_single_image(b) and b.get("representative")]
    group_flagged = [i for i, b in enumerate(blocks)
                     if b.get("type") == "image" and "files" in b and b.get("representative")]
    warns: list[str] = []
    for i in group_flagged:
        warns.append(f"blocks[{i}]: 그룹(콜라주) 블록의 representative 는 무시됨 — 대표는 단독 사진이어야 함.")
    if len(single_flagged) > 1:
        warns.append(f"대표(representative:true) 단독 블록이 {len(single_flagged)}개 "
                     f"(blocks {single_flagged}) — 첫 번째만 대표로 사용, 나머지는 무시.")
    if not single_flagged:
        if has_image:
            warns.append("대표(representative:true) 지정 없음 — 네이버 기본(첫 이미지)이 썸네일이 됨. "
                         "글을 가장 잘 대표하는 단독 사진을 '첫 이미지 블록'에 두고 representative:true 권장.")
    else:
        rep_idx = single_flagged[0]
        first_img = first_image_block_index(layout)
        if first_img is not None and rep_idx != first_img:
            warns.append(
                f"대표 단독 블록(blocks[{rep_idx}])이 첫 이미지(blocks[{first_img}])가 아님 — "
                f"네이버 기본 썸네일은 '첫 이미지'다. 가장 안전한 방법은 대표를 첫 이미지로 옮기는 것. "
                f"굳이 유지하려면 publish.enforce_representative_click=true 로 에디터에서 대표를 클릭해야 함.")
    return warns
