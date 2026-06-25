// 자격증명 보안 저장소 — safeStorage(OS 키체인)로 암호화해 userData 에 저장.
// .env 파일을 쓰지 않는다. 저장된 값은 PTY 스폰 시 환경변수로 주입되어 python 이 os.getenv 로 읽는다.
const { app, safeStorage } = require('electron');
const fs = require('fs');
const path = require('path');

// 신용정보 인벤토리에서 확정된 env 변수 키들. (발행: NAVER_ID/PW · SEO: 나머지)
const KEYS = [
  'NAVER_ID',
  'NAVER_PW',
  'NAVER_CLIENT_ID',
  'NAVER_CLIENT_SECRET',
  'NAVER_SEARCHAD_ACCESS_LICENSE',
  'NAVER_SEARCHAD_SECRET_KEY',
  'NAVER_SEARCHAD_CUSTOMER_ID',
];

function file() {
  return path.join(app.getPath('userData'), 'secrets.enc.json');
}

function loadRaw() {
  try { return JSON.parse(fs.readFileSync(file(), 'utf8')); } catch (_) { return {}; }
}

// { KEY: plaintext } — main 전용(렌더러로 평문 안 보냄). 비어있는 키는 생략.
function loadSecrets() {
  const raw = loadRaw();
  const out = {};
  for (const k of KEYS) {
    const v = raw[k];
    if (!v) continue;
    try {
      if (v.enc && safeStorage.isEncryptionAvailable()) {
        out[k] = safeStorage.decryptString(Buffer.from(v.enc, 'base64'));
      } else if (typeof v.plain === 'string') {
        out[k] = v.plain;
      }
    } catch (_) {}
  }
  return out;
}

// 렌더러용: 각 키가 저장돼 있는지 여부만(평문 노출 X).
function presence() {
  const s = loadSecrets();
  const out = {};
  for (const k of KEYS) out[k] = !!s[k];
  return out;
}

// values: { KEY: '값' | null }. 빈/누락 = 변경 없음, null = 삭제, 그 외 문자열 = 갱신.
function save(values) {
  const raw = loadRaw();
  const canEnc = safeStorage.isEncryptionAvailable();
  for (const k of KEYS) {
    if (!(k in values)) continue;
    const val = values[k];
    if (val === null) { delete raw[k]; continue; }
    if (typeof val !== 'string' || val === '') continue; // 빈 입력 = 유지
    raw[k] = canEnc
      ? { enc: safeStorage.encryptString(val).toString('base64') }
      : { plain: val }; // 키체인 불가 환경 폴백(그래도 repo .env 아님)
  }
  fs.writeFileSync(file(), JSON.stringify(raw), { mode: 0o600 });
  return presence();
}

module.exports = { KEYS, loadSecrets, presence, save, encryptionAvailable: () => {
  try { return safeStorage.isEncryptionAvailable(); } catch (_) { return false; }
} };
