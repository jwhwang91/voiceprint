"""설정 로딩. config/settings.yaml + .env 를 합쳐 하나의 Config 객체로 제공.

경로(입력/초고/세션 등)는 `paths` 모듈(워크스페이스 추상화)로 위임한다 — 개발 모드는 repo-local
`data/` 폴백, 앱 모드는 `VOICEPRINT_WORKSPACE`. 셀렉터 로딩은 `selectors` 모듈로 위임한다
(번들 기본값 + 사용자 오버라이드 병합). 둘 다 기존 공개 API(`cfg.input_dir`, `load_selectors`)를
그대로 보존하므로 호출부는 수정이 필요 없다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from . import paths
# 셀렉터 로딩/접근/오버라이드 — 하위 호환을 위해 여기서 재노출(기존 `from ..config import load_selectors`).
from .selectors import (  # noqa: F401
    load_selectors,
    load_selectors_raw,
    get_selector,
    save_selector_override,
)

ROOT = paths.REPO_ROOT                          # 프로젝트 루트(번들 기본값 위치)
CONFIG_FILE = ROOT / "config" / "settings.yaml"


def _load_yaml() -> dict[str, Any]:
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=dict)
    naver_id: str | None = None
    naver_pw: str | None = None

    # --- 경로 헬퍼 (절대경로로 반환) ---
    # 모두 paths(워크스페이스 추상화)로 위임한다. 개발 모드(워크스페이스 미지정)에서는
    # paths 기본값이 기존 settings.yaml 의 data/* 레이아웃과 정확히 일치 → 동작 동일.
    @property
    def collected_dir(self) -> Path: return paths.get_collected_root()
    @property
    def input_dir(self) -> Path: return paths.get_input_root()
    @property
    def drafts_dir(self) -> Path: return paths.get_drafts_root()
    @property
    def auth_dir(self) -> Path: return paths.get_auth_dir()
    @property
    def persona_dir(self) -> Path: return paths.get_persona_dir()

    def section(self, name: str) -> dict[str, Any]:
        return self.raw.get(name, {})

    def ensure_dirs(self) -> None:
        paths.ensure_runtime_dirs()


def load_config() -> Config:
    load_dotenv(ROOT / ".env")
    raw = _load_yaml()

    # .env 가 yaml 을 덮어쓰는 항목
    if os.getenv("HEADLESS"):
        raw["browser"]["headless"] = os.getenv("HEADLESS", "").lower() == "true"
    if os.getenv("SLOW_MO_MS"):
        raw["browser"]["slow_mo_ms"] = int(os.getenv("SLOW_MO_MS"))

    cfg = Config(
        raw=raw,
        naver_id=os.getenv("NAVER_ID") or None,
        naver_pw=os.getenv("NAVER_PW") or None,
    )
    cfg.ensure_dirs()
    return cfg
