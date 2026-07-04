#!/usr/bin/env bash
# Voiceprint Studio — semi-packaged ZIP 배포 만들기(앱스토어 X, 선택 사용자 공유용).
#
#   bash scripts/create_distribution_zip.sh
#
# 산출물:
#   dist-local/VoiceprintStudio/         ← 깨끗한 배포 폴더(코드/설정/문서/스크립트만)
#   dist-local/VoiceprintStudio-mac.zip  ← 위 폴더를 압축한 공유용 ZIP
#
# 받는 사람: ZIP 압축 해제 → VoiceprintStudio/START_MAC.command 더블클릭(첫 실행에 자동 설치).
#
# ⚠️ 사용자 데이터/비밀은 절대 포함하지 않는다: data/·워크스페이스·photos·drafts·logs·auth·
#    .env·secrets·selectors.user.yaml·node_modules·.venv·빌드 산출물.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

OUT_DIR="$ROOT/dist-local"
STAGE="$OUT_DIR/VoiceprintStudio"
ZIP="$OUT_DIR/VoiceprintStudio-mac.zip"

echo "── 배포 스테이징: $STAGE ──"
rm -rf "$STAGE" "$ZIP"
mkdir -p "$STAGE"

# 배포에 포함할 항목만(필수 구조 + 문서 링크용 docs/·.env.example).
INCLUDE=(
  app src prompts config scripts
  main.py requirements.txt
  README_USER.md README_DEV.md
  START_MAC.command .gitignore
  docs .env.example
)

# 디렉터리 복사 시 제외할 런타임/빌드/비밀 산출물.
RSYNC_EXCLUDES=(
  --exclude 'node_modules'
  --exclude '.venv'
  --exclude 'dist'
  --exclude 'dist-local'
  --exclude '__pycache__'
  --exclude '*.pyc'
  --exclude '.pytest_cache'
  --exclude '.DS_Store'
  --exclude 'app.log'
  --exclude 'selectors.user.yaml'
  --exclude 'workflows.user.yaml'
  --exclude 'healing-history.jsonl'
  --exclude 'secrets.enc.json'
  --exclude 'app-config.json'
  --exclude '.env'
)

copy_item() {
  local item="$1"
  [ -e "$item" ] || { echo "  (건너뜀, 없음) $item"; return; }
  if [ -d "$item" ]; then
    rsync -a "${RSYNC_EXCLUDES[@]}" "$item" "$STAGE/"
  else
    cp "$item" "$STAGE/"
  fi
  echo "  + $item"
}

for it in "${INCLUDE[@]}"; do copy_item "$it"; done

# 안전망: 혹시라도 섞여 들어간 비밀/런타임 데이터 제거.
rm -f "$STAGE/.env" 2>/dev/null || true
find "$STAGE" \( -name 'selectors.user.yaml' -o -name 'workflows.user.yaml' \
  -o -name 'healing-history.jsonl' -o -name 'secrets.enc.json' \
  -o -name 'app-config.json' \) -delete 2>/dev/null || true
# data/·logs/·auth/·drafts/ 가 어떤 경로로든 들어왔으면 통째 제거(애초에 INCLUDE 에 없음).
rm -rf "$STAGE/data" "$STAGE/logs" 2>/dev/null || true

# 실행 권한.
chmod +x "$STAGE/START_MAC.command" 2>/dev/null || true
chmod +x "$STAGE/scripts/"*.sh 2>/dev/null || true

# ZIP 생성(폴더째).
( cd "$OUT_DIR" && zip -r -q "$ZIP" "VoiceprintStudio" -x '*.DS_Store' )

SIZE="$(du -sh "$ZIP" | cut -f1)"
echo
green() { printf "\033[32m%s\033[0m\n" "$1"; }
green "배포 폴더: $STAGE"
green "배포 ZIP : $ZIP ($SIZE)"
echo "받는 사람: ZIP 해제 → VoiceprintStudio/START_MAC.command 더블클릭(첫 실행에 자동 설치)."
