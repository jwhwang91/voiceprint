"""중앙 경로 해석기 — '워크스페이스'(런타임 데이터 루트) 추상화.

이 프로젝트는 두 가지 모드로 돈다:

  · 개발/PyCharm 모드 — 워크스페이스 미지정. 모든 런타임 데이터가 repo-local `data/`(+ 루트
    `logs/`·`personas/`)에 떨어진다. **기존과 100% 동일한 동작**(앱 도입 전과 차이 없음).
  · 앱 모드 — Electron 이 `VOICEPRINT_WORKSPACE=<사용자가 고른 폴더>` 를 넘긴다. 모든 런타임
    데이터(입력/초고/세션/로그/사용자 셀렉터 패치)가 그 폴더 아래로 간다 → 앱 코드 업데이트가
    사용자 데이터를 지우지 않는다.

해석 우선순위(`get_workspace_root`):
  1. `set_workspace_override(path)`  — CLI `--workspace`
  2. 환경변수 `VOICEPRINT_WORKSPACE`
  3. `config/settings.yaml` 의 `paths.workspace` (있으면)
  4. 폴백: repo-local `data/`   (개발 기본값)

워크스페이스 레이아웃:
    <workspace>/input/<job>/photos/
    <workspace>/input/<job>/description.txt
    <workspace>/drafts/<job>/
    <workspace>/collected/<id>/
    <workspace>/engage/<job>/
    <workspace>/auth/
    <workspace>/logs/
    <workspace>/personas/
    <workspace>/blog_growth/blog_growth.db
    <workspace>/config/selectors.user.yaml
    <workspace>/config/workflows.user.yaml
    <workspace>/settings.json            (Electron 앱 설정 — main.js 가 관리)

⚠️ 개발 모드(워크스페이스 미지정)에서는 `logs/` 와 `personas/` 가 **repo 루트**에 남는다(기존 호환).
   앱 모드에서는 둘 다 `<workspace>/` 아래로 들어간다(사용자 데이터 = 워크스페이스 한 곳에 모임).

이 모듈은 `config`/`logging_setup` 등 어떤 내부 모듈도 import 하지 않는다(순환 방지). 표준
라이브러리 + yaml 만 쓴다.
"""
from __future__ import annotations

import os
from pathlib import Path

# repo 루트(번들 기본값·앱 소스가 사는 곳). paths.py → blog_automation → src → repo.
REPO_ROOT = Path(__file__).resolve().parents[2]

# 개발 폴백 워크스페이스(= repo-local data/). 기존 settings.yaml 의 paths.*_dir 와 일치한다.
_DEV_WORKSPACE = REPO_ROOT / "data"

# CLI --workspace 등으로 주입되는 명시적 오버라이드. None 이면 env/settings 로 해석.
_override: Path | None = None


# ───────────────────────── 워크스페이스 해석 ─────────────────────────

def set_workspace_override(path: str | os.PathLike | None) -> None:
    """워크스페이스를 명시적으로 지정(CLI `--workspace`). None 이면 초기화."""
    global _override
    _override = Path(path).expanduser().resolve() if path else None


def _settings_workspace() -> Path | None:
    """config/settings.yaml 의 `paths.workspace`(있으면) → Path. 없거나 읽기 실패면 None."""
    cfg_file = REPO_ROOT / "config" / "settings.yaml"
    try:
        import yaml  # 지연 import: 이 경로가 안 타도 비용 0
        with open(cfg_file, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        val = ((raw.get("paths") or {}).get("workspace") or "")
        val = str(val).strip()
        if val:
            return Path(val).expanduser().resolve()
    except Exception:  # noqa: BLE001 — 설정 파일이 없거나 깨져도 폴백으로 진행
        pass
    return None


def _explicit_workspace() -> Path | None:
    """명시적으로 지정된 워크스페이스(override > env > settings.yaml). 없으면 None(=개발 폴백).

    None 을 반환하면 '개발 모드'다 — 호출부는 repo-local 기본값을 쓴다.
    """
    if _override is not None:
        return _override
    env = os.getenv("VOICEPRINT_WORKSPACE", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return _settings_workspace()


def is_workspace_mode() -> bool:
    """명시적 워크스페이스가 설정돼 있으면 True(=앱/명시 모드), 아니면 False(=개발 폴백)."""
    return _explicit_workspace() is not None


def get_workspace_root() -> Path:
    """런타임 데이터 루트. 개발 모드면 repo-local `data/`, 앱 모드면 사용자가 고른 폴더."""
    ws = _explicit_workspace()
    return ws if ws is not None else _DEV_WORKSPACE


# ───────────────────────── job 스코프 입력 ─────────────────────────

def get_input_root() -> Path:
    """입력 루트(`cfg.input_dir` 가 가리키던 곳)."""
    return get_workspace_root() / "input"


def get_input_dir(job: str) -> Path:
    return get_input_root() / job


def get_photos_dir(job: str) -> Path:
    return get_input_dir(job) / "photos"


def get_description_path(job: str) -> Path:
    return get_input_dir(job) / "description.txt"


# ───────────────────────── 초고(드래프트) ─────────────────────────

def get_drafts_root() -> Path:
    return get_workspace_root() / "drafts"


def get_drafts_dir(job: str) -> Path:
    return get_drafts_root() / job


# ───────────────────────── 수집(페르소나 학습) ─────────────────────────

def get_collected_root() -> Path:
    return get_workspace_root() / "collected"


def get_collected_dir(blog_id: str) -> Path:
    return get_collected_root() / blog_id


# ───────────────────────── 세션/인증(Playwright 프로필) ─────────────────────────

def get_auth_dir() -> Path:
    return get_workspace_root() / "auth"


# ───────────────────────── 로그(개발 모드는 repo 루트 유지) ─────────────────────────

def get_logs_dir() -> Path:
    ws = _explicit_workspace()
    return (ws / "logs") if ws is not None else (REPO_ROOT / "logs")


def get_screenshots_dir() -> Path:
    return get_logs_dir() / "screenshots"


def get_healing_history_path() -> Path:
    """셀렉터 자가치유 이력(JSONL)."""
    return get_logs_dir() / "healing-history.jsonl"


# ───────────────────────── 페르소나(개발 모드는 repo 루트 유지) ─────────────────────────

def get_persona_dir() -> Path:
    ws = _explicit_workspace()
    return (ws / "personas") if ws is not None else (REPO_ROOT / "personas")


# ───────────────────────── SEO DB / 크롤러 실패 로그 ─────────────────────────

def get_seo_db_path() -> Path:
    """blog_growth SQLite DB. 개발: data/blog_growth/blog_growth.db, 앱: <ws>/blog_growth/…"""
    return get_workspace_root() / "blog_growth" / "blog_growth.db"


def get_seo_failure_log_dir() -> Path:
    return get_logs_dir() / "seo_crawler_failures"


# ───────────────────────── 사용자 런타임 설정/오버라이드(워크스페이스 하위) ─────────────────────────

def get_user_config_dir() -> Path:
    return get_workspace_root() / "config"


def get_user_selectors_path() -> Path:
    """자가치유가 쓰는 사용자 셀렉터 오버라이드(번들 기본값을 덮어씀)."""
    return get_user_config_dir() / "selectors.user.yaml"


def get_user_workflows_path() -> Path:
    return get_user_config_dir() / "workflows.user.yaml"


# ───────────────────────── 번들 기본값(앱 코드와 함께 배포) ─────────────────────────

def get_default_selectors_path() -> Path:
    """번들된 기본 셀렉터(항상 안정 유지 — 자가치유는 여기 절대 안 씀)."""
    return REPO_ROOT / "config" / "selectors.yaml"


# ───────────────────────── 부트스트랩 ─────────────────────────

def ensure_runtime_dirs() -> None:
    """런타임 데이터 디렉터리들을 만든다(없으면). 기존 Config.ensure_dirs 와 동일 집합 + 호환."""
    for d in (
        get_collected_root(),
        get_input_root(),
        get_drafts_root(),
        get_auth_dir(),
        get_persona_dir(),
    ):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001 — 디렉터리 생성 실패가 전체를 막지 않게
            pass
