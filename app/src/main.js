// Voiceprint Studio — main process
// v0: 사용자가 직접 로그인한 claude CLI 를 PTY 로 띄움(헤드리스/SDK X → 구독 과금).
// v1 추가:
//  - 네이버 발행 화면을 앱 안에 임베드(WebContentsView, persist:naver) + CDP 로 기존 Python 발행기가 조작.
//  - 자격증명을 safeStorage 로 저장하고 PTY 에 환경변수로 주입(.env 파일 안 씀).
// v2(배포): getCoreRoot() 로 개발/ZIP/패키징(.app) 모드 모두에서 파이썬 코어 경로를 해석.
//
// ⚠️ TODO(향후 풀 번들링): 지금은 'semi-packaged' — 사용자의 Python3 + 첫 실행 .venv 설치에 의존한다.
//   다음 단계로 (1) PyInstaller 로 voiceprint-core 단일 바이너리, (2) Playwright Chromium 번들,
//   (3) ffmpeg 번들, (4) macOS 코드서명/공증(notarize) 을 추가하면 Python 미설치 사용자도 지원 가능.
//   그 전까지 패키징(.app) 모드는 실험적이며, 권장 배포 경로는 ZIP(START_MAC.command) 이다.

const { app, BrowserWindow, WebContentsView, ipcMain, webUtils, dialog, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawnSync } = require('child_process');
const secrets = require('./settings-store');
const workspace = require('./workspace-store');

// 워크스페이스(런타임 데이터 루트) — 모든 입력/초고/세션/로그가 이 폴더 아래로 간다.
// Python 에는 ptyEnv() 가 VOICEPRINT_WORKSPACE 로 주입한다.
function ws() { return workspace.resolve(); }
function inputDir(job) { return path.join(ws(), 'input', String(job || '').trim()); }
function photosDir(job) { return path.join(inputDir(job), 'photos'); }

let pty = null;
let ptyLoadError = null;
try {
  pty = require('node-pty');
} catch (e) {
  ptyLoadError = e.message;
}

const PROJECT_ROOT = path.resolve(__dirname, '..', '..');

// 프로젝트 코어(파이썬 측: main.py·src·prompts·config·scripts) 위치.
//  · 개발/ZIP(semi-packaged) 모드: repo 루트(= app/ 의 상위). `python main.py` 가 여기서 돈다.
//  · 패키징(electron-builder .app) 모드: Resources/voiceprint-core (package.json build.extraResources).
function getCoreRoot() {
  if (app.isPackaged) return path.join(process.resourcesPath, 'voiceprint-core');
  return PROJECT_ROOT;
}

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

// venv 위치: 개발/ZIP 은 코어 루트의 .venv(쓰기 가능), 패키징 은 Resources 가 읽기전용이라
// 쓰기 가능한 userData/voiceprint-venv 를 쓴다.
function venvDir() {
  if (app.isPackaged) return path.join(app.getPath('userData'), 'voiceprint-venv');
  return path.join(getCoreRoot(), '.venv');
}
// venv bin 경로(python 실행파일이 있으면), 없으면 null. 부트스트랩이 만든 venv 의 의존성을
// PTY/환경점검이 쓰게 한다(로그인 셸 PATH 는 venv 를 모르므로).
function venvBin() {
  const isWin = process.platform === 'win32';
  const cand = path.join(venvDir(), isWin ? 'Scripts' : 'bin');
  return fs.existsSync(path.join(cand, isWin ? 'python.exe' : 'python')) ? cand : null;
}
// 실행할 python 명령(venv 우선, 없으면 시스템 python3). spawnSync/runPythonCommand 용.
function getPythonCommand() {
  const vb = venvBin();
  if (vb) return path.join(vb, process.platform === 'win32' ? 'python.exe' : 'python');
  return process.platform === 'win32' ? 'python' : 'python3';
}

// python 명령을 코어 루트에서 실행(워크스페이스/자격증명 env 주입). 기본 동기(spawnSync),
// opts.detached 면 백그라운드. 예: runPythonCommand(['main.py','inspect-dom','--json']).
function runPythonCommand(args, env = {}, opts = {}) {
  const py = getPythonCommand();
  const base = { cwd: getCoreRoot(), env: { ...ptyEnv(), ...env }, encoding: 'utf8' };
  if (opts.detached) {
    const { spawn } = require('child_process');
    const child = spawn(py, args, { ...base, detached: true, stdio: 'ignore' });
    try { child.unref(); } catch (_) {}
    return child;
  }
  return spawnSync(py, args, { ...base, timeout: opts.timeout || 120000 });
}

// ANTHROPIC_API_KEY 가 설정돼 있으면 경고(이 앱은 구독 기반 claude CLI 만 쓴다 — API 과금 안 함).
function apiKeyWarning() {
  return process.env.ANTHROPIC_API_KEY
    ? 'ANTHROPIC_API_KEY 가 설정돼 있습니다 — 이 앱은 구독형 Claude Code CLI 만 사용하며 API 과금을 쓰지 않습니다(키는 무시 권장).'
    : null;
}

// PTY 환경: PATH(+venv) + CDP 엔드포인트 + 워크스페이스 + 저장된 자격증명(.env 대체).
function ptyEnv() {
  const vb = venvBin();
  const basePath = loginPath();
  return {
    ...process.env,
    // venv 가 있으면 그 bin 을 PATH 앞에 둬서 claude 가 실행하는 `python main.py` 가 venv 의존성을 쓰게.
    PATH: vb ? `${vb}${path.delimiter}${basePath}` : basePath,
    TERM: 'xterm-256color',
    VOICEPRINT_CDP_ENDPOINT: CDP_ENDPOINT,   // python 발행기가 이 화면에 붙음
    VOICEPRINT_WORKSPACE: ws(),              // python paths.py 가 같은 데이터 루트를 쓰게
    ...secrets.loadSecrets(),                // NAVER_ID/PW(선택) · API 키들
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
    cwd: getCoreRoot(),   // `python main.py` 가 코어(repo 또는 Resources/voiceprint-core)에서 돌게
    env: ptyEnv(),
  });
  ptyProc.onData((d) => { if (win) win.webContents.send('pty:data', d); });
  ptyProc.onExit(() => {
    ptyProc = null;
    // 셸이 죽으면 알리지 않으면 터미널이 얼어붙은 듯 보인다(입력이 조용히 버려짐).
    // 렌더러가 claudeStarted 를 리셋하고 안내 메시지를 띄우게 알린다. 자동 재시작은
    // pty:input(아무 키/버튼)이 하도록 둔다 — 원치 않게 셸을 계속 되살리지 않도록.
    if (win) {
      win.webContents.send('pty:exit');
      win.webContents.send('pty:data',
        '\r\n\x1b[33m[세션 종료됨 — 아무 키나 누르거나 버튼을 누르면 새 셸을 엽니다]\x1b[0m\r\n');
    }
  });
}

function restartPty() {
  if (ptyProc) { try { ptyProc.kill(); } catch (_) {} ptyProc = null; }
  if (win) win.webContents.send('pty:data', '\r\n\x1b[36m[세션 재시작 — 새 설정 적용됨]\x1b[0m\r\n');
  startPty();
}

// claude 를 PTY(사용자의 로컬 CLI = 구독 로그인) 안에서 보장한다. 헤드리스/SDK/API 안 씀.
// cmd 가 있으면 PTY 에 입력으로 보낸다(기본 'claude' 로 TUI 띄움).
function runClaudeCommandOrPTY(cmd = 'claude') {
  if (!ptyProc) startPty();
  if (cmd && ptyProc) {
    try { ptyProc.write(cmd.endsWith('\r') ? cmd : cmd + '\r'); } catch (_) {}
  }
  return !!ptyProc;
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

  // ⭐ dirty 에디터(SmartEditor 의 beforeunload) 때문에 네비게이션이 취소되는 것을 막는다.
  //    Electron 기본값: beforeunload 핸들러가 있는 페이지가 이동하려 하면 will-prevent-unload
  //    가 뜨고, 처리 안 하면 이동을 **취소**한다(메인 프로세스에서 동기 결정 → CDP goto 가
  //    net::ERR_ABORTED 로 7ms 만에 죽음). 발행기가 직전 글(임시저장 잔여)이 떠 있는
  //    postwrite 에서 '새 글'로 이동할 때 이게 발목을 잡아 새 글이 직전 글에 이어써졌다.
  //    preventDefault() = beforeunload 무시하고 이탈 허용(임시저장본은 서버에 이미 안전).
  naverView.webContents.on('will-prevent-unload', (event) => {
    event.preventDefault();
  });
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
  try { workspace.ensureDirs(); } catch (_) {}  // 워크스페이스 표준 폴더 보장
  createNaverView();
  startPty();
}

// --- IPC: PTY ---
// 입력이 오면 죽은 PTY 를 자동으로 되살린다(셸 종료 후 터미널이 먹통 되는 것 방지).
ipcMain.on('pty:input', (_e, data) => {
  if (!ptyProc) startPty();
  if (ptyProc) ptyProc.write(data);
});
ipcMain.on('pty:resize', (_e, { cols, rows }) => {
  if (ptyProc && cols > 0 && rows > 0) { try { ptyProc.resize(cols, rows); } catch (_) {} }
});
ipcMain.handle('session:restart', () => { restartPty(); return true; });
// claude(사용자 로컬 CLI = 구독) 보장/시작.
ipcMain.handle('session:claude', () => runClaudeCommandOrPTY('claude'));
// python main.py 직접 실행(코어 루트 + 워크스페이스 env). 동기 실행 결과 반환.
ipcMain.handle('python:run', (_e, { args, env } = {}) => {
  const r = runPythonCommand(Array.isArray(args) ? args : [], env || {});
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
});

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
  return {
    installed: !!bin, bin, version, projectRoot: PROJECT_ROOT,
    coreRoot: getCoreRoot(), packaged: app.isPackaged, cdp: CDP_ENDPOINT,
    workspace: ws(), workspaceChosen: workspace.isChosen(), apiKeyWarning: apiKeyWarning(),
  };
});

// --- IPC: 워크스페이스(작업 폴더) ---
ipcMain.handle('workspace:get', () => ({ root: ws(), chosen: workspace.isChosen(), default: workspace.defaultPath() }));
ipcMain.handle('workspace:choose', async () => {
  const res = await dialog.showOpenDialog(win, {
    title: '작업 폴더(워크스페이스) 선택',
    defaultPath: ws(),
    properties: ['openDirectory', 'createDirectory'],
    buttonLabel: '이 폴더 사용',
  });
  if (res.canceled || !res.filePaths || !res.filePaths.length) return { root: ws(), changed: false };
  const chosen = res.filePaths[0];
  workspace.set(chosen);
  workspace.ensureDirs(chosen);
  restartPty();  // 새 VOICEPRINT_WORKSPACE 를 PTY 환경에 반영
  return { root: chosen, changed: true };
});
ipcMain.handle('workspace:open', () => { shell.openPath(ws()).catch(() => {}); return true; });
ipcMain.handle('logs:open', () => { shell.openPath(path.join(ws(), 'logs')).catch(() => {}); return true; });

// --- IPC: 환경 점검(Claude/Python/Playwright/ffmpeg) ---
function _checkCmd(cmd, args, re) {
  try {
    const out = spawnSync(LOGIN_SHELL, ['-lic', `${cmd} ${args}`], { encoding: 'utf8', timeout: 12000 });
    const text = ((out.stdout || '') + (out.stderr || '')).trim();
    const ok = out.status === 0 && (!re || re.test(text));
    return { ok, detail: text.split('\n')[0] || '' };
  } catch (e) { return { ok: false, detail: String(e.message || e) }; }
}
// Chromium: `playwright install --dry-run` 의 'Install location' 경로가 실제로 있으면 설치됨.
function _checkChromium(py) {
  try {
    const out = spawnSync(LOGIN_SHELL, ['-lic', `${py || 'python'} -m playwright install --dry-run chromium`],
      { encoding: 'utf8', timeout: 15000 });
    const text = (out.stdout || '') + (out.stderr || '');
    for (const line of text.split('\n')) {
      const m = line.match(/Install location:\s*(.+chromium-\d+.*)$/i);
      if (m && fs.existsSync(m[1].trim())) return { ok: true, detail: 'Chromium 설치됨' };
    }
    return { ok: false, detail: 'Chromium 미설치 (python -m playwright install chromium)' };
  } catch (e) { return { ok: false, detail: String(e.message || e) }; }
}
ipcMain.handle('env:check', () => {
  const claudeBin = resolveClaude();
  let claudeVer = '';
  if (claudeBin) { try { claudeVer = (spawnSync(claudeBin, ['--version'], { encoding: 'utf8', timeout: 8000 }).stdout || '').trim(); } catch (_) {} }
  const PY = getPythonCommand();
  const py = _checkCmd(PY, '--version', /Python\s+3\.(1[0-9]|[2-9])/);
  const playwright = _checkCmd(PY, "-c \"import playwright,sys;print('playwright',playwright.__version__)\"", /playwright/);
  const chromium = _checkChromium(PY);
  const ffmpeg = _checkCmd('ffmpeg', '-version', /ffmpeg version/);
  return {
    claude: { ok: !!claudeBin, detail: claudeBin ? (claudeVer || claudeBin) : '미설치 — claude.ai/code 에서 설치 후 로그인' },
    python: py,
    playwright,
    chromium,
    ffmpeg,
    apiKeyWarning: apiKeyWarning(),
    workspace: ws(),
  };
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
  const jobDir = inputDir(safe);
  const dir = path.join(jobDir, 'photos');
  const existed = fs.existsSync(jobDir);
  fs.mkdirSync(dir, { recursive: true });
  return { job: safe, dir, existed };
});

ipcMain.handle('jobs:list', () => {
  const base = path.join(ws(), 'input');
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
  const dest = photosDir(safe);
  fs.mkdirSync(dest, { recursive: true });
  const stats = { count: 0, converted: 0, videos: 0 };
  for (const p of (paths || [])) if (p) ingestInto(p, dest, stats);
  return { dest, ...stats };
});

// --- IPC: 메모(description.txt) 읽기/저장 ---
//   저장 위치는 표준 경로 <workspace>/input/<job>/description.txt 로 통일한다.
//   읽기는 표준 경로가 없으면 job 폴더 전체를 재귀로 뒤져 묻혀 들어온 메모(예: photos/모리몰리,
//   확장자 없음)를 찾아 보여준다 — 사용자가 모달에서 확인 후 저장하면 표준 경로로 정착된다.
const _MEMO_SKIP_EXTS = new Set([
  '.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif', '.gif', '.bmp', '.tiff',
  '.mov', '.mp4', '.m4v', '.avi', '.mkv', '.webm', '.json', '.zip', '.pdf',
]);
function _readTextMemo(file) {
  try {
    const buf = fs.readFileSync(file);
    if (!buf.length || buf.length > 200000 || buf.includes(0)) return '';
    return buf.toString('utf8');
  } catch (_) { return ''; }
}
function _findMemo(jobDir) {
  const desc = [], txtmd = [], extless = [];
  (function walk(d) {
    let entries;
    try { entries = fs.readdirSync(d, { withFileTypes: true }); } catch (_) { return; }
    for (const e of entries) {
      if (e.name.startsWith('.') || e.name.startsWith('_') || e.name === '__MACOSX') continue;
      const full = path.join(d, e.name);
      if (e.isDirectory()) { walk(full); continue; }
      const ext = path.extname(e.name).toLowerCase();
      if (_MEMO_SKIP_EXTS.has(ext)) continue;
      const text = _readTextMemo(full);
      if (!text.trim()) continue;
      if (e.name.toLowerCase() === 'description.txt') desc.push(text);
      else if (ext === '.txt' || ext === '.md') txtmd.push(text);
      else if (ext === '') extless.push(text);
    }
  })(jobDir);
  return [...desc, ...txtmd, ...extless].join('\n\n').trim();
}
ipcMain.handle('memo:get', (_e, job) => {
  const safe = String(job || '').trim();
  if (!safe) return { text: '' };
  const jobDir = inputDir(safe);
  const std = path.join(jobDir, 'description.txt');
  try {
    if (fs.existsSync(std)) return { text: fs.readFileSync(std, 'utf8') };
  } catch (_) {}
  return { text: _findMemo(jobDir) };  // 표준 경로 없으면 묻힌 메모라도 찾아서.
});
ipcMain.handle('memo:save', (_e, { job, text }) => {
  const safe = String(job || '').trim();
  if (!safe) throw new Error('현재 job 없음');
  const jobDir = inputDir(safe);
  fs.mkdirSync(jobDir, { recursive: true });
  fs.writeFileSync(path.join(jobDir, 'description.txt'), String(text || ''), 'utf8');
  return { ok: true };
});

// 현재 job 의 photos/ 안 미디어를 재귀로 나열(UI 칩 목록용). HEIC 는 변환된 jpg 가 있으면 숨김.
const _IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.heic']);
const _VIDEO_EXTS = new Set(['.mov', '.mp4']);
function listMedia(job) {
  const dir = photosDir(job);
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
