# 워크스페이스(작업 폴더) 가이드

이 문서는 Voiceprint의 **워크스페이스(작업 폴더)** 개념을 처음부터 끝까지 설명한다.
워크스페이스가 무엇인지, 폴더 구조, 경로가 어떻게 결정되는지, 개발(PyCharm) 모드와 앱 모드의 차이,
Electron 앱에서 작업 폴더를 고르고 바꾸는 방법, 그리고 워크스페이스를 **옮기는 법**과 **백업하는 법**까지 다룬다.

> Voiceprint는 API SaaS가 아니라 **로컬 데스크톱 도구**다. 사용자의 **본인 Claude Code CLI 구독**(Anthropic API/SDK 아님, API 과금 없음),
> 로컬 Python 자동화(Playwright), 로컬 사용자 파일, 그리고 **눈에 보이는 브라우저 기반 네이버 작업**을 오케스트레이션한다.
> 그 "로컬 사용자 파일"이 쌓이는 곳이 바로 워크스페이스다.

---

## 1. 워크스페이스란 무엇이고 왜 필요한가

**워크스페이스 = 런타임 데이터의 루트 폴더**다. 사진·메모·초안·발행 로그·페르소나·로그인 세션·SEO DB 등
"실행하면서 만들어지고 쌓이는 모든 데이터"가 한곳에 모인다.

핵심은 **앱 코드와 사용자 데이터를 분리**하는 것이다.

- 앱을 새 버전으로 교체하거나, ZIP을 다시 풀거나, 저장소를 새로 받아도
  **사용자 데이터(작업 폴더)는 그대로 살아남는다.**
- 즉, 업데이트가 사용자 데이터를 지우지 않는다. 코드는 코드대로, 데이터는 데이터대로 산다.

이 추상화는 `src/blog_automation/paths.py`(`get_workspace_root()`)에 구현되어 있다.

---

## 2. 워크스페이스 폴더 구조(전체)

워크스페이스(`<ws>`) 아래에는 다음과 같은 하위 폴더와 파일이 생긴다.

```text
<workspace>/
├── input/                         # 글 한 건(job)의 입력 (사용자가 채움)
│   └── <job>/
│       ├── photos/                # 사진·영상 (보통 <카테고리>/ 하위폴더로 분류)
│       │   ├── <카테고리>/...      #   ↳ 사진을 카테고리별 하위폴더로 정리
│       │   └── _gifs/             #   ↳ 영상→움짤 렌더 결과 GIF가 여기에 떨어짐
│       └── description.txt        # 메모 (선택 — 없으면 비전 단독 모드로 글 작성)
│
├── drafts/                        # 글 한 건(job)의 산출물 (Claude가 씀)
│   └── <job>/
│       ├── post.md                # 본문 (사진 자리는 {{photo: 파일명}})
│       ├── layout.json            # 배치도 (publish가 그대로 파싱)
│       ├── photo_tags.json        # 사진별 분석 태그(category/subject/hero/group_key)
│       ├── video_plan.json        # 영상 구간 선정 결과(쓸 영상·자를 구간)
│       ├── video/                 # video-scan이 뽑은 프레임
│       ├── SEO_BRIEF.md           # SEO 전략 브리프(있으면 글쓰기에 반영)
│       ├── seo_brief.json         # SEO 브리프 구조화 데이터
│       ├── SEO_REPORT.md          # SEO 리포트
│       └── SEO_QUALITY.json       # SEO 품질 점검 결과
│
├── collected/                     # 과거 글 수집 결과(페르소나 분석 입력)
│   └── <id>/                      #   ↳ *.json
│
├── engage/                        # 답방 댓글 작업
│   └── <job>/
│       ├── targets.json           # 댓글 단 사람들의 최근 글 발췌
│       └── comments.json          # 생성한 답방 댓글
│
├── auth/                          # ⚠️ 네이버 로그인 세션(민감) — 외부 유출 금지
│
├── personas/                      # 페르소나 .md (글종류별 말투/배치 패턴)
│
├── logs/
│   ├── blog_automation.log        # 실행 로그
│   ├── screenshots/               # 발행/디버그 스크린샷
│   ├── healing-history.jsonl      # 셀렉터 자가치유 이력
│   └── seo_crawler_failures/      # SEO 크롤러 실패 기록
│
├── blog_growth/
│   └── blog_growth.db             # SEO 레이어 SQLite DB
│
└── config/
    ├── selectors.user.yaml        # 사용자 셀렉터 오버라이드(기본값 위에 deep-merge)
    └── workflows.user.yaml        # 사용자 워크플로 오버라이드
```

> 참고: `config/selectors.yaml`(번들 기본 셀렉터)는 **저장소 코드 쪽**에 있고 자가치유로도 **절대 수정되지 않는다.**
> 워크스페이스의 `config/selectors.user.yaml`만 사용자/자가치유가 덮어쓴다(아래 4·5장 참고).

---

## 3. 경로 결정 우선순위

`get_workspace_root()`는 다음 **우선순위**로 워크스페이스 루트를 정한다.

1. **CLI 글로벌 플래그** `--workspace <path>`
2. **환경 변수** `VOICEPRINT_WORKSPACE`
3. **설정 파일** `config/settings.yaml`의 `paths.workspace` (선택 키 — 기본값에는 없음)
4. **폴백**: 저장소 로컬 `data/` → 이게 곧 **개발/PyCharm/dev 모드**다

위에서 먼저 잡히는 것이 이긴다. `--workspace`가 있으면 환경 변수·설정·폴백을 모두 무시한다.

### 예시 — 개발(dev) 모드

아무것도 지정하지 않으면 저장소 로컬 `data/`가 워크스페이스가 된다. 동작은 옛 버전과 **바이트 단위로 동일**하다.

```bash
# 아무 워크스페이스도 지정 안 함 → fallback: data/
python main.py publish --job myjob
# input=data/input, drafts=data/drafts, auth=data/auth, collected=data/collected,
# logs=<repo>/logs, personas=<repo>/personas, seo db=data/blog_growth/blog_growth.db
```

`--workspace`는 **모든 명령**에서 동작하며, **서브커맨드 앞**에 둔다.

```bash
# 명시적으로 워크스페이스 지정
python main.py --workspace ~/Documents/VoiceprintWorkspace publish --job myjob

# 환경 변수로 지정
export VOICEPRINT_WORKSPACE="$HOME/Documents/VoiceprintWorkspace"
python main.py publish --job myjob
```

### 예시 — 앱(워크스페이스) 모드

앱은 선택된 워크스페이스 경로를 PTY 환경에 `VOICEPRINT_WORKSPACE`로 주입한다.
따라서 앱 안에서 Claude가 실행하는 명령은 `--workspace` 없이도 자동으로 그 워크스페이스로 해석된다.

```bash
# 앱 내부 PTY에는 이미 VOICEPRINT_WORKSPACE가 주입돼 있음
python main.py publish --job myjob   # ← 알아서 <ws> 아래로 해석됨
```

워크스페이스 모드에서는 위 2장의 구조 그대로 **모든 것이 선택한 워크스페이스 폴더 아래**에 들어간다.

---

## 4. 앱 모드 vs 개발 모드 비교

같은 코드지만 데이터가 어디에 쌓이는지가 다르다. 핵심 차이는 **logs/personas의 위치**와 **앱 설정/자격증명의 위치**다.

| 항목 | 개발(dev) 모드 (`data/` 폴백) | 앱(워크스페이스) 모드 |
| --- | --- | --- |
| input | `data/input/<job>/` | `<ws>/input/<job>/` |
| drafts | `data/drafts/<job>/` | `<ws>/drafts/<job>/` |
| collected | `data/collected/<id>/` | `<ws>/collected/<id>/` |
| engage | `data/engage/<job>/` | `<ws>/engage/<job>/` |
| auth(로그인 세션) | `data/auth/` | `<ws>/auth/` |
| **logs** | **`<repo>/logs`** (저장소 루트) | **`<ws>/logs`** |
| **personas** | **`<repo>/personas`** (저장소 루트) | **`<ws>/personas`** |
| SEO DB | `data/blog_growth/blog_growth.db` | `<ws>/blog_growth/blog_growth.db` |
| 셀렉터 오버라이드 | `data/config/selectors.user.yaml` | `<ws>/config/selectors.user.yaml` |

### 앱 설정/자격증명은 워크스페이스에 없다 (중요)

Electron 앱의 **앱 레벨 설정**은 워크스페이스가 아니라 **OS의 앱 데이터 폴더(Electron userData)**에 저장된다.

- `userData/app-config.json` — 선택한 워크스페이스 경로 등 앱 설정
- `userData/secrets.enc.json` — 암호화된 자격증명(OS 키체인, `safeStorage` 기반)

또한 저장소의 `.env`는 **앱에서 사용하지 않는다.**
즉, "어떤 워크스페이스를 쓰는지"는 userData가 기억하고, "그 워크스페이스 안의 데이터"는 작업 폴더가 들고 있다 — 둘은 분리되어 있다.

---

## 5. Electron 앱에서 워크스페이스를 고르고 바꾸기

앱 오른쪽 레일의 **작업 폴더(워크스페이스)** 영역에 관련 버튼이 있다.

- **📂 작업 폴더 바꾸기** — 워크스페이스 폴더를 새로 선택
- **폴더 열기** — 현재 워크스페이스를 파일 탐색기/Finder로 열기
- **로그 열기** — 워크스페이스의 `logs/`를 열기

동작 방식:

1. 기본 워크스페이스는 **`~/Documents/VoiceprintWorkspace`**.
2. 선택한 워크스페이스 경로는 **`userData/app-config.json`**에 저장된다.
3. 앱은 그 경로를 PTY 환경에 **`VOICEPRINT_WORKSPACE`로 주입**한다.
4. 그래서 앱 안에서 Claude가 돌리는 모든 명령은 `--workspace` 없이도 그 워크스페이스로 해석된다.

> 임베디드 터미널(xterm)은 항상 보인다. 파워 유저는 거기에 직접 명령을 칠 수 있다(터미널 탈출구).

### 자가치유 셀렉터와 워크스페이스

네이버 DOM이 바뀌어 발행이 실패하면(자가치유 루프, 발행 **최대 3회 시도까지**) 셀렉터 패치가
**오직 `<ws>/config/selectors.user.yaml`에만** 기록되고, 이력은 `<ws>/logs/healing-history.jsonl`에 남는다.
번들 기본값 `config/selectors.yaml`이나 소스 코드는 **절대 건드리지 않는다.**

> ⚠️ CAPTCHA·로그인·보안/안티봇 챌린지는 **자가치유 대상이 아니다.** 멈추고 사용자가 직접
> 보이는 브라우저에서 처리해야 한다. 보안 우회는 하지 않는다.
> 또한 publish는 설계상 **임시저장까지만** 수행하고, 최종 발행은 사용자가 네이버에서 직접 누른다.

---

## 6. 워크스페이스 옮기기

워크스페이스는 그냥 폴더이므로 옮기기도 간단하다.

1. **앱을 완전히 종료**한다(실행 중에 옮기지 말 것).
2. 워크스페이스 폴더를 원하는 위치로 **이동(또는 복사)**한다.
   ```bash
   # 예: 이동
   mv ~/Documents/VoiceprintWorkspace /Volumes/External/VoiceprintWorkspace
   ```
3. 새 위치를 **다시 인식시킨다.** 둘 중 하나면 된다.
   - 앱에서 **📂 작업 폴더 바꾸기**로 새 위치를 다시 선택한다(경로가 `app-config.json`에 갱신됨), 또는
   - 환경 변수로 지정한다.
     ```bash
     export VOICEPRINT_WORKSPACE="/Volumes/External/VoiceprintWorkspace"
     ```

`auth/`(로그인 세션)·`config/selectors.user.yaml` 등이 폴더 안에 함께 있으므로,
폴더만 통째로 옮기면 로그인 세션과 사용자 셀렉터까지 그대로 따라간다.

---

## 7. 워크스페이스 백업하기

워크스페이스는 **그냥 폴더 하나**다. 백업도 그 폴더를 통째로 복사하면 끝이다.

```bash
# 통째로 복사
cp -R ~/Documents/VoiceprintWorkspace ~/Backups/VoiceprintWorkspace-2026-06-30

# 압축 백업
tar -czf ~/Backups/VoiceprintWorkspace-2026-06-30.tgz \
    -C ~/Documents VoiceprintWorkspace
```

복원은 백업 폴더를 원하는 위치에 풀고, 6장처럼 **작업 폴더 바꾸기**나 `VOICEPRINT_WORKSPACE`로 다시 가리키면 된다.

> ⚠️ **민감 데이터 주의**: `auth/`에는 **네이버 로그인 세션**이 들어 있다. 이 폴더(또는 백업본)가 유출되면
> 계정 세션이 노출될 수 있으니 외부로 내보내거나 공유하지 마라. 백업본도 안전한 곳에 보관할 것.
> (앱의 자격증명은 워크스페이스가 아니라 `userData/secrets.enc.json`에 OS 키체인으로 암호화되어 별도 보관된다.)
