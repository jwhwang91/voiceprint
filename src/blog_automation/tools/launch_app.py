"""데스크톱 앱(Voiceprint Studio) 실행/포커스.

`python main.py`(인자 없음) 또는 `python main.py app` 으로 호출된다.
이미 떠 있으면(CDP 포트 9223 점유) 중복 실행하지 않고 창만 앞으로 가져온다.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

CDP_PORT = 9223
_ROOT = Path(__file__).resolve().parents[3]  # tools → blog_automation → src → repo root
_APP = _ROOT / "app"


def _is_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", CDP_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def _bring_to_front() -> None:
    if sys.platform == "darwin":
        try:
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to set frontmost of '
                 '(first process whose name is "Electron") to true'],
                timeout=5, capture_output=True)
        except Exception:
            pass


def _electron_bin() -> Path | None:
    for c in (
        _APP / "node_modules" / ".bin" / "electron",
        _APP / "node_modules" / "electron" / "dist" / "Electron.app" / "Contents" / "MacOS" / "Electron",
    ):
        if c.exists():
            return c
    return None


def run_app() -> None:
    if _is_running():
        print("Voiceprint Studio 가 이미 실행 중입니다 — 창을 앞으로 가져옵니다.")
        _bring_to_front()
        return

    if not (_APP / "node_modules").exists():
        print("앱 의존성이 아직 설치되지 않았습니다. 먼저 한 번:")
        print(f"  cd {_APP} && npm install")
        return

    binp = _electron_bin()
    if binp is None:
        print("Electron 바이너리를 찾지 못했습니다. 먼저:")
        print(f"  cd {_APP} && npm install   (그래도 안되면 npm run fix-electron)")
        return

    print("Voiceprint Studio 를 실행합니다…")
    log = open(_APP / "app.log", "ab", buffering=0)
    subprocess.Popen(
        [str(binp), "."],
        cwd=str(_APP),
        stdout=log, stderr=log,
        start_new_session=True,  # 부모(python)가 끝나도 앱은 계속 떠 있게 분리
    )
    for _ in range(20):  # 부팅 대기(최대 10초)
        if _is_running():
            break
        time.sleep(0.5)
    _bring_to_front()
    print("실행됨. 창이 안 보이면 Mission Control / 다른 Space 를 확인하세요.")
