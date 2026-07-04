// renderer (main world). node 권한 없음 — 모든 권한 작업은 window.api(preload) 경유.
/* global Terminal, FitAddon */

const term = new Terminal({
  fontFamily: 'Menlo, Monaco, "Courier New", monospace',
  fontSize: 13,
  cursorBlink: true,
  convertEol: false,
  allowProposedApi: true,
  theme: { background: '#0b0e14', foreground: '#cdd6f4', cursor: '#7aa2f7', selectionBackground: '#283457' },
});
const fit = new FitAddon.FitAddon();
term.loadAddon(fit);
term.open(document.getElementById('terminal'));
fit.fit();

window.api.pty.onData((d) => term.write(d));
term.onData((d) => window.api.pty.input(d));
// 셸이 죽으면 claude 도 꺼진 것 — 다음 버튼 클릭이 먼저 셸/claude 를 되살리게 한다.
window.api.pty.onExit(() => { claudeStarted = false; });

function syncSize() {
  try { fit.fit(); } catch (_) {}
  window.api.pty.resize(term.cols, term.rows);
}
new ResizeObserver(syncSize).observe(document.getElementById('terminal'));
window.addEventListener('resize', syncSize);
setTimeout(syncSize, 120);

function send(text) { window.api.pty.input(text); term.focus(); }

// 앱 메시지는 터미널이 아니라 하단 상태바로(터미널엔 claude/셸 출력만 남게).
const _statusbar = document.getElementById('statusbar');
const _STATUS_CLS = { 32: 'ok', 33: 'warn', 31: 'err', 36: 'info' };
function notice(msg, color = 32) {
  if (!_statusbar) return;
  _statusbar.textContent = msg;
  _statusbar.className = 'statusbar ' + (_STATUS_CLS[color] || 'muted');
}

// claude(TUI)가 켜졌는지 추적. claude 가 필요한 버튼은 안 켜져 있으면 먼저 켜고 한 번 더 누르게 안내.
let claudeStarted = false;
function ensureClaude() {
  if (claudeStarted) return true;
  // session.claude() 는 죽은 PTY 를 먼저 되살린 뒤 claude 를 띄운다(raw send 는 죽은 셸에 무시됨).
  window.api.session.claude();
  claudeStarted = true;
  notice('[Claude] 먼저 Claude 를 켰어요 — 화면이 준비되면 버튼을 한 번 더 눌러주세요', 33);
  return false;
}

// --- 세션 ---
// PTY 가 죽어 있어도 되살리도록 session.claude() 경로를 쓴다(raw send 는 먹통 셸엔 무반응).
document.getElementById('btn-claude').onclick = () => { window.api.session.claude(); claudeStarted = true; term.focus(); };
document.getElementById('btn-status').onclick = () => { if (ensureClaude()) send('/status\r'); };

// --- 기타 작업 (자기완결 지시문 주입 — 메뉴 번호 의존 X) ---
document.getElementById('btn-persona').onclick = () => {
  if (ensureClaude()) send('과거 수집 글을 분석해서 personas/ 를 업데이트해줘 (/blog 의 "1) 페르소나 업데이트" 절차대로).\r');
};
document.getElementById('btn-comments').onclick = () => {
  if (ensureClaude()) send('답방 댓글을 생성하고 발행해줘 (/blog 의 "3) 답방 댓글 작성 & 발행" 절차대로). 어떤 job 인지 물어보면 알려줄게.\r');
};
document.getElementById('btn-blog-menu').onclick = () => { if (ensureClaude()) send('/blog\r'); };

// --- 제어 ---
document.getElementById('btn-int').onclick = () => send('\x03');
document.getElementById('btn-clear').onclick = () => { term.clear(); term.focus(); };

// --- 네이버 임베드 뷰 토글 ---
let naverVisible = false;
const btnView = document.getElementById('btn-view');
function reflectView(v) {
  naverVisible = v;
  btnView.textContent = v ? '⌨ 터미널 보기' : '🌐 네이버 보기';
  btnView.classList.toggle('active', v);
}
btnView.onclick = () => window.api.naver.show(!naverVisible);
document.getElementById('btn-naver-login').onclick = () => window.api.naver.login();
window.api.naver.onVisibility(reflectView);

// --- 온보딩 상태칩 ---
window.api.onboarding.status().then((s) => {
  const el = document.getElementById('status-chip');
  if (s.installed) { el.textContent = 'claude ' + (s.version || 'OK'); el.classList.add('ok'); }
  else { el.textContent = 'claude 미설치'; el.classList.add('bad'); }
  if (s.apiKeyWarning) notice('⚠ ' + s.apiKeyWarning, 33);
});

// --- 워크스페이스(작업 폴더) ---
let workspaceRoot = '';
const wsPathEl = document.getElementById('ws-path');
async function refreshWorkspace() {
  try {
    const w = await window.api.workspace.get();
    workspaceRoot = w.root || '';
    if (wsPathEl) {
      wsPathEl.textContent = (w.chosen ? '📁 ' : '📁 (기본) ') + workspaceRoot;
      wsPathEl.title = workspaceRoot;
    }
  } catch (_) {}
}
refreshWorkspace();

document.getElementById('btn-ws-change').onclick = async () => {
  try {
    const r = await window.api.workspace.choose();
    if (r.changed) {
      claudeStarted = false; // PTY 재시작됨 → claude 꺼짐
      await refreshWorkspace();
      await refreshJobs();
      notice(`작업 폴더를 바꿨어요: ${r.root} (세션 재시작됨)`, 32);
    }
  } catch (e) { notice('작업 폴더 변경 실패: ' + e.message, 31); }
};
document.getElementById('btn-ws-open').onclick = () => window.api.workspace.open();
document.getElementById('btn-logs-open').onclick = () => window.api.logs.open();

// --- 환경 점검 ---
document.getElementById('btn-envcheck').onclick = async () => {
  notice('환경 점검 중…', 36);
  try {
    const r = await window.api.env.check();
    const mark = (o) => (o && o.ok ? '✓' : '✗');
    const summary = `Claude ${mark(r.claude)} · Python ${mark(r.python)} · Playwright ${mark(r.playwright)} · Chromium ${mark(r.chromium)} · ffmpeg ${mark(r.ffmpeg)}`;
    const allOk = [r.claude, r.python, r.playwright, r.chromium, r.ffmpeg].every((o) => o && o.ok);
    notice(summary + (r.apiKeyWarning ? '  ⚠ API 키 감지' : ''), allOk ? 32 : 33);
  } catch (e) { notice('환경 점검 실패: ' + e.message, 31); }
};

// --- 새 글 작성: ①폴더 → ②드롭 → ③쓰기·발행 (한 흐름) ---
let currentJob = null;
const jobLabel = document.getElementById('job-label');
const dz = document.getElementById('dropzone');

function setJob(name) {
  currentJob = name; jobLabel.textContent = name; dz.classList.add('armed');
  // 새 작업으로 전환하면 이전 발행/에디터가 떠 있던 네이버 뷰를 홈으로 초기화(다음 발행이 깨끗하게 시작).
  try { window.api.naver.home(); } catch (_) {}
}

// 드롭한 미디어를 칩으로 표시
const _filelist = document.getElementById('filelist');
const _fileCount = document.getElementById('file-count');
const _KIND_ICON = { image: '🖼️', video: '🎬', gif: '✨', other: '📄' };
function renderChips(files) {
  _filelist.innerHTML = '';
  const vids = files.filter((f) => f.kind === 'video').length;
  _fileCount.textContent = files.length ? `· ${files.length}개${vids ? ` (영상 ${vids})` : ''}` : '';
  for (const f of files) {
    const chip = document.createElement('div');
    chip.className = 'chip-file' + (f.kind === 'video' ? ' video' : f.kind === 'gif' ? ' gif' : '');
    const ic = document.createElement('span'); ic.textContent = _KIND_ICON[f.kind] || '📄';
    const nm = document.createElement('span'); nm.className = 'nm'; nm.textContent = f.name;
    chip.append(ic, nm);
    _filelist.appendChild(chip);
  }
}
async function refreshFiles() {
  if (!currentJob) { renderChips([]); return; }
  try { renderChips(await window.api.files.list(currentJob)); } catch (_) {}
}

// 기존 글 목록(data/input/*) → 드롭다운
const jobSelect = document.getElementById('job-select');
async function refreshJobs(selected) {
  let jobs = [];
  try { jobs = await window.api.listJobs(); } catch (_) {}
  jobSelect.innerHTML = '';
  const def = document.createElement('option');
  def.value = ''; def.textContent = '기존 글 불러오기…';
  jobSelect.appendChild(def);
  for (const j of jobs) {
    const o = document.createElement('option');
    o.value = j; o.textContent = j;
    if (j === selected) o.selected = true;
    jobSelect.appendChild(o);
  }
}
jobSelect.onchange = async () => {
  const j = jobSelect.value;
  if (!j) return;
  setJob(j);
  document.getElementById('job-input').value = j;
  await refreshFiles();
  notice(`기존 글 "${j}" 불러옴`, 36);
};

document.getElementById('btn-newjob').onclick = async () => {
  const input = document.getElementById('job-input');
  const name = input.value.trim();
  if (!name) { notice('폴더 이름을 입력하거나, 아래에서 기존 글을 고르세요', 33); return; }
  try {
    const res = await window.api.newJob(name);
    setJob(name);
    await refreshFiles();
    await refreshJobs(name);
    notice(res.existed
      ? `기존 폴더 "${name}" 을 현재 글로 불러왔어요`
      : `"${name}" 폴더 생성 완료 — 사진·영상을 드롭하세요`, res.existed ? 36 : 32);
  } catch (e) { notice(`새 글 폴더 실패: ${e.message}`, 31); }
};
refreshJobs();

['dragenter', 'dragover'].forEach((ev) =>
  dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add('over'); }));
['dragleave', 'dragend'].forEach((ev) =>
  dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove('over'); }));

dz.addEventListener('drop', async (e) => {
  e.preventDefault();
  dz.classList.remove('over');
  if (!currentJob) { notice('먼저 "+ 폴더 만들기"로 폴더를 만드세요', 33); return; }
  const paths = [...e.dataTransfer.files].map((f) => window.api.files.pathForFile(f)).filter(Boolean);
  if (!paths.length) { notice('드롭 경로를 못 읽었습니다', 31); return; }
  dz.classList.add('busy');
  try {
    const r = await window.api.files.ingest(currentJob, paths);
    await refreshFiles();
    let msg = `${r.count}개 추가됨`;
    if (r.converted) msg += ` · HEIC→JPG ${r.converted}`;
    if (r.videos) msg += ` · 영상 ${r.videos}개`;
    notice(msg, 32);
  } catch (err) { notice(`드롭 실패: ${err.message}`, 31); }
  finally { dz.classList.remove('busy'); }
});

// 워크스페이스 기준 job 경로(claude 의 파일 읽기는 절대경로가 필요). 워크스페이스 미확인 시 상대 폴백.
function jobPhotos(job) { return (workspaceRoot ? `${workspaceRoot}/input/${job}/photos/` : `input/${job}/photos/`); }
function jobDrafts(job) { return (workspaceRoot ? `${workspaceRoot}/drafts/${job}/` : `drafts/${job}/`); }
function needJob(tag) {
  if (!currentJob) { notice(`[${tag}] 먼저 위에서 "+ 폴더 만들기" 하고 사진을 드롭하세요`, 33); return false; }
  return true;
}

// ③ 이 글 쓰고 발행 — 현재 job 을 claude 에 자동 전달(다시 안 물어보게).
//    영상(MOV/MP4)이 섞여 있으면 본문 쓰기 전에 video-scan→video-render(움짤)까지 한 흐름으로 체이닝.
//    (🎬 영상 버튼은 GIF 만 따로 돌리고 싶을 때를 위한 수동 단계로 남겨둠.)
document.getElementById('btn-write').onclick = () => {
  if (!needJob('글쓰기')) return;
  if (!ensureClaude()) return;
  const job = currentJob;
  // 이전 발행/에디터 화면이 남아있으면 다음 작업을 방해 → 깨끗한 네이버 홈으로 초기화하고 시작.
  try { window.api.naver.home(); } catch (_) {}
  const instr =
    `job "${job}" 로 블로그 글을 써서 발행해줘. 사진·영상은 ${jobPhotos(job)} 에 있어. ` +
    `⭐ 먼저 ${jobDrafts(job)}post.md 와 layout.json 이 이미 있는지 확인하고, 있으면 ` +
    `사진 재분석 없이 "이대로 발행할까요, 새로 쓸까요?" 를 물어봐. ` +
    `없거나 새로 쓰기를 고르면 /blog 의 "2) 포스트 작성 & 발행" 절차대로 진행하되, ` +
    `⭐⭐ 본문 작성 전에 먼저 ${jobPhotos(job)} 에 아직 GIF 로 안 바꾼 영상(MOV/MP4 인데 photos/_gifs/ 에 대응 .gif 가 없음)이 있는지 확인하고, ` +
    `있으면 영상→움짤부터 처리해: \`python main.py video-scan --job "${job}"\` 실행 → 추출된 프레임만 보고(원본 영상 통째로 열지 말 것) 쓸 구간을 골라 video_plan.json 작성 → ` +
    `\`python main.py video-render --job "${job}"\` 실행. 만든 GIF 는 본문에서 동작에 맞는 위치에 단독 이미지 블록으로 배치해(representative·콜라주 금지). ` +
    `그다음 SEO 브리프 자동 → 사진 태깅 → 본문·배치 작성 → 임시저장/발행, 발행 실패 시 inspect-dom 자가치유.`;
  send(instr + '\r');
  notice(`[글쓰기] "${job}" 작성·발행을 Claude 에 요청했습니다 (영상 있으면 움짤 변환 포함)`, 36);
};

// SEO 브리프 생성 — python 명령은 claude 가 실행(셸 env 에 VOICEPRINT_WORKSPACE 주입됨).
document.getElementById('btn-seo').onclick = () => {
  if (!needJob('SEO')) return;
  if (!ensureClaude()) return;
  send(`SEO 브리프를 만들어줘: \`python main.py seo-generate-brief --job "${currentJob}"\` 를 실행하고 ${jobDrafts(currentJob)}SEO_BRIEF.md 를 요약해서 보여줘.\r`);
  notice(`[SEO] "${currentJob}" 브리프 생성을 요청했어요`, 36);
};

// 영상 → 움짤(GIF): scan → (Claude 가 video_plan.json 작성) → render
document.getElementById('btn-video').onclick = () => {
  if (!needJob('영상')) return;
  if (!ensureClaude()) return;
  send(`${jobPhotos(currentJob)} 의 영상을 움짤(GIF)로 만들어줘. /blog 의 영상 절차대로: ` +
       `\`python main.py video-scan --job "${currentJob}"\` 실행 → 프레임만 보고 쓸 구간을 골라 video_plan.json 작성 → ` +
       `\`python main.py video-render --job "${currentJob}"\` 실행. (원본 영상을 통째로 열지 말 것)\r`);
  notice(`[영상] "${currentJob}" 움짤 변환을 요청했어요`, 36);
};

// 초안 미리보기 — 드래프트 파일을 claude 가 읽어 요약
document.getElementById('btn-preview').onclick = () => {
  if (!needJob('미리보기')) return;
  if (!ensureClaude()) return;
  send(`${jobDrafts(currentJob)} 의 post.md 와 layout.json 을 읽고, 제목·문단 수·사진 배치(블록 순서)를 간단히 요약해서 보여줘. 발행은 하지 마.\r`);
  notice(`[미리보기] "${currentJob}" 초안 요약을 요청했어요`, 36);
};

// 발행 실패 시 자가치유 — self-heal 지시서 흐름
document.getElementById('btn-heal').onclick = () => {
  if (!needJob('자가치유')) return;
  if (!ensureClaude()) return;
  send(`방금 "${currentJob}" 발행이 셀렉터/DOM 문제로 실패했어. prompts/self_heal_selector.md 절차대로 ` +
       `inspect-dom --json 으로 진단 → 패치 JSON 작성 → apply-selector-patch 로 사용자 오버라이드에 적용 → 재확인 → 재발행(최대 3회). ` +
       `로그인/캡차/보안 문제면 고치지 말고 네이버 화면에서 직접 처리하라고 알려줘.\r`);
  notice(`[자가치유] "${currentJob}" 셀렉터 자가치유를 요청했어요`, 36);
};

// --- 설정 모달 ---
const overlay = document.getElementById('settings-overlay');
const settingsMsg = document.getElementById('settings-msg');

async function openSettings() {
  const { presence, encrypted } = await window.api.settings.keys();
  document.getElementById('enc-note').textContent = encrypted
    ? 'OS 키체인으로 암호화 저장 — .env 파일을 쓰지 않습니다.'
    : '⚠ 이 환경은 키체인 암호화 불가 — 값은 userData 에 평문 저장됩니다(.env 아님).';
  overlay.querySelectorAll('input[data-key]').forEach((inp) => {
    const k = inp.dataset.key;
    inp.value = '';
    inp.placeholder = presence[k] ? '●●●●●● (저장됨 — 바꿀 때만 입력)' : '미설정';
  });
  settingsMsg.textContent = '';
  overlay.classList.remove('hidden');
}
function closeSettings() { overlay.classList.add('hidden'); }

document.getElementById('btn-settings').onclick = openSettings;
document.getElementById('settings-close').onclick = closeSettings;
overlay.addEventListener('click', (e) => { if (e.target === overlay) closeSettings(); });

document.getElementById('settings-save').onclick = async () => {
  const values = {};
  overlay.querySelectorAll('input[data-key]').forEach((inp) => {
    const v = inp.value.trim();
    if (v) values[inp.dataset.key] = v;
  });
  try {
    await window.api.settings.save(values);
    settingsMsg.textContent = '저장됨. 세션 재시작 중…';
    await window.api.session.restart();
    claudeStarted = false; // 셸 재시작 → claude 꺼짐
    closeSettings();
    notice('[설정] 자격증명 저장 + 세션 재시작 완료', 36);
  } catch (e) {
    settingsMsg.textContent = '실패: ' + e.message;
  }
};

// --- 메모 모달 ---
const memoOverlay = document.getElementById('memo-overlay');
const memoText = document.getElementById('memo-text');
const memoMsg = document.getElementById('memo-msg');

async function openMemo() {
  if (!currentJob) { notice('먼저 "+ 폴더 만들기"로 폴더를 만드세요', 33); return; }
  document.getElementById('memo-job').textContent = currentJob;
  memoMsg.textContent = '불러오는 중…';
  memoText.value = '';
  try {
    const { text } = await window.api.memo.get(currentJob);
    memoText.value = text || '';
    memoMsg.textContent = text ? '기존 메모를 불러왔어요(편집 후 저장).' : '';
  } catch (_) { memoMsg.textContent = ''; }
  memoOverlay.classList.remove('hidden');
  memoText.focus();
}
function closeMemo() { memoOverlay.classList.add('hidden'); }

document.getElementById('btn-memo').onclick = openMemo;
document.getElementById('memo-close').onclick = closeMemo;
memoOverlay.addEventListener('click', (e) => { if (e.target === memoOverlay) closeMemo(); });

document.getElementById('memo-save').onclick = async () => {
  if (!currentJob) { closeMemo(); return; }
  try {
    await window.api.memo.save(currentJob, memoText.value);
    closeMemo();
    notice(`[메모] "${currentJob}" 메모 저장 완료`, 32);
  } catch (e) {
    memoMsg.textContent = '저장 실패: ' + e.message;
  }
};

term.focus();
