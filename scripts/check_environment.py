#!/usr/bin/env python3
"""환경 점검 — Voiceprint Studio 를 돌리는 데 필요한 도구가 갖춰졌는지 확인한다.

비기술 사용자/배포 대상이 실행해도 안전하게, 무엇이 되고 안 되는지 한눈에 보여준다.
앱(Electron)의 '환경 점검' 버튼과 동일한 항목을 CLI 로도 확인할 수 있게 한다.

    python scripts/check_environment.py

종료 코드: 필수 항목이 모두 OK 면 0, 하나라도 빠지면 1.
이 스크립트는 **아무것도 설치하지 않는다**(진단만). 설치는 scripts/bootstrap-mac.sh 참고.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

OK = "\033[32m✓\033[0m"
BAD = "\033[31m✗\033[0m"
WARN = "\033[33m!\033[0m"


def _run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except FileNotFoundError:
        return 127, "(명령을 찾을 수 없음)"
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def check_python() -> tuple[bool, str]:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 10)
    return ok, f"Python {v.major}.{v.minor}.{v.micro}" + ("" if ok else " (3.10+ 필요)")


def check_module(mod: str, label: str | None = None) -> tuple[bool, str]:
    label = label or mod
    try:
        m = __import__(mod)
        ver = getattr(m, "__version__", "")
        return True, f"{label} {ver}".strip()
    except Exception:  # noqa: BLE001
        return False, f"{label} 미설치 (pip install -r requirements.txt)"


def check_playwright_chromium() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception:
        return False, "playwright 미설치"
    code, out = _run([sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"])
    # --dry-run 은 'Install location: <경로>' 를 출력한다. 그 경로(첫 chromium 항목)가 실제로
    # 디스크에 있으면 설치된 것으로 본다(버전 무관·견고).
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("Install location:"):
            loc = s.split(":", 1)[1].strip()
            if "chromium" in loc.lower() and "headless" not in loc.lower() and Path(loc).exists():
                return True, f"Chromium 설치됨 ({Path(loc).name})"
    return False, "Chromium 미설치 (python -m playwright install chromium)"


def check_ffmpeg() -> tuple[bool, str]:
    path = shutil.which("ffmpeg")
    if not path:
        return False, "ffmpeg 미설치 (영상→움짤 기능에 필요. brew install ffmpeg)"
    code, out = _run(["ffmpeg", "-version"])
    first = out.split("\n")[0] if out else "ffmpeg"
    return code == 0, first


def check_claude() -> tuple[bool, str]:
    path = shutil.which("claude")
    if not path:
        return False, "claude CLI 미설치 (claude.ai/code 에서 설치 후 로그인)"
    code, out = _run(["claude", "--version"])
    return code == 0, (out.split("\n")[0] if out else f"claude ({path})")


def check_node() -> tuple[bool, str]:
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        missing = " / ".join(n for n, p in (("node", node), ("npm", npm)) if not p)
        return False, f"{missing} 없음 (데스크톱 앱 실행에 필요. https://nodejs.org LTS)"
    nv = _run(["node", "--version"])[1].split("\n")[0]
    pv = _run(["npm", "--version"])[1].split("\n")[0]
    return True, f"node {nv} · npm {pv}"


def check_workspace() -> tuple[bool, str]:
    """워크스페이스가 설정돼 있으면 그 폴더가 실제로 있는지 확인. 미설정이면 개발 기본값 안내."""
    try:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from blog_automation import paths  # noqa: WPS433
    except Exception as e:  # noqa: BLE001
        return True, f"(워크스페이스 모듈 로드 불가: {type(e).__name__}) — 무시 가능"
    root = paths.get_workspace_root()
    if not paths.is_workspace_mode():
        return True, f"미설정 → 개발 기본값(repo data/): {root}"
    exists = root.exists()
    return exists, ("설정됨" if exists else "설정됐으나 폴더 없음") + f": {root}"


def main() -> int:
    print("── Voiceprint 환경 점검 ──\n")
    # (라벨, 함수, 필수여부)
    checks = [
        ("Python 3.10+", check_python, True),
        ("pyyaml", lambda: check_module("yaml", "pyyaml"), True),
        ("python-dotenv", lambda: check_module("dotenv", "python-dotenv"), True),
        ("playwright", lambda: check_module("playwright"), True),
        ("requests", lambda: check_module("requests"), True),
        ("beautifulsoup4", lambda: check_module("bs4", "beautifulsoup4"), True),
        ("Playwright Chromium", check_playwright_chromium, True),
        ("claude CLI", check_claude, True),
        ("Node.js / npm (데스크톱 앱)", check_node, False),
        ("ffmpeg (영상→GIF)", check_ffmpeg, False),
        ("pillow-heif (HEIC)", lambda: check_module("pillow_heif", "pillow-heif"), False),
        ("gdown (드라이브 다운로드)", lambda: check_module("gdown"), False),
        ("워크스페이스 경로", check_workspace, False),
    ]
    required_ok = True
    for label, fn, required in checks:
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"점검 실패: {type(e).__name__}"
        mark = OK if ok else (BAD if required else WARN)
        tag = "" if required else "  (선택)"
        print(f"  {mark} {label:<26} {detail}{tag}")
        if required and not ok:
            required_ok = False

    # ANTHROPIC_API_KEY 경고(이 프로젝트는 구독형 claude CLI 만 쓴다 — API 과금 안 함).
    if os.getenv("ANTHROPIC_API_KEY"):
        print(f"\n  {WARN} ANTHROPIC_API_KEY 가 설정돼 있습니다 — 이 앱은 구독형 Claude Code CLI 만 "
              "사용하며 API 과금을 쓰지 않습니다. 키를 비워두는 것을 권장합니다.")

    print()
    if required_ok:
        print(f"{OK} 필수 항목이 모두 준비됐습니다.")
        return 0
    print(f"{BAD} 일부 필수 항목이 빠졌습니다 — 위 안내대로 설치하세요 "
          "(또는 scripts/bootstrap-mac.sh).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
