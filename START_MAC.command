#!/usr/bin/env bash
# Voiceprint Studio — 더블클릭 실행기(macOS, semi-packaged ZIP 배포용).
# Finder 에서 더블클릭하면 이 파일이 자기 폴더에서 환경을 준비하고 앱(Electron)을 띄운다.
#   처음 실행: Python venv 생성 + 의존성 설치 + Playwright Chromium + 앱(npm) 설치 → 실행.
#   이후 실행: 빠르게 바로 실행.
set -uo pipefail

# 1) 자기 폴더(= 배포 루트)로 이동. 개발자 절대경로를 가정하지 않는다.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

green() { printf "\033[32m%s\033[0m\n" "$1"; }
yellow() { printf "\033[33m%s\033[0m\n" "$1"; }
red() { printf "\033[31m%s\033[0m\n" "$1"; }
pause_exit() { read -r -p "엔터를 누르면 이 창이 닫힙니다…" _; exit "${1:-1}"; }

echo "── Voiceprint Studio ──  ($ROOT)"

# 2) Claude Code CLI 확인(핵심 의존성). 이 앱은 '당신의 Claude 구독 로그인'만 씁니다(API 키 아님).
if ! command -v claude >/dev/null 2>&1; then
  red "Claude Code CLI 가 설치/로그인돼 있지 않습니다."
  echo "이 앱은 당신의 Claude Code '구독' 로그인을 사용합니다(추가 API 과금 없음)."
  echo "  1) https://claude.ai/code 에서 Claude Code 설치"
  echo "  2) 터미널에서  claude  를 한 번 실행해 구독 계정으로 로그인"
  echo "  3) 다시 이 START_MAC.command 를 더블클릭"
  pause_exit 1
fi
green "Claude Code CLI 확인됨 ($(claude --version 2>/dev/null | head -1))"

# ⚠️ API 키 경고(이 앱은 구독형 CLI 만 쓰며 API 과금을 의도하지 않음).
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  yellow "⚠ ANTHROPIC_API_KEY 가 설정돼 있습니다 — 이 앱은 구독형 Claude Code CLI 만 쓰며 API 과금을 쓰지 않습니다(키 비우길 권장)."
fi

# 3) python3 확인.
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  red "python3 가 없습니다. https://www.python.org/downloads/ 에서 Python 3.10+ 를 설치한 뒤 다시 실행하세요."
  pause_exit 1
fi
green "python3 확인됨 ($("$PY" --version 2>&1))"

# 4) .venv 생성(없으면) — 처음 실행이면 무거운 설치 단계를 수행.
FIRST_RUN=0
if [ ! -d ".venv" ]; then
  FIRST_RUN=1
  echo "가상환경(.venv) 생성 중…"
  "$PY" -m venv .venv || { red "venv 생성 실패."; pause_exit 1; }
fi

# 5) .venv 활성화.
# shellcheck disable=SC1091
source .venv/bin/activate || { red ".venv 활성화 실패."; pause_exit 1; }

if [ "$FIRST_RUN" -eq 1 ]; then
  # 6) requirements 설치.
  echo "Python 의존성 설치 중(requirements.txt) — 잠시 기다려 주세요…"
  python -m pip install --upgrade pip >/dev/null 2>&1 || true
  python -m pip install -r requirements.txt || { red "의존성 설치 실패 — 위 오류를 확인하세요."; pause_exit 1; }

  # 7) Playwright Chromium 설치.
  echo "Playwright Chromium 설치 중…"
  python -m playwright install chromium || yellow "Chromium 설치에 문제가 있었어요 — 나중에 'python -m playwright install chromium' 로 다시 시도하세요."
fi

# 8) ffmpeg 확인(영상→움짤에 필요) — 없어도 막지 않고 경고만.
if command -v ffmpeg >/dev/null 2>&1; then
  green "ffmpeg 확인됨"
else
  yellow "ffmpeg 없음(영상→움짤 기능에만 필요). 설치: brew install ffmpeg — 없어도 글쓰기/발행은 됩니다."
fi

# 9) app 으로 이동 → node_modules 없으면 npm install.
cd "$ROOT/app" || { red "app 폴더를 찾지 못했습니다."; pause_exit 1; }
if ! command -v npm >/dev/null 2>&1; then
  red "npm(Node.js) 이 없습니다. 데스크톱 앱 실행에 필요합니다 — https://nodejs.org 에서 LTS 설치 후 다시 실행하세요."
  pause_exit 1
fi
if [ ! -d "node_modules" ]; then
  echo "앱 의존성 설치 중(npm install) — 처음 한 번, 잠시 기다려 주세요…"
  npm install || { red "앱 의존성 설치 실패. 'cd app && npm install'(필요 시 npm run rebuild) 로 재시도하세요."; pause_exit 1; }
fi

# 10) 앱 실행(Electron). 이미 떠 있으면 새 인스턴스는 종료되고 기존 창이 앞으로 옵니다.
green "앱을 실행합니다…"
npm start
