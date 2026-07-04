// 워크스페이스(런타임 데이터 루트) 저장소.
// 사용자가 고른 폴더 경로를 userData/app-config.json 에 저장한다. Python 에는 PTY 환경변수
// VOICEPRINT_WORKSPACE 로 주입되어 src/blog_automation/paths.py 가 같은 루트를 쓰게 한다.
//
// ⚠️ 사용자 데이터(입력 사진·초고·세션·로그·셀렉터 패치)는 모두 이 폴더 아래로 간다 →
//    앱 코드 업데이트가 사용자 데이터를 지우지 않는다.
const { app } = require('electron');
const fs = require('fs');
const path = require('path');
const os = require('os');

function file() {
  return path.join(app.getPath('userData'), 'app-config.json');
}

function loadRaw() {
  try { return JSON.parse(fs.readFileSync(file(), 'utf8')); } catch (_) { return {}; }
}

function saveRaw(obj) {
  try { fs.writeFileSync(file(), JSON.stringify(obj, null, 2), { mode: 0o600 }); } catch (_) {}
}

// macOS 권장 기본 위치.
function defaultPath() {
  return path.join(os.homedir(), 'Documents', 'VoiceprintWorkspace');
}

// 저장된 경로(없으면 null). '한 번도 안 골랐는지' 판단용.
function getStored() {
  const v = loadRaw().workspace;
  return (typeof v === 'string' && v.trim()) ? v.trim() : null;
}

// 실제로 쓸 경로(저장값 || 기본값). 항상 구체 경로를 돌려준다.
function resolve() {
  return getStored() || defaultPath();
}

function set(p) {
  const raw = loadRaw();
  raw.workspace = String(p || '').trim();
  saveRaw(raw);
  return resolve();
}

// 워크스페이스 하위 표준 폴더들을 만든다(없으면).
function ensureDirs(root) {
  const base = root || resolve();
  for (const sub of ['input', 'drafts', 'collected', 'auth', 'logs', 'personas', 'config']) {
    try { fs.mkdirSync(path.join(base, sub), { recursive: true }); } catch (_) {}
  }
  return base;
}

module.exports = { defaultPath, getStored, resolve, set, ensureDirs, isChosen: () => !!getStored() };
