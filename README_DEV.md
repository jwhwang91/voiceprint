# README_DEV — Voiceprint 개발자 가이드

이 문서는 **PyCharm에서 작업하는 개발자**를 위한 레퍼런스다. 사용자(블로거)용 안내가 아니라,
코드 구조 / 데이터 경로 / CLI / 셀렉터·자가치유 / 배포 빌드 / 테스트를 정확하게 정리한다.

> Voiceprint는 **API SaaS가 아니다.** 로컬 데스크톱 도구다. 다음을 오케스트레이션한다.
> - (a) 사용자 **본인의 Claude Code CLI 구독** (Claude/Anthropic **API·SDK 아님** → API 과금 없음)
> - (b) 로컬 Python 자동화 (Playwright)
> - (c) 로컬 사용자 워크스페이스 파일
> - (d) 눈에 보이는 브라우저 기반 네이버 상호작용
>
> **역할 분담:** Python은 기계적 작업(수집·브라우저 자동화/발행·이미지/영상·SEO·inspect-dom)을 하고,
> Claude Code(로컬 CLI)는 인지적 작업(페르소나 분석·사진 이해·글쓰기·댓글·배치 기획·셀렉터 자가치유)을 한다.
> **Python은 절대 Claude를 호출하지 않는다.**
> Electron 앱(`app/`)은 사용자 본인의 `claude` CLI를 PTY(node-pty)로 감싼 셸일 뿐이다.
> 반드시 구독 로그인을 쓰고, API 키를 쓰지 않는다.

---

## 1) 개발 모드 — 기본은 레포-로컬 `data/` (예전과 동일)

워크스페이스를 아무것도 지정하지 않으면(개발자/PyCharm/dev 모드), 동작은 **예전과 바이트 단위로 동일**하다.
모든 데이터 루트가 레포 하위로 떨어진다.

| 용도 | dev 모드 경로 |
| --- | --- |
| 입력(사진·메모) | `data/input/<job>/photos/`, `data/input/<job>/description.txt` |
| 초안 | `data/drafts/<job>/` |
| 인증 | `data/auth/` |
| 수집 과거글 | `data/collected/<id>/` |
| 답방 | `data/engage/<job>/` |
| 로그 | `<repo>/logs/` |
| 페르소나 | `<repo>/personas/` |
| SEO DB | `data/blog_growth/blog_growth.db` |

`data/drafts/<job>/`에 들어갈 수 있는 파일:
`post.md`, `layout.json`, `SEO_BRIEF.md`, `SEO_REPORT.md`, `seo_brief.json`, `photo_tags.json`,
`video_plan.json`, `video/`(프레임), `SEO_QUALITY.json`.

`logs/`에 들어가는 것:
`blog_automation.log`, `screenshots/`, `healing-history.jsonl`, `seo_crawler_failures/`.

---

## 2) 워크스페이스 추상화 (`src/blog_automation/paths.py`)

"워크스페이스" = **런타임 데이터 루트**다. `get_workspace_root()`의 우선순위:

1. CLI 전역 플래그 `--workspace <path>`
2. 환경변수 `VOICEPRINT_WORKSPACE`
3. `config/settings.yaml` 의 `paths.workspace` (선택 키 — 기본에는 없음)
4. **폴백: 레포-로컬 `data/`** (= 개발자/PyCharm/dev 모드)

### dev 모드 vs 앱/워크스페이스 모드

- **dev 모드(워크스페이스 미설정):** 위 1절 표 그대로.
- **앱/워크스페이스 모드:** 모든 것이 선택한 워크스페이스 폴더 **하위**로 들어간다.

```
<ws>/input/<job>/photos/
<ws>/input/<job>/description.txt
<ws>/drafts/<job>/
<ws>/collected/<id>/
<ws>/engage/<job>/
<ws>/auth/
<ws>/logs/
<ws>/personas/
<ws>/blog_growth/blog_growth.db
<ws>/config/selectors.user.yaml
<ws>/config/workflows.user.yaml
```

> **중요:** 앱 레벨 설정은 워크스페이스에 들어가지 않는다. Electron 앱은 선택한 워크스페이스 경로를
> OS 앱-데이터 디렉터리(Electron `userData/app-config.json`)에 저장하고, 암호화된 자격증명은
> `userData/secrets.enc.json`(OS 키체인 / `safeStorage`)에 저장한다. 레포의 `.env`는 앱이 사용하지 않는다.

### `paths.py` 헬퍼

`paths.py`가 모든 경로의 단일 진실원이다. 주요 `get_*` 헬퍼:

```python
get_workspace_root()        # 위 우선순위로 런타임 데이터 루트 결정
get_input_root()            # <ws>/input            ( = cfg.input_dir )
get_input_dir(job)          # <ws>/input/<job>
get_photos_dir(job)         # <ws>/input/<job>/photos
get_description_path(job)   # <ws>/input/<job>/description.txt
get_drafts_root()           # <ws>/drafts           ( = cfg.drafts_dir )
get_drafts_dir(job)         # <ws>/drafts/<job>
get_collected_root()        # <ws>/collected        ( = cfg.collected_dir )
get_auth_dir()              # <ws>/auth
get_logs_dir()              # <ws>/logs   (dev: <repo>/logs)
get_persona_dir()           # <ws>/personas (dev: <repo>/personas)
get_seo_db_path()           # <ws>/blog_growth/blog_growth.db
get_user_config_dir()       # <ws>/config
get_user_selectors_path()   # <ws>/config/selectors.user.yaml
get_healing_history_path()  # <ws>/logs/healing-history.jsonl
get_default_selectors_path()# <repo>/config/selectors.yaml  (번들 기본값)
```

> 참고: `engage/<job>/` 는 전용 헬퍼 없이 `collected_dir.parent / "engage" / job` 로 파생된다
> (즉 `<ws>/engage/<job>/`). 워크스페이스 추상화를 자동으로 따라간다.

### Config / seo/config.py / logging_setup.py 위임

세 모듈 모두 자체적으로 경로를 계산하지 않고 `paths.py`에 **위임**한다.

- `Config` — 입력/초안/인증/수집/페르소나 경로를 `paths.get_*()`로 받는다.
- `seo/config.py` — SEO DB 경로를 `paths.get_seo_db_path()`로 받는다.
- `logging_setup.py` — 로그 파일/스크린샷/치유 이력 경로를 `paths.get_logs_dir()` 기준으로 잡는다.

따라서 `--workspace`/`VOICEPRINT_WORKSPACE`/`settings.yaml`을 바꾸면 세 모듈이 자동으로 따라간다.

자세한 내용: `docs/WORKSPACE.md`.

---

## 3) CLI 레퍼런스 (`python main.py <cmd>`)

dev 모드에서는 **사용자(개발자)가** 직접 실행하고, 앱 안에서는 Claude의 셸이 실행한다.

### 전역 플래그

모든 서브커맨드 **앞**에 붙일 수 있다.

```bash
python main.py --workspace <path> <cmd> ...
```

> 앱은 PTY 환경에 `VOICEPRINT_WORKSPACE`를 주입한다. 따라서 앱 안에서 Claude가 돌리는 명령은
> `--workspace` 없이도 선택된 워크스페이스로 자동 해석된다.

### 수집 · 입력

```bash
python main.py collect --id <blog_id> [--max N]
python main.py fetch --url <url> --job <job>
python main.py fetch-doc --url <url>
```

### 영상 → GIF

```bash
python main.py video-scan --job <job>      # 프레임 추출(Python). Claude는 프레임만 보고 구간 선정
python main.py video-render --job <job>    # ffmpeg 렌더링 → GIF
```

### 발행 · 답방

```bash
python main.py publish --job <job> [--dry-run] [--yes|-y]
python main.py engage scan --post <logNo|url> --job <job>
python main.py engage run --job <job> [--go]
```

> **설계상** `publish`는 **임시저장(temp-save)까지만** 한다. 최종 **발행**은 사용자가 네이버에서
> 직접 누른다. `--yes`로 돌려도 자동 발행되지 않는다 — "글이 자동 게시됐다"고 말하면 안 된다.

### SEO

```bash
python main.py seo-init-db
python main.py seo-import-posts --id <blog_id>
python main.py seo-research-keywords --job <job>
python main.py seo-generate-brief --job <job>
python main.py seo-quality-check --job <job>
python main.py collect-outcomes [--days N] [--blog-id X]
```

### 앱 실행

```bash
python main.py app     # 데스크톱 앱 실행/포커스
python main.py         # 인자 없이 실행해도 앱을 실행/포커스
```

### inspect-dom (DOM 점검 / 셀렉터 진단)

```bash
python main.py inspect-dom [--selector <css>] [--text <t>] \
    [--list buttons|inputs|editable|links|interactive] \
    [--html <css>] [--section <name>] [--editor] \
    [--goto <url>] [--blog-id <id>] [--json]
```

### 셀렉터 패치 (자가치유)

```bash
python main.py apply-selector-patch --patch <file.json> [--verify|--no-verify] [--blog-id <id>]
python main.py validate-selector-patch --patch <file.json> [--verify] [--blog-id <id>]
```

---

## 4) 셀렉터 아키텍처

### 두 계층

- **번들 기본값:** `config/selectors.yaml` — **안정(STABLE)**. 자가치유가 **절대 수정하지 않는다.**
- **사용자 런타임 오버라이드:** `<ws>/config/selectors.user.yaml` — 기본값 **위에 deep-merge**.
  오버라이드가 없거나 깨졌으면 **경고 후 기본값으로 폴백** — 발행을 절대 크래시시키지 않는다.

### 값 형식 — 구식 문자열 / 신식 dict 둘 다 지원

```yaml
# 구식: 문자열
write.publish_open_button: "button:has-text('발행')"

# 신식: dict
write.publish_open_button:
  selector: "[class*='publish_btn']"
  updated_at: "2026-06-30T..."
  reason: "..."
  confidence: 0.91
  source: "self-heal"
```

`load_selectors()`가 dict를 **문자열로 평탄화(flatten)** 하므로, 기존 소비자 코드는 전부 그대로 동작한다.

### 헬퍼

```python
get_selector(sel, "write.publish_open_button")     # 평탄화된 셀렉터 문자열 조회
save_selector_override(...)                          # <ws>/config/selectors.user.yaml 에만 기록
```

`save_selector_override()`는 **오직** `<ws>/config/selectors.user.yaml`에만 쓴다.
`config/selectors.yaml`이나 소스 코드를 절대 건드리지 않는다.

자세한 내용: `docs/SELF_HEALING.md`.

---

## 5) inspect-dom JSON 모드 + 셀렉터 패치 + 검증/적용 + 치유 이력

### inspect-dom `--json`

`--json`은 구조화된 JSON을 출력한다. 필드:
`status`(OK/MISS/AMBIGUOUS/ERROR), `matched`, `visible`, `suggested_selectors`, `elements`,
`url`, `timestamp` 등.

### 셀렉터 패치 JSON 스키마

```json
{
  "type": "selector_patch",
  "target": "write.publish_open_button",
  "old_selector": "...",
  "new_selector": "[class*='publish_btn']",
  "evidence": { "matched_count": 1, "visible": true, "text": "발행" },
  "confidence": 0.91,
  "reason": "..."
}
```

### validate / apply

- `validate-selector-patch --patch <file.json> [--verify] [--blog-id <id>]`
  스키마 검증(+ `--verify` 시 라이브 DOM 매칭 확인). 파일은 쓰지 않는다.
- `apply-selector-patch --patch <file.json> [--verify|--no-verify] [--blog-id <id>]`
  스키마 검증 → 빈/과도하게 넓은 셀렉터(`div`, `button`, `*` 같은 맨몸 태그) 거부 →
  (앱 모드 / `--verify` 시) `new_selector`가 라이브 DOM과 매칭되는지 확인 →
  **오직** `<ws>/config/selectors.user.yaml`에 기록 → `<ws>/logs/healing-history.jsonl`에 로깅.
  `config/selectors.yaml`이나 소스 코드는 **절대** 수정하지 않는다.

### 자가치유 루프

- **발행 시도 총 3회로 상한(CAP).** Claude가 `prompts/self_heal_selector.md`(및
  `/blog-run` 스킬 `.claude/commands/blog-run.md`)를 따라 구동한다.
- **하드-페일(자가치유 금지, 멈추고 사용자에게 보이는 브라우저에서 직접 처리 요청):**
  CAPTCHA, 로그인, 보안/안티봇 챌린지. **CAPTCHA/로그인 보안은 절대 우회하지 않는다.**

자세한 내용: `docs/SELF_HEALING.md`, 회귀 점검: `docs/REGRESSION_CHECKLIST.md`.

---

## 6) 배포 빌드 (App Store 없이 — 선택 사용자 공유)

배포는 **2단계**다. **STAGE 1(권장·기본)** 은 semi-packaged ZIP, **STAGE 2(선택)** 는 electron-builder `.dmg/.zip`.

### STAGE 1 — semi-packaged ZIP

| 스크립트 | 역할 |
| --- | --- |
| `scripts/bootstrap-mac.sh` | 멱등 설치/점검(CLI): Python venv, pip, Playwright chromium, ffmpeg 안내, npm 앱 의존성, claude CLI 로그인 안내 |
| `scripts/bootstrap-windows.ps1` | Windows best-effort |
| `scripts/check_environment.py` | 진단 전용(아무것도 설치 안 함). 앱의 "🩺 환경 점검"과 동일 체크(Python·claude·Node/npm·ffmpeg·playwright·워크스페이스) |
| `scripts/create_distribution_zip.sh` | 깨끗한 `dist-local/VoiceprintStudio/` 스테이징 후 `dist-local/VoiceprintStudio-mac.zip` 생성 |
| `START_MAC.command` | 더블클릭: claude/python3 확인 → `.venv` 생성·의존성·Playwright → `cd app && npm start` |

```bash
bash scripts/create_distribution_zip.sh
#  → dist-local/VoiceprintStudio/            (배포 폴더)
#  → dist-local/VoiceprintStudio-mac.zip     (공유용 ZIP)
```

ZIP 에는 `app/ src/ prompts/ config/ scripts/ main.py requirements.txt README_USER.md README_DEV.md
START_MAC.command .gitignore`(+ `docs/`·`.env.example`)만 들어간다. **제외**: `node_modules`, `.venv`,
`data/`, `logs/`, `.env`, `secrets`, `selectors.user.yaml`, `healing-history.jsonl`, 빌드 산출물.

### STAGE 2 — electron-builder `.dmg`/`.zip` (선택)

```bash
cd app
npm install
npm run rebuild
npm run dist:mac      #  electron-builder --mac dmg zip  →  app/dist/
```

- `app/package.json` 의 `build`: `appId=com.voiceprint.studio`, `productName="Voiceprint Studio"`,
  출력 `app/dist/`, `asar:false`(renderer 가 `../../node_modules` 의 xterm 을 file:// 로 로드).
- 파이썬 코어(`../src ../prompts ../config ../main.py ../requirements.txt ../scripts ../README_*.md`)는
  `extraResources` 로 `Resources/voiceprint-core/` 에 들어간다 → 패키징 모드에서
  `getCoreRoot()=process.resourcesPath/voiceprint-core`. **`data/`·워크스페이스·`.env`·auth/logs/drafts/photos 는 미포함**.
- ⚠️ 지금은 **풀 번들링 아님(semi-packaged)** — 사용자 Python3 + 첫 실행 `.venv` 에 의존한다.
  TODO(향후): PyInstaller `voiceprint-core` 단일 바이너리, Playwright Chromium 번들, ffmpeg 번들,
  macOS 코드서명/공증(notarize). 그 전까지 패키징 `.app` 모드는 실험적이며 권장 경로는 ZIP 이다.

### Electron 코어 경로 해석(`app/src/main.js`)

- `getCoreRoot()` — 패키징이면 `process.resourcesPath/voiceprint-core`, 개발/ZIP 이면 repo 루트.
- `getPythonCommand()` — `.venv` 의 python 우선, 없으면 시스템 `python3`.
- `runPythonCommand(args, env)` — 코어 루트에서 python 실행(+`VOICEPRINT_WORKSPACE`/자격증명 env 주입).
- `runClaudeCommandOrPTY()` — 사용자의 로컬 `claude` CLI 를 PTY 로 보장(구독 로그인, API/SDK 안 씀).
- PTY 와 위 헬퍼 모두 **`VOICEPRINT_WORKSPACE`** 를 주입하므로, 앱 안에서 claude 가 돌리는
  `python main.py …` 는 선택된 워크스페이스로 자동 해석된다(`--workspace` 불필요).

- 소스 어디에도 개발자 경로 `/Users/seungchanboi`를 하드코딩하지 않는다. 모든 루트는 `Path(__file__)`/`getCoreRoot()`에서 파생.
- `.gitignore` 제외: `data/`, `logs/`, `.env`, `**/selectors.user.yaml`, `**/healing-history.jsonl`,
  `**/secrets.enc.json`, `**/app-config.json`, `app/node_modules/`, `app/dist/`, `/dist/`, `/dist-local/`.

### Electron 앱 버튼(우측 레일, `app/src/renderer`)

- 상단: ▶ Claude 시작 / `/status`(과금 확인) / 🩺 환경 점검
- 작업 폴더(워크스페이스): 📂 작업 폴더 바꾸기 / 폴더 열기 / 로그 열기
- 새 글 작성: + 폴더 만들기 / 기존 글 불러오기 / 드롭존(사진·영상) / 📝 메모 /
  🔑 SEO 브리프 생성 / 🎬 영상→움짤(GIF) / ✍️ 이 글 쓰고 발행 / 👀 초안 미리보기 / 🩹 발행 실패 시 자가치유
- 발행 화면: 🌐 네이버 보기 / 네이버 로그인(1회)
- 기타: 페르소나 업데이트 / 답방 댓글 / `/blog` 직접 메뉴
- 제어: 중단(Ctrl-C) / 화면 지우기 / 설정(⚙, 자격증명 모달)

내장 터미널(xterm)은 항상 보인다 — 파워 유저는 명령을 직접 입력할 수 있다(터미널 탈출구).

---

## 7) 테스트 실행

```bash
python -m pytest -q
```

현재 **77개 테스트**가 통과한다. 변경 후 반드시 돌릴 것.
회귀 점검 항목은 `docs/REGRESSION_CHECKLIST.md` 참고.

---

## 참고 문서 / 프롬프트 · 스킬

- `docs/WORKSPACE.md` — 워크스페이스 해석/경로 매핑
- `docs/SELF_HEALING.md` — 셀렉터 자가치유 전체 흐름
- `docs/REGRESSION_CHECKLIST.md` — 회귀 점검 체크리스트

프롬프트:
`prompts/analyze_persona.md`(페르소나 분석), `prompts/write_post.md`(글쓰기·사진 태깅·layout.json·place 블록·영상 GIF·SEO 브리프 소비),
`prompts/write_comments.md`(답방 댓글), `prompts/self_heal_selector.md`(셀렉터 자가치유).

스킬:
`/blog`(`.claude/commands/blog.md`, 앱 내 메뉴), `/blog-run`(`.claude/commands/blog-run.md`, 자가치유 포함 발행 러너).
