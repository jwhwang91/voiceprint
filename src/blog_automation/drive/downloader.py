"""구글 드라이브 공개 공유 폴더/파일 다운로드(gdown).

전제: '링크가 있는 모든 사용자'로 공개된 폴더. 사진과 설명(description.txt 또는
설명이 담긴 텍스트/문서)을 data/input/<job>/ 로 받는다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

import gdown
import requests

from ..config import Config
from ..logging_setup import get_logger
from ..utils.files import list_images, IMAGE_EXTS

log = get_logger()


# ──────────────────────────────────────────────
# 단일 Drive 폴더/파일 fetch
# ──────────────────────────────────────────────

def run_fetch(cfg: Config, url: str, job: str) -> None:
    out_dir = cfg.input_dir / job
    photos_dir = out_dir / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    log.info("드라이브에서 다운로드 중... → %s", out_dir)
    if "/folders/" in url:
        # 폴더는 목록만 먼저 받고(skip_download) 이미지 파일만 ID 로 내려받는다.
        # 대용량 동영상(.MOV 등)은 건너뛴다 — 동영상이 다운로드를 느리게 하고 구글
        # 드라이브 rate-limit 을 유발해 '일부 사진 누락'을 일으키던 문제 해결.
        try:
            listing = gdown.download_folder(
                url=url, output=str(out_dir), quiet=True,
                use_cookies=False, skip_download=True) or []
        except Exception as exc:  # noqa: BLE001
            log.error("폴더 목록 가져오기 실패(드라이브 접근 제한 가능 — 잠시 후 재시도): %s", exc)
            listing = []
        images = [f for f in listing
                  if Path(f.local_path).suffix.lower() in IMAGE_EXTS]
        log.info("폴더 항목 %d개 중 이미지 %d개 받기(동영상 등 %d개 건너뜀)",
                 len(listing), len(images), len(listing) - len(images))
        got = 0
        for f in images:
            dest = Path(f.local_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and dest.stat().st_size > 0:
                got += 1
                continue
            try:
                gdown.download(id=f.id, output=str(dest), quiet=True, use_cookies=False)
                got += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("이미지 다운로드 실패 %s: %s", dest.name, exc)
        log.info("이미지 다운로드 완료 %d/%d", got, len(images))
    else:
        gdown.download(url=url, output=str(out_dir) + "/", quiet=False, fuzzy=True)

    _organize(out_dir, photos_dir)

    imgs = list_images(photos_dir)
    log.info("이미지 %d장 정리 완료 → %s", len(imgs), photos_dir)
    desc = out_dir / "description.txt"
    if not desc.exists():
        desc.write_text(
            "# 여기에 사진별 간단 설명을 적거나, 드라이브의 설명 파일 내용을 붙여넣으세요.\n",
            encoding="utf-8")
        log.info("설명 파일 템플릿 생성: %s", desc)
    log.info("다음 단계: Claude Code 에게 'prompts/write_post.md 따라 %s 글 써줘' 라고 요청하세요.", job)


# ──────────────────────────────────────────────
# Google Docs → 여러 포스트 일괄 fetch
# ──────────────────────────────────────────────

class _Entry(TypedDict):
    job: str
    title: str
    folder_url: str
    description: str


def run_fetch_from_doc(cfg: Config, doc_url: str) -> None:
    """Google Docs URL에서 포스트 목록을 파싱하고 각 Drive 폴더 사진을 일괄 다운로드."""
    log.info("Google Docs 파싱 중... %s", doc_url)
    doc_id = _extract_doc_id(doc_url)
    text = _fetch_doc_text(doc_id)
    entries = _parse_doc_entries(text)

    if not entries:
        log.warning("파싱된 엔트리가 없습니다. 문서 형식을 확인하세요.")
        return

    log.info("총 %d개 포스트 발견", len(entries))

    failed = []
    for entry in entries:
        job = entry["job"]
        log.info("─── [%s] 처리 시작: %s", job, entry["title"])

        # description.txt를 먼저 저장 — 다운로드 실패해도 보존됨
        job_dir = cfg.input_dir / job
        job_dir.mkdir(parents=True, exist_ok=True)
        desc_file = job_dir / "description.txt"
        desc_file.write_text(entry["description"], encoding="utf-8")
        log.info("설명 저장 완료: %s", desc_file)

        try:
            run_fetch(cfg, url=entry["folder_url"], job=job)
        except Exception as exc:
            log.error("[%s] 다운로드 실패 (description.txt는 저장됨): %s", job, exc)
            failed.append(job)

    if failed:
        log.warning("실패한 job (나중에 개별 fetch로 재시도): %s", ", ".join(failed))
    log.info("모든 포스트 처리 완료 (%d개, 실패 %d개)", len(entries), len(failed))
    log.info("다음 단계: 각 job 폴더별로 'prompts/write_post.md 따라 <job> 글 써줘' 라고 요청하세요.")


def _extract_doc_id(url: str) -> str:
    m = re.search(r'/document/d/([a-zA-Z0-9_-]+)', url)
    if not m:
        raise ValueError(f"Google Docs URL에서 문서 ID를 찾을 수 없습니다: {url}")
    return m.group(1)


def _fetch_doc_text(doc_id: str) -> str:
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    resp = requests.get(export_url, allow_redirects=True, timeout=30)
    resp.raise_for_status()
    # Google Docs txt export may include a UTF-8 BOM (﻿) at the start
    return resp.text.lstrip('﻿')


def _parse_doc_entries(text: str) -> list[_Entry]:
    """6자리 날짜로 시작하는 각 블록을 엔트리로 파싱."""
    # 각 엔트리 시작 위치: 줄 맨 앞에 6자리 숫자
    header_re = re.compile(r'^(\d{6}[^\n]*)', re.MULTILINE)
    positions = [(m.start(), m.group(1)) for m in header_re.finditer(text)]

    entries: list[_Entry] = []
    for i, (start, title_line) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        chunk = text[start:end].strip()

        # 링크 추출 (첫 번째 https URL이 Drive 폴더 링크)
        link_m = re.search(r'링크\s*[:：]\s*(https?://\S+)', chunk)
        if not link_m:
            log.warning("링크를 찾을 수 없어 건너뜀: %s", title_line.strip())
            continue

        folder_url = link_m.group(1).rstrip(')')  # 혹시 붙은 ) 제거
        description = chunk[link_m.end():].strip()

        entries.append(_Entry(
            job=_make_job_name(title_line),
            title=title_line.strip(),
            folder_url=folder_url,
            description=description,
        ))

    return entries


def _make_job_name(title: str) -> str:
    """제목 → 안전한 job 식별자.

    '260611 마감_옥스라이브파이브그릴 성수 (레뷰)' → '260611_옥스라이브파이브그릴_성수'
    """
    date_m = re.match(r'^(\d{6})', title)
    date = date_m.group(1) if date_m else ""

    # 마지막 _ 이후를 주 이름으로 사용
    name_part = title.split('_')[-1] if '_' in title else title[6:]

    # 괄호 안 내용, 화살표 이후 지시사항 제거
    name_part = re.sub(r'\([^)]*\)', '', name_part)
    name_part = re.sub(r'->.*', '', name_part)

    # 파일명 안전: 한글/영숫자 외 → _, 연속 _ 합치기
    name_part = re.sub(r'[^\w가-힣]', '_', name_part.strip())
    name_part = re.sub(r'_+', '_', name_part).strip('_')

    return f"{date}_{name_part}" if date else name_part


# ──────────────────────────────────────────────
# 내부 유틸
# ──────────────────────────────────────────────

def _organize(out_dir: Path, photos_dir: Path) -> None:
    """다운로드된 이미지들을 photos/ 하위로 이동(폴더 구조가 평탄치 않을 때 대비)."""
    from ..utils.files import IMAGE_EXTS
    for p in out_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and p.parent != photos_dir:
            target = photos_dir / p.name
            if not target.exists():
                p.rename(target)
