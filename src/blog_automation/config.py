"""설정 로딩. config/settings.yaml + .env 를 합쳐 하나의 Config 객체로 제공."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]   # 프로젝트 루트
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
    def _p(self, key: str) -> Path:
        return ROOT / self.raw["paths"][key]

    @property
    def collected_dir(self) -> Path: return self._p("collected_dir")
    @property
    def input_dir(self) -> Path: return self._p("input_dir")
    @property
    def drafts_dir(self) -> Path: return self._p("drafts_dir")
    @property
    def auth_dir(self) -> Path: return self._p("auth_dir")
    @property
    def persona_dir(self) -> Path: return self._p("persona_dir")

    def section(self, name: str) -> dict[str, Any]:
        return self.raw.get(name, {})

    def ensure_dirs(self) -> None:
        for key in ("collected_dir", "input_dir", "drafts_dir", "auth_dir", "persona_dir"):
            self._p(key).mkdir(parents=True, exist_ok=True)


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


def load_selectors() -> dict[str, Any]:
    with open(ROOT / "config" / "selectors.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
