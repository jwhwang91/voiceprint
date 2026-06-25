// Voiceprint Studio — main process
// v0: 사용자가 직접 로그인한 claude CLI 를 PTY 로 띄움(헤드리스/SDK X → 구독 과금).
// v1 추가:
//  - 네이버 발행 화면을 앱 안에 임베드(WebContentsView, persist:naver) + CDP 로 기존 Python 발행기가 조작.
//  - 자격증명을 safeStorage 로 저장하고 PTY 에 환경변수로 주입(.env 파일 안 씀).

const { app, BrowserWindow, WebContentsView, ipcMain, webUtils } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawnSync } = require('child_process');
const secrets = require('./settings-store');

let pty = null;
let ptyLoadError = null;
try {
  pty = require('node-pty');
} catch (e) {
  ptyLoadError = e.message;
}

const PROJECT_ROOT = path.resolve(__dirname, '..', '..');
const LOGIN_SHELL = process.env.SHELL || '/bin/zsh';
const CDP_PORT = 9223;
const CDP_ENDPOINT = `http://127.0.0.1:${CDP_PORT}`;
const RAIL_W = 264;   // 우측 버튼 레일 폭(렌더러 CSS 와 일치)
const HEADER_H = 46;  // 상단 바 높이(렌더러 CSS 와 일치)

// Playwright(connect_over_cdp)가 붙을 수 있도록 CDP 포트 + origin 허용. app ready 전에 설정해야 함.
app.commandLine.appendSwitch('remote-debugging-port', String(CDP_PORT));
app.commandLine.appendSwitch('remote-allow-origins', '*');

let win = null;
let ptyProc = null;
let naverView = null;

// --- GUI 앱은 로그인 셸 PATH 를 못 물려받는다. 로그인 셸을 거쳐 PATH/claude 를 해석한다. ---
function loginPath() {
  try {
    const out = spawnSync(LOGIN_SHELL, ['-lic', 'printf %s "$PATH"'], { encoding: 'utf8', timeout: 8000 });
    const p = (out.stdout || '').trim();
    if (p) return p;
  } catch (_) {}
  return process.env.PATH || '';
}

function resolveClaude() {
  try {
    const out = spawnSync(LOGIN_SHELL, ['-lic', 'command -v claude'], { encoding: 'utf8', timeout: 8000 });
    const found = (out.stdout || '').trim().split('\n').filter(Boolean).pop();
    if (found && fs.existsSync(found)) return found;
  } catch (_) {}
  const candidates = [
    path.join(os.homedir(), '.local/bin/claude'),
    '/opt/homebrew/bin/claude',
    '/usr/local/bin/claude',
  ];
  for (const c of candidates) if (fs.existsSync(c)) return c;
  return null;
}

// PTY 환경: PATH + CDP 엔드포인트 + 저장된 자격증명(.env 대체).
function ptyEnv() {
  return {
    ...process.env,
    PATH: loginPath(),
    TERM: 'xterm-256color',
    VOICEPRINT_CDP_ENDPOINT: CDP_ENDPOINT, // python 발행기가 이 화면에 붙음
    ...secrets.loadSecrets(),              // NAVER_ID/PW(선택) · API 키들
  };
}

function startPty() {
  if (!pty) {
    setTimeout(() => {
      if (win) win.webContents.send('pty:data',
        `\r\n\x1b[31m[node-pty 로드 실패]\x1b[0m ${ptyLoadError}\r\n` +
        `\x1b[33mapp/ 에서  npm run rebuild  실행 후 다시 켜세요.\x1b[0m\r\n`);
    }, 300);
    return;
  }
  ptyProc = pty.spawn(LOGIN_SHELL, [], {
    name: 'xterm-256color',
    cols: 100,
    rows: 30,
    cwd: PROJECT_ROOT,
    env: ptyEnv(),
  });
  ptyProc.onData((d) => { if (win) win.webContents.send('pty:data', d); });
  ptyProc.onExit(() => { ptyProc = null; });
}

function restartPty() {
  if (ptyProc) { try { ptyProc.kill(); } catch (_) {} ptyProc = null; }
  if (win) win.webContents.send('pty:data', '\r\n\x1b[36m[세션 재시작 — 새 설정 적용됨]\x1b[0m\r\n');
  startPty();
}

// --- 네이버 임베드 뷰 (발행 화면) ---
// ⚠️ 한글 IME: 창에 붙은(attached) WebContentsView 는 숨겨도 host 창의 IME 를 가로채는
//    Electron 이슈가 있다. 그래서 평소엔 분리(detach)해 두고 '보일 때만' 붙인다.
//    webContents 자체는 백그라운드로 살아 naver.com 을 로드 → CDP 타깃으로 항상 존재(발행 attach 가능).
let naverAttached = false;
function naverBounds() {
  const [w, h] = win.getContentSize();
  return { x: 0, y: HEADER_H, width: Math.max(0, w - RAIL_W), height: Math.max(0, h - HEADER_H) };
}

function positionNaverView() {
  if (naverView && win && naverAttached) naverView.setBounds(naverBounds());
}

function setNaverVisible(v) {
  if (!naverView || !win) return;
  if (v && !naverAttached) { win.contentView.addChildView(naverView); naverAttached = true; }
  else if (!v && naverAttached) { win.contentView.removeChildView(naverView); naverAttached = false; }
  if (naverAttached) { positionNaverView(); naverView.setVisible(true); }
  win.webContents.send('naver:visibility', naverAttached);
}

function createNaverView() {
  naverView = new WebContentsView({ webPreferences: { partition: 'persist:naver' } });
  // 일부러 addChildView 안 함(분리 상태) — 한글 IME 가로채기 방지. 보일 때만 attach.
  naverView.webContents.loadURL('https://www.naver.com').catch(() => {});

  // python 발행기가 에디터로 이동하면 화면을 자동으로 앞으로.
  naverView.webContents.on('did-navigate', (_e, url) => {
    if (/blog\.naver\.com\/[^/]+\/postwrite/.test(url || '')) setNaverVisible(true);
  });
  // 새 창 요청은 같은 뷰에서 열기(팝업 난립 방지).
  naverView.webContents.setWindowOpenHandler(({ url }) => {
    naverView.webContents.loadURL(url).catch(() => {});
    return { action: 'deny' };
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1180,
    height: 760,
    minWidth: 920,
    minHeight: 580,
    backgroundColor: '#0b0e14',
    title: 'Voiceprint Studio',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  win.on('resize', positionNaverView);
  win.on('closed', () => { win = null; naverView = null; });
  createNaverView();
  startPty();
}

// --- IPC: PTY ---
ipcMain.on('pty:input', (_e, data) => { if (ptyProc) ptyProc.write(data); });
ipcMain.on('pty:resize', (_e, { cols, rows }) => {
  if (ptyProc && cols > 0 && rows > 0) { try { ptyProc.resize(cols, rows); } catch (_) {} }
});
ipcMain.handle('session:restart', () => { restartPty(); return true; });

// --- IPC: 네이버 뷰 ---
ipcMain.handle('naver:show', (_e, show) => { setNaverVisible(show); return !!show; });
ipcMain.handle('naver:login', () => {
  if (naverView) naverView.webContents.loadURL('https://nid.naver.com/nidlogin.login').catch(() => {});
  setNaverVisible(true);
  return true;
});
ipcMain.handle('naver:home', () => {
  if (naverView) naverView.webContents.loadURL('https://www.naver.com').catch(() => {});
  return true;
});

// --- IPC: 온보딩/설정 ---
ipcMain.handle('onboarding:status', () => {
  const bin = resolveClaude();
  let version = null;
  if (bin) {
    try {
      const out = spawnSync(bin, ['--version'], { encoding: 'utf8', timeout: 8000 });
      version = (out.stdout || '').trim() || null;
    } catch (_) {}
  }
  return { installed: !!bin, bin, version, projectRoot: PROJECT_ROOT, cdp: CDP_ENDPOINT };
});

ipcMain.handle('settings:keys', () => ({ keys: secrets.KEYS, presence: secrets.presence(), encrypted: secrets.encryptionAvailable() }));
ipcMain.handle('settings:save', (_e, values) => secrets.save(values || {}));

// --- IPC: 새 글 폴더 + 드롭 적재 ---
function ingestInto(src, destDir, stats) {
  let st;
  try { st = fs.statSync(src); } catch (_) { return; }
  if (st.isDirectory()) {
    const base = path.basename(src);
    if (base === '__MACOSX') return;
    const sub = path.join(destDir, base);
    fs.mkdirSync(sub, { recursive: true });
    for (const name of fs.readdirSync(src)) ingestInto(path.join(src, name), sub, stats);
    return;
  }
  const ext = path.extname(src).toLowerCase();
  const base = path.basename(src);
  if (base.startsWith('.')) return;
  const target = path.join(destDir, base);
  try { fs.copyFileSync(src, target); stats.count++; } catch (_) { return; }
  if (ext === '.heic' && process.platform === 'darwin') {
    const jpg = target.replace(/\.heic$/i, '.jpg');
    try {
      spawnSync('sips', ['-s', 'format', 'jpeg', target, '--out', jpg], { timeout: 20000 });
      if (fs.existsSync(jpg)) stats.converted++;
    } catch (_) {}
  }
  if (ext === '.mov' || ext === '.mp4') stats.videos++;
}

ipcMain.handle('job:new', (_e, job) => {
  const safe = String(job || '').trim();
  if (!safe) throw new Error('빈 job 이름');
  const jobDir = path.join(PROJECT_ROOT, 'data', 'input', safe);
  const dir = path.join(jobDir, 'photos');
  const existed = fs.existsSync(jobDir);
  fs.mkdirSync(dir, { recursive: true });
  return { job: safe, dir, existed };
});

ipcMain.handle('jobs:list', () => {
  const base = path.join(PROJECT_ROOT, 'data', 'input');
  try {
    return fs.readdirSync(base, { withFileTypes: true })
      .filter((e) => e.isDirectory() && !e.name.startsWith('.') && !e.name.startsWith('__'))
      .map((e) => e.name)
      .sort();
  } catch (_) { return []; }
});

ipcMain.handle('files:ingest', (_e, { job, paths }) => {
  const safe = String(job || '').trim();
  if (!safe) throw new Error('현재 job 없음');
  const dest = path.join(PROJECT_ROOT, 'data', 'input', safe, 'photos');
  fs.mkdirSync(dest, { recursive: true });
  const stats = { count: 0, converted: 0, videos: 0 };
  for (const p of (paths || [])) if (p) ingestInto(p, dest, stats);
  return { dest, ...stats };
});

// 현재 job 의 photos/ 안 미디어를 재귀로 나열(UI 칩 목록용). HEIC 는 변환된 jpg 가 있으면 숨김.
const _IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.heic']);
const _VIDEO_EXTS = new Set(['.mov', '.mp4']);
function listMedia(job) {
  const dir = path.join(PROJECT_ROOT, 'data', 'input', String(job || '').trim(), 'photos');
  const out = [];
  (function walk(d) {
    let entries;
    try { entries = fs.readdirSync(d, { withFileTypes: true }); } catch (_) { return; }
    for (const e of entries) {
      if (e.name.startsWith('.') || e.name === '__MACOSX') continue;
      const full = path.join(d, e.name);
      if (e.isDirectory()) { walk(full); continue; }
      const ext = path.extname(e.name).toLowerCase();
      let kind = 'other';
      if (ext === '.gif') kind = 'gif';
      else if (_IMAGE_EXTS.has(ext)) kind = 'image';
      else if (_VIDEO_EXTS.has(ext)) kind = 'video';
      out.push({ name: e.name, kind });
    }
  })(dir);
  const jpgStems = new Set(
    out.filter((f) => /\.jpe?g$/i.test(f.name)).map((f) => f.name.replace(/\.[^.]+$/, '')));
  return out.filter((f) => !(/\.heic$/i.test(f.name) && jpgStems.has(f.name.replace(/\.[^.]+$/, ''))));
}
ipcMain.handle('files:list', (_e, job) => { try { return listMedia(job); } catch (_) { return []; } });

// 싱글 인스턴스 — 두 번 실행돼도 새 창 대신 기존 창을 포커스(포트 9223 충돌 방지).
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
    }
  });
  app.whenReady().then(createWindow);
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
}
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('before-quit', () => { if (ptyProc) { try { ptyProc.kill(); } catch (_) {} } });
