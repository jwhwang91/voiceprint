#!/usr/bin/env bash
# Voiceprint Studio — macOS 부트스트랩(설치/점검).
#
# 비기술 사용자도 한 번 실행하면 필요한 것들을 설치/점검한다. 멱등(여러 번 돌려도 안전).
# 이 스크립트는 절대 개발자의 절대경로를 가정하지 않는다 — 자기 위치 기준으로 repo 루트를 찾는다.
#
#   bash scripts/bootstrap-mac.sh
#
# 하는 일:
#   1) Python 3.10+ 확인           4) Playwright Chromium 설치
#   2) 가상환경(.venv) 생성/활성화   5) ffmpeg 안내(영상→GIF, 선택)
#   3) pip 의존성 설치              6) Node/npm + Electron 앱 의존성
#   7) Claude Code CLI 설치/로그인 안내
set -uo pipefail

# repo 루트 = 이 스크립트의 부모의 부모(scripts/ → repo).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

green() { printf "\033[32m%s\033[0m\n" "$1"; }
yellow() { printf "\033[33m%s\033[0m\n" "$1"; }
red() { printf "\033[31m%s\033[0m\n" "$1"; }

echo "── Voiceprint 부트스트랩 (repo: $ROOT) ──"

# 1) Python 3.10+
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  red "Python 이 없습니다. https://www.python.org/downloads/ 에서 3.10+ 를 설치하세요."
  exit 1
fi
PYV="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
green "Python $PYV 발견 ($PY)"
"$PY" -c 'import sys;raise SystemExit(0 if sys.version_info[:2]>=(3,10) else 1)' || {
  red "Python 3.10+ 가 필요합니다 (현재 $PYV)."; exit 1; }

# 2) venv
if [ ! -d ".venv" ]; then
  echo "가상환경(.venv) 생성 중…"
  "$PY" -m venv .venv || { red "venv 생성 실패"; exit 1; }
fi
# shellcheck disable=SC1091
source .venv/bin/activate
green "가상환경 활성화: $(command -v python)"

# 3) pip 의존성
echo "pip 의존성 설치 중(requirements.txt)…"
python -m pip install --upgrade pip >/dev/null 2>&1 || true
if python -m pip install -r requirements.txt; then
  green "pip 의존성 설치 완료"
else
  red "pip 의존성 설치 실패 — 위 오류를 확인하세요."
fi

# 4) Playwright Chromium
echo "Playwright Chromium 설치/확인 중…"
python -m playwright install chromium && green "Chromium 준비됨" || yellow "Chromium 설치에 문제 — 나중에 'python -m playwright install chromium' 재시도"

# 5) ffmpeg (선택 — 영상→GIF)
if command -v ffmpeg >/dev/null 2>&1; then
  green "ffmpeg 발견 ($(ffmpeg -version 2>/dev/null | head -1))"
else
  yellow "ffmpeg 없음(영상→움짤 기능에 필요). 설치: brew install ffmpeg"
fi

# 6) Node/npm + Electron 앱 의존성
if command -v npm >/dev/null 2>&1; then
  green "npm 발견 ($(npm -v))"
  if [ -d "app" ]; then
    echo "Electron 앱 의존성 설치 중(app/)…"
    ( cd app && npm install ) && green "앱 의존성 설치 완료" || yellow "앱 의존성 설치 문제 — 'cd app && npm install' 재시도(또는 npm run rebuild)"
  fi
else
  yellow "Node/npm 없음(데스크톱 앱 실행에 필요). https://nodejs.org 에서 LTS 설치."
fi

# 7) Claude Code CLI
if command -v claude >/dev/null 2>&1; then
  green "Claude Code CLI 발견 ($(claude --version 2>/dev/null | head -1))"
  yellow "→ 로그인 상태 확인: 터미널에서 'claude' 실행 후 '/status' 로 구독 로그인 확인."
else
  red "Claude Code CLI 없음 — 이 앱의 핵심입니다."
  echo "   설치: https://claude.ai/code  (설치 후 'claude' 실행해 구독 계정으로 로그인)"
fi

# ⚠️ API 키 경고
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  yellow "⚠ ANTHROPIC_API_KEY 가 설정돼 있습니다 — 이 앱은 구독형 Claude Code CLI 만 쓰며 API 과금을 쓰지 않습니다. 비워두는 것을 권장합니다."
fi

echo
echo "최종 점검:"
python scripts/check_environment.py || true
echo
green "부트스트랩 끝. 앱 실행: ./START_MAC.command  (또는  python main.py)"
