# Voiceprint Studio - Windows 부트스트랩(설치/점검). PowerShell.
#
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap-windows.ps1
#
# 멱등(여러 번 실행해도 안전). 개발자 절대경로를 가정하지 않는다.
# 참고: 네이버 발행/임베드 뷰는 macOS 에서 주로 검증됐다. Windows 는 베스트에포트.
$ErrorActionPreference = "Stop"

function Green($m){ Write-Host $m -ForegroundColor Green }
function Yellow($m){ Write-Host $m -ForegroundColor Yellow }
function Red($m){ Write-Host $m -ForegroundColor Red }

# repo 루트 = 이 스크립트의 부모의 부모.
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
Write-Host "-- Voiceprint 부트스트랩 (repo: $Root) --"

# 1) Python 3.10+
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { Red "Python 이 없습니다. https://www.python.org/downloads/ 에서 3.10+ 설치(‘Add to PATH’ 체크)."; exit 1 }
$pyv = (python -c "import sys;print('%d.%d'%sys.version_info[:2])")
Green "Python $pyv 발견"
$okv = (python -c "import sys;print(1 if sys.version_info[:2]>=(3,10) else 0)")
if ($okv.Trim() -ne "1") { Red "Python 3.10+ 가 필요합니다 (현재 $pyv)."; exit 1 }

# 2) venv
if (-not (Test-Path ".venv")) { Write-Host "가상환경(.venv) 생성 중..."; python -m venv .venv }
& ".\.venv\Scripts\Activate.ps1"
Green "가상환경 활성화"

# 3) pip 의존성
Write-Host "pip 의존성 설치 중(requirements.txt)..."
python -m pip install --upgrade pip | Out-Null
python -m pip install -r requirements.txt
Green "pip 의존성 설치 완료"

# 4) Playwright Chromium
Write-Host "Playwright Chromium 설치/확인 중..."
python -m playwright install chromium
Green "Chromium 준비됨"

# 5) ffmpeg (선택)
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { Green "ffmpeg 발견" }
else { Yellow "ffmpeg 없음(영상->움짤에 필요). https://www.gyan.dev/ffmpeg/builds/ 등에서 설치 후 PATH 추가." }

# 6) Node/npm + 앱 의존성
if (Get-Command npm -ErrorAction SilentlyContinue) {
  Green "npm 발견"
  if (Test-Path "app") { Push-Location app; npm install; Pop-Location; Green "앱 의존성 설치 완료" }
} else { Yellow "Node/npm 없음(데스크톱 앱 실행에 필요). https://nodejs.org LTS 설치." }

# 7) Claude Code CLI
if (Get-Command claude -ErrorAction SilentlyContinue) {
  Green "Claude Code CLI 발견 ($(claude --version))"
  Yellow "-> 'claude' 실행 후 '/status' 로 구독 로그인 확인."
} else {
  Red "Claude Code CLI 없음 - 이 앱의 핵심입니다. https://claude.ai/code 에서 설치 후 로그인."
}

# API 키 경고
if ($env:ANTHROPIC_API_KEY) {
  Yellow "! ANTHROPIC_API_KEY 가 설정돼 있습니다 - 이 앱은 구독형 Claude Code CLI 만 쓰며 API 과금을 쓰지 않습니다. 비워두는 것을 권장."
}

Write-Host ""
python scripts\check_environment.py
Green "부트스트랩 끝. 앱 실행: python main.py"
