# 회귀 점검 체크리스트 (Regression Checklist)

이 문서는 **voiceprint** 프로젝트에서 새 기능(워크스페이스 추상화, 셀렉터 셀프힐링, Electron 앱,
배포 스크립트)을 추가한 뒤에도 **기존 동작이 깨지지 않았는지(회귀 없음)**, 그리고 **새 기능이 의도대로
동작하는지**를 손으로 빠르게 확인하기 위한 실전 체크리스트입니다.

> 핵심 전제(잊지 말 것)
> - 이건 API SaaS가 아니라 **로컬 데스크톱 도구**다. 사용자의 **본인 Claude Code CLI 구독**(API/SDK 아님,
>   API 과금 없음) + 로컬 Python 자동화(Playwright) + 로컬 워크스페이스 파일 + **눈에 보이는 브라우저**로
>   네이버를 다룬다.
> - Python은 기계적 작업, Claude Code(로컬 CLI)는 인지적 작업. **Python은 절대 Claude를 호출하지 않는다.**
> - `publish`는 설계상 **임시저장까지만** 한다. 최종 발행은 사용자가 네이버에서 수동으로 누른다.
>   자동 발행됐다고 주장하지 말 것.

각 항목은 `- [ ]` 체크박스 + **정확한 명령/동작**으로 적혀 있습니다. 통과하면 체크하세요.

---

## (A) DEV 모드 — `--workspace` 없이 레포-로컬 `data/`로 그대로 동작해야 함

> DEV 모드(워크스페이스 미설정)는 **과거 동작과 바이트 단위로 동일**해야 한다.
> 모든 산출물은 **예전과 같은 `data/` 경로**에 떨어진다:
> `data/input`, `data/drafts`, `data/auth`, `data/collected`, `<repo>/logs`, `<repo>/personas`,
> `data/blog_growth/blog_growth.db`.

### A-1. 페르소나 (수집 → Claude 페르소나 분석)

- [ ] 과거 글 수집이 동작하고 `data/collected/<id>/*.json`에 떨어진다.

```bash
python main.py collect --id <blog_id> --max 30
```

- [ ] Claude가 `prompts/analyze_persona.md`를 따라 `data/collected/<id>/*.json`을 읽고
      글 종류별 `personas/<글종류>.md`를 `<repo>/personas/` 아래에 생성한다.
- [ ] 생성된 페르소나 .md가 말투·문장길이·이모지·해시태그·**사진 배치 패턴**을 구체적으로 담는다.

### A-2. 글쓰기 플로우 (사진 → SEO 브리프 → 글/배치 → 발행)

- [ ] 사진이 `data/input/<job>/photos/` 아래에 있고(사용자가 수동 ZIP으로 채움), Claude가 **모든 사진을
      재귀로 직접 열어** 태깅한다 → `data/drafts/<job>/photo_tags.json`.
- [ ] `description.txt`(메모)는 **선택**. 없으면 멈추지 않고 **비전 단독 모드**로 사진만 보고 쓴다
      (확인 안 되는 가격·고유명사는 날조 금지).
- [ ] (선택) SEO 브리프 생성이 동작하고 `data/drafts/<job>/SEO_BRIEF.md`가 생긴다.

```bash
python main.py seo-generate-brief --job <job>
```

- [ ] Claude가 `prompts/write_post.md`를 따라 본문/배치를 작성한다 →
      `data/drafts/<job>/post.md` + `data/drafts/<job>/layout.json`.
- [ ] `layout.json`이 `src/blog_automation/content/schema.py` 스키마를 정확히 지킨다(publish가 그대로 파싱).
- [ ] 발행(임시저장)이 동작한다. **임시저장까지만** 되고 최종 발행은 안 된다는 점 확인.

```bash
python main.py publish --job <job> --yes
```

- [ ] (선택) 드라이런으로 실제 입력 없이 흐름만 확인.

```bash
python main.py publish --job <job> --dry-run
```

### A-3. 영상 → GIF 움짤

- [ ] 영상 스캔이 프레임을 뽑아 Claude가 볼 수 있게 한다(원본 영상 통째 분석 금지).

```bash
python main.py video-scan --job <job>
```

- [ ] Claude가 프레임만 보고 쓸 구간을 골라 `data/drafts/<job>/video_plan.json`을 쓴다.
- [ ] 렌더가 GIF를 만들고 `photos/_gifs/`에 떨어진다(이후 사진과 동일하게 발행됨).

```bash
python main.py video-render --job <job>
```

### A-4. inspect-dom (plain + --editor + --json)

- [ ] 기본 inspect-dom가 동작한다.

```bash
python main.py inspect-dom --list buttons
```

- [ ] 에디터 화면 기준으로도 동작한다.

```bash
python main.py inspect-dom --editor --list interactive
```

- [ ] 구조화 JSON 출력이 동작한다(status OK/MISS/AMBIGUOUS/ERROR 등).

```bash
python main.py inspect-dom --selector "button[data-name='map']" --json
```

### A-5. 답방 댓글 (engage scan / run)

- [ ] 대상 수집이 동작하고 `data/engage/<job>/targets.json`이 생긴다.

```bash
python main.py engage scan --post <logNo|url> --job <job>
```

- [ ] Claude가 `prompts/write_comments.md`를 따라 `data/engage/<job>/comments.json`을 만든다(복붙 금지).
- [ ] 댓글 실행이 동작한다(`--go` 없으면 안전 미리보기).

```bash
python main.py engage run --job <job> --go
```

- [ ] ⭐ A 섹션 전체 공통: **모든 산출물이 예전과 동일한 `data/` 경로**에 그대로 떨어진다(경로 회귀 없음).

---

## (B) 단위 테스트

- [ ] 전체 단위 테스트가 통과한다 → **77 passed**.

```bash
python -m pytest -q
```

---

## (C) WORKSPACE 모드 — 모든 런타임 데이터가 워크스페이스 아래로

> `VOICEPRINT_WORKSPACE` 환경변수 또는 글로벌 `--workspace <path>` 플래그로 워크스페이스를 지정한다.
> 해석 우선순위(`get_workspace_root()`): ① `--workspace` → ② `VOICEPRINT_WORKSPACE` →
> ③ `config/settings.yaml`의 `paths.workspace`(기본엔 없음) → ④ 폴백: 레포-로컬 `data/`(=DEV 모드).

- [ ] 환경변수로 워크스페이스를 지정하면 경로가 그 아래로 해석된다.

```bash
export VOICEPRINT_WORKSPACE=/path/to/ws
python main.py publish --job <job> --dry-run
```

- [ ] 글로벌 플래그(서브커맨드 **앞**)로도 동일하게 동작한다.

```bash
python main.py --workspace /path/to/ws publish --job <job> --dry-run
```

- [ ] 다음 경로들이 모두 **워크스페이스 아래**로 해석되는지 확인:
  - [ ] `<ws>/input/<job>/photos/`, `<ws>/input/<job>/description.txt`
  - [ ] `<ws>/drafts/<job>/`
  - [ ] `<ws>/collected/<id>/`
  - [ ] `<ws>/engage/<job>/`
  - [ ] `<ws>/auth/`
  - [ ] `<ws>/logs/` (blog_automation.log, screenshots/, healing-history.jsonl, seo_crawler_failures/)
  - [ ] `<ws>/personas/`
  - [ ] `<ws>/blog_growth/blog_growth.db` (seo-db)
- [ ] 사용자 셀렉터 오버라이드가 `<ws>/config/selectors.user.yaml`에 위치한다
      (워크플로 오버라이드는 `<ws>/config/workflows.user.yaml`).
- [ ] ⭐ DEV 모드와 동시 비교: 워크스페이스를 끄면(`unset VOICEPRINT_WORKSPACE`) 다시 레포-로컬 `data/`로
      폴백된다.

---

## (D) Electron 앱

> 앱(app/)은 사용자의 **본인 `claude` CLI**를 PTY(node-pty)로 감싼 셸이다. **구독 로그인만** 쓰고
> API 키는 쓰지 않는다. 앱 레벨 설정은 워크스페이스가 아니라 OS 앱-데이터(userData)에 저장된다
> (`app-config.json` = 워크스페이스 경로, `secrets.enc.json` = OS 키체인/safeStorage 암호화 자격증명).
> 레포의 `.env`는 앱이 쓰지 않는다.

- [ ] 앱이 실행/포커스된다.

```bash
python main.py app
# 또는 인자 없이
python main.py
```

- [ ] 워크스페이스 **선택**이 동작한다(📂 작업 폴더 바꾸기), 그리고 **변경**도 동작한다.
- [ ] 드롭존에 끌어놓은 사진·영상이 `<ws>/input/<job>/photos/`에 들어간다.
- [ ] 📝 메모로 작성한 내용이 `<ws>/input/<job>/description.txt`에 저장된다.
- [ ] 초안 산출물이 `<ws>/drafts/<job>/` 아래에 생긴다(post.md, layout.json, photo_tags.json 등).
- [ ] 앱이 PTY 환경에 `VOICEPRINT_WORKSPACE`를 주입해서, 앱 안에서 Claude가 실행하는 명령은
      `--workspace` 없이도 선택한 워크스페이스로 해석된다.
- [ ] `ANTHROPIC_API_KEY`가 설정돼 있으면 **경고만** 띄운다(앱은 그 키를 사용하지 않음 — 구독 로그인 사용).
- [ ] 우측 레일 버튼이 동작하는지 스팟 체크: ▶ Claude 시작 / /status(과금 확인) / 🩺 환경 점검 /
      📂 작업 폴더 바꾸기·폴더 열기·로그 열기 / + 폴더 만들기 / 기존 글 불러오기 / 📝 메모 /
      🔑 SEO 브리프 생성 / 🎬 영상→움짤(GIF) / ✍️ 이 글 쓰고 발행 / 👀 초안 미리보기 /
      🩹 발행 실패 시 자가치유 / 🌐 네이버 보기·네이버 로그인 / 페르소나 업데이트 / 답방 댓글 /
      중단(Ctrl-C) / 화면 지우기 / 설정(⚙ 자격증명 모달).
- [ ] 임베디드 터미널(xterm)이 항상 보이고, 파워 유저가 명령을 직접 타이핑할 수 있다(탈출구).

---

## (E) 셀렉터

> 번들 기본값 `config/selectors.yaml`은 **셀프힐링이 절대 건드리지 않는 안정 기준선(baseline)**.
> 사용자 런타임 오버라이드 `<ws>/config/selectors.user.yaml`이 기본값 **위로 딥머지**된다.
> 값 포맷은 **옛 문자열**과 **새 dict** 둘 다 지원하며, `load_selectors()`가 문자열로 평탄화해
> 기존 소비자가 변경 없이 동작한다.

- [ ] 기본 `config/selectors.yaml`이 기준선 그대로(셀프힐링/실행으로 변경되지 않음)인지 확인.
- [ ] `<ws>/config/selectors.user.yaml`을 두면 기본값 위로 **머지**되어 적용된다.
- [ ] 오버라이드가 없거나 깨져도 **경고 후 기본값으로 폴백**, 발행이 크래시하지 않는다.
- [ ] 값 포맷 호환: **옛 문자열**(`"button:has-text('발행')"`)과
      **새 dict**(`{selector: "...", updated_at, reason, confidence, source}`)가 모두 동작한다.
- [ ] `get_selector(sel, "write.publish_open_button")` 헬퍼가 두 포맷 모두에서 올바른 셀렉터 문자열을 돌려준다.

---

## (F) 셀프힐링 (셀렉터 자가치유)

> 셀프힐 루프는 Claude가 `prompts/self_heal_selector.md`(및 `/blog-run` 스킬
> `.claude/commands/blog-run.md`)를 따라 돈다. **발행 시도 총 3회로 캡**.
> CAPTCHA/로그인/보안 챌린지는 **하드페일** — 절대 우회하지 말고 멈추고 사용자가 보이는 브라우저에서
> 처리하도록 알린다.

- [ ] 구조화 진단 JSON이 동작한다.

```bash
python main.py inspect-dom --selector "[class*='publish_btn']" --json
```

- [ ] 너무 광범위한 셀렉터(`"div"`, `"button"`, `"*"`)를 담은 패치는 **검증에서 거부**된다.

```bash
python main.py validate-selector-patch --patch /path/to/broad_patch.json
```

- [ ] 패치 스키마 검증: `{"type":"selector_patch","target":...,"old_selector":...,"new_selector":...,
      "evidence":{...},"confidence":...,"reason":...}` 형식을 만족해야 통과.
- [ ] 패치 적용이 **오직** `<ws>/config/selectors.user.yaml`에만 쓰고, `<ws>/logs/healing-history.jsonl`에만
      기록한다. **`config/selectors.yaml`이나 소스코드는 절대 수정하지 않는다.**

```bash
python main.py apply-selector-patch --patch /path/to/patch.json --verify
```

- [ ] (앱 모드/`--verify`) 적용 전에 `new_selector`가 라이브 DOM에 매칭되는지 확인한다.
- [ ] 셀프힐 루프가 **발행 시도 3회**를 넘지 않는다(캡 확인).
- [ ] CAPTCHA/로그인/보안 챌린지가 뜨면 **셀프힐하지 않고** 멈춰서 사용자에게 알린다(우회 금지).

---

## (G) 배포 (App Store 없음 — ZIP/수동 공유)

- [ ] 환경 점검 스크립트가 아무것도 설치하지 않고 진단만 한다(앱 🩺 환경 점검과 동일 체크).

```bash
python scripts/check_environment.py
```

- [ ] 배포용 스크립트들이 존재한다:
  - [ ] `scripts/bootstrap-mac.sh` (idempotent: venv, pip, Playwright chromium, ffmpeg 안내, npm 앱 의존성, claude CLI 로그인 안내)
  - [ ] `scripts/bootstrap-windows.ps1` (Windows best-effort)
  - [ ] `scripts/check_environment.py` (진단 전용)
  - [ ] `scripts/create_distribution_zip.sh` (node_modules/data/logs/.env/secrets/유저 패치 제외하고 `VoiceprintStudio/` 스테이징 후 zip)
  - [ ] `START_MAC.command` (더블클릭: 최초 1회 부트스트랩 후 `python main.py app`)
- [ ] 소스 어디에도 개발자 경로 `/Users/seungchanboi`가 **하드코딩되어 있지 않다**(모든 루트는 `Path(__file__)`에서 파생).
- [ ] `.gitignore`가 비밀/데이터/패치를 덮는지 확인:
      `data/`, `logs/`, `.env`, `**/selectors.user.yaml`, `**/healing-history.jsonl`,
      `**/secrets.enc.json`, `**/app-config.json`, `app/node_modules/`, `/dist/`.

---

### 빠른 최종 확인 (회귀 게이트)

- [ ] (A) DEV 모드 산출물이 전부 옛 `data/` 경로로 떨어진다.
- [ ] (B) `python -m pytest -q` → **77 passed**.
- [ ] (C) 워크스페이스 지정 시 모든 경로가 `<ws>/` 아래로 이동한다.
- [ ] (D) 앱이 구독 로그인으로 동작하고 `VOICEPRINT_WORKSPACE`를 PTY에 주입한다(API 키 미사용).
- [ ] (E) 기본 셀렉터 기준선 불변 + 유저 오버라이드 머지 + 문자열/dict 호환.
- [ ] (F) 셀프힐은 user.yaml/healing-history.jsonl에만 쓰고, 3회 캡, CAPTCHA/로그인은 하드페일.
- [ ] (G) 배포 스크립트 정상, 하드코딩 경로 없음, gitignore가 비밀을 덮음.
