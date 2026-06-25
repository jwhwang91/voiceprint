# voiceprint

> 내 블로그의 **목소리(voiceprint)** 를 학습해, 내 말투와 사진 배치 습관 그대로 새 글의 초고를 써 주는 글쓰기 어시스턴트.

voiceprint는 과거에 쓴 글들을 분석해 **말투 · 문장 리듬 · 이모지 습관 · 해시태그 패턴 · 사진 배치 방식**을 하나의 재사용 가능한 *페르소나*로 추출합니다.
그 페르소나를 바탕으로 새 사진과 메모만 주면, 사람이 쓴 것처럼 자연스러운 초고와 사진 배치도를 만들어 줍니다.
**발행은 항상 사람이 검토한 뒤** 직접 누릅니다 — 자동 도배 도구가 아니라, 내가 더 빨리·일관되게 쓰도록 돕는 보조 도구입니다.

## 핵심 아이디어: 기계적 일 vs 인지적 일

Python은 **기계적인 일**(브라우저 제어, 다운로드, 업로드)만 맡고,
**인지적인 일**(스타일 학습, 글쓰기, 사진 배치 계획)은 Claude Code가 `prompts/`의 지시서를 따라 수행합니다.

| 단계 | 담당 | 입력 → 산출물 |
|------|------|----------------|
| 1. 과거 글 수집 | **Python** (네이버 공개 API, 로그인 불필요) | 블로그 → `data/collected/` |
| 2. 페르소나(voiceprint) 분석 | **Claude Code** | `data/collected/` → `personas/<글종류>.md` ⭐ |
| 3. 사진·설명 준비 | **사람 (수동)** | 드라이브 ZIP 다운로드 + 메모 → `data/input/<job>/` |
| 4. 글 · 사진배치 작성 | **Claude Code** | 페르소나 + 입력 → `data/drafts/<job>/` |
| 5. 네이버 임시저장/발행 | **Python / Playwright** | 초고 + 배치도 → SmartEditor 새 글 |
| (옵션) 자동 답방 댓글 | **Claude Code + Python** | 댓글러 최근 글 → 자연스러운 댓글 |

> ⭐ `personas/<글종류>.md` 가 전체 품질을 좌우합니다. 구체적이고 재현 가능하게 쓰일수록 결과물이 "나답게" 나옵니다.

## 전체 플로우

```
[수집]  python main.py collect --id <블로그ID>
            │
            ▼
   data/collected/<id>/*.json          과거 글 원문 + 이미지 메타

[분석]  Claude Code 에게: "prompts/analyze_persona.md 따라 페르소나 분석해줘"
            │
            ▼
   personas/<글종류>.md   ⭐            말투·구성·사진배치 스타일 정의

[준비]  (수동) 구글 드라이브 폴더 → ZIP 다운로드 → 압축 풀어
        data/input/<작업명>/photos/ 에 사진 넣기 (+ description.txt 메모는 선택)
            │
            ▼
   data/input/<job>/photos/*  (+ description.txt 선택)

[작성]  Claude Code 에게: "prompts/write_post.md 따라 <job> 글 써줘"
            │
            ▼
   data/drafts/<job>/post.md  +  layout.json     본문 + 사진 배치도

[발행]  python main.py publish --job <작업명> --dry-run   # 입력만, 저장 안 함(미리보기)
        python main.py publish --job <작업명>             # 임시저장까지 (기본 안전모드)
            │
            ▼
   네이버 SmartEditor 새 글에 본문/사진 자동 배치 → 임시저장
   (사람이 검토 후 직접 '발행')
```

## 디렉터리 구조

```
voiceprint/
├── main.py                       # CLI 진입점
├── config/
│   ├── settings.yaml             # 전역 설정(경로·브라우저·발행·답방 등)
│   ├── selectors.yaml            # 네이버 DOM 셀렉터 (UI 바뀌면 여기만 고침)
│   └── blog_growth.yaml          # (선택) SEO 레이어 설정(점수 가중치·한도·API 토글)
├── scripts/
│   └── init_blog_growth_db.py    # (선택) SEO 성과 DB 초기화
├── prompts/                      # Claude Code 가 따르는 지시서
│   ├── analyze_persona.md
│   ├── write_post.md
│   └── write_comments.md
├── personas/                     # 학습된 voiceprint (글 종류별)
├── src/blog_automation/
│   ├── collector/                # 과거 글 수집
│   ├── persona/                  # 분석 헬퍼 + 페르소나 템플릿
│   ├── drive/                    # 구글 드라이브/Docs 다운로드 (gdown)
│   ├── content/                  # 배치도 스키마 + 검증
│   ├── publisher/                # 네이버 SmartEditor 발행 (Playwright)
│   ├── engage/                   # 자동 답방 댓글
│   ├── seo/                      # (선택) Naver Blog Growth Agent — 키워드/제목/태그 전략
│   └── utils/                    # 브라우저 팩토리·파일 헬퍼
├── data/                         # 로컬 전용: collected / input / drafts / engage / auth / blog_growth
└── logs/                         # 실행 로그 + 그룹 레이아웃 스크린샷
```

## 설치

요구사항: Python 3.10+, Playwright(Chromium). 그 외 의존성은 `requirements.txt` 참고.
**영상(MOV/MP4) → GIF 기능을 쓰려면 `ffmpeg` 가 필요합니다**(시스템 도구, pip 아님):
macOS `brew install ffmpeg`, Ubuntu `sudo apt install ffmpeg`, Windows `winget install ffmpeg`.
없어도 사진만 쓰는 기존 흐름은 그대로 동작합니다.
Windows · macOS · Linux 모두 동작합니다(코드는 `pathlib` + UTF-8 기반, OS 의존 코드 없음).

**Windows (PowerShell)**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env            # NAVER_ID / NAVER_PW 등 채우기
```

**macOS · Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env              # NAVER_ID / NAVER_PW 등 채우기
```

> macOS 에서는 `python` 대신 `python3` 를 사용하세요. Apple Silicon(M1~)도 Playwright 가 지원합니다.
> Linux 는 파일명 대소문자를 구분하므로 사진 확장자(`.JPG` 등)를 `layout.json` 과 정확히 일치시키세요.

## 설정

- **`.env`** — 계정·런타임 토글: `NAVER_ID`, `NAVER_PW`, `HEADLESS`, `SLOW_MO_MS`.
- **`config/settings.yaml`** — 경로, 브라우저, 수집/발행/답방 옵션. 주요 발행 옵션:
  - `save_as_draft: true` — 임시저장까지만(안전 기본값). `false` 라야 실제 발행 시도.
  - `dry_run: false` — `true` 면 입력만 하고 저장/발행 버튼은 누르지 않음.
  - `group_layout: 슬라이드` — 사진 2장 이상 묶을 때 기본 레이아웃(슬라이드/콜라주/개별).
  - `group_upload_mode: group` — 그룹 묶음 업로드(권장). `individual` 은 한 장씩.
- **`config/selectors.yaml`** — 네이버 DOM 셀렉터. UI가 바뀌면 **여기 한 곳만** 고치면 됩니다.

## 사용 — 단계별 워크플로우

세 가지 작업 흐름입니다. 각 단계에 **Python 명령**(터미널에서 사용자가 직접 실행)과
**Claude Code 명령**(채팅창에 입력)을 함께 표기했습니다.

> Windows PowerShell 기준. macOS·Linux 는 `python` → `python3`.
> Python 명령은 가상환경을 켠 상태에서 실행하세요: `.\.venv\Scripts\Activate.ps1`

### 1) 페르소나 업데이트 (voiceprint 학습)

과거 글을 분석해 말투·구성·사진배치 스타일을 `personas/*.md` 로 추출/갱신합니다.

```powershell
# (Python) 과거 글 수집 — 네이버 공개 API, 로그인 불필요
python main.py collect --id <블로그ID>            # 예: cloudy43_
```
```text
# (Claude Code) 수집한 글을 분석해 personas/*.md 생성·갱신
prompts/analyze_persona.md 따라 페르소나 분석해줘
```
- 입력: `data/collected/<블로그ID>/*.json`  →  산출물: `personas/<글종류>.md` ⭐

### 2) 자동 블로그 글쓰기

**2-1. 사진·메모 준비 (수동 — 가장 안정적)**

> ⚠️ 자동 다운로드(`fetch`/`fetch-doc`, gdown)는 한 번에 여러 폴더를 받으면 구글 드라이브의
> 익명 다운로드 **횟수 제한**에 걸려 뒤쪽 폴더가 "0장"으로 실패합니다(폴더 목록은 보이는데
> 파일 본문은 못 받음). 그래서 **브라우저에서 ZIP 다운로드**가 가장 확실합니다.

1. 구글 드라이브에서 폴더 열기 → 우클릭(또는 우측 상단 ⋮) → **다운로드** (ZIP 으로 받아짐)
2. 압축을 풀어 **카테고리 폴더째** 작업 폴더의 `photos/` 안에 넣기(폴더 이름이 사진 분류 라벨로 쓰임):
   ```
   data\input\<작업명>\photos\<카테고리>\*.jpg
   예: data\input\260615_네이다이닝라운지\photos\사시미 플레이트 2인\IMG_1.JPG
   ```
   - `<작업명>` = `<6자리날짜>_<가게이름>` (예: `260615_네이다이닝라운지`)
   - 카테고리 폴더 구조는 **그대로 둬도 됩니다** — `publish`/검증이 `photos/` 하위를 재귀로 찾습니다(평탄하게 풀어도 동작). 폴더 이름은 글쓰기 단계에서 사진 분류 힌트로 활용됩니다.
3. (선택) 같은 작업 폴더에 방문 메모 작성 → `data\input\<작업명>\description.txt`
   (가는 길·메뉴·느낌 등 자유롭게. 메모가 있으면 글의 사실 근거가 됩니다.
   **없으면** Claude 가 사진만 보고 글을 씁니다 — 비전 단독 모드.)
4. (선택) **영상(MOV/MP4)** 도 사진과 같이 `photos/<카테고리>/` 안에 넣으면 됩니다 — 움직이는 컷은
   글에 **GIF 움짤**로 들어갑니다(아래 2-1.5 / 2-2.5). 안 넣으면 무시됩니다.

**2-1.5. (영상이 있을 때만) 분석용 프레임 추출 (Python)** — ffmpeg 필요
```powershell
# 영상에서 토큰-저렴한 썸네일만 뽑아 둠(원본을 Claude 가 통으로 안 보게)
python main.py video-scan --job <작업명>
```
- 산출물: `data/drafts/<작업명>/video/frames/**` + `videos.json`

**2-2. 글·사진배치 작성 (Claude Code)**
```text
# 사진을 직접 보고 태깅 → 페르소나 말투로 본문(~2000자) + 배치도 작성
prompts/write_post.md 따라 <작업명> 글 써줘       # 예: 260615_네이다이닝라운지
```
- 산출물: `data/drafts/<작업명>/` 의 `photo_tags.json` · `post.md` · `layout.json`
  (영상이 있으면 `video_plan.json` 도 — 어떤 영상을 어디서 어디까지 자를지)

**2-2.5. (영상이 있을 때만) GIF 렌더 (Python)** — ffmpeg 필요, **publish 전에 실행**
```powershell
# video_plan.json 의 구간을 GIF 로 만들어 photos/_gifs/ 에 저장 → 발행이 사진처럼 픽업
python main.py video-render --job <작업명>
```

**2-3. 네이버 발행 (Python)**
```powershell
# 미리보기 — 입력만 하고 저장/발행 버튼은 안 누름
python main.py publish --job <작업명> --dry-run
# 임시저장까지 (기본 안전모드). 최종 '발행'은 네이버에서 직접 확인 후 클릭
python main.py publish --job <작업명>
```

### 3) 자동 답방 (품앗이 댓글)  ⚠️ 보수적으로

내 글에 댓글 단 이웃의 글을 방문·체류한 뒤, 글 내용에 맞는 댓글을 남깁니다.

```powershell
# (Python) 댓글러 + 그들의 최근 글 수집 → targets.json
python main.py engage scan --post <내글 logNo 또는 URL> --job 답방_<날짜>
```
```text
# (Claude Code) 글 내용에 맞는 자연스러운 댓글 생성 → comments.json
prompts/write_comments.md 따라 답방_<날짜> 댓글 써줘
```
```powershell
# (Python) 방문·체류만 (dry-run, 안전)
python main.py engage run --job 답방_<날짜>
# (Python) 실제 댓글 등록
python main.py engage run --job 답방_<날짜> --go
```
> 약관상 계정 정지 위험 → 기본 dry-run. 소량·느린 간격으로만 사용하세요.

### 4) SEO 전략 (선택) — Naver Blog Growth Agent

글을 쓰기 **전에** 검색 유입이 높은 **키워드·제목·태그 전략**을 결정해 `SEO_BRIEF.md` 로 만들어 두는
부가 레이어입니다. **기존 글쓰기 흐름을 바꾸지 않습니다** — 브리프가 있으면 작성 단계(2-2)가
이를 반영하고, 없으면 그냥 페르소나대로 씁니다. **자동 발행은 절대 하지 않습니다(임시저장까지만).**

준비물: `.env` 에 네이버 Open API 키(`NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`)를 채웁니다.
키가 없으면 크롤링 폴백으로 완만히 동작하고, 검색광고 API(`NAVER_SEARCHAD_*`)는 비어 있으면 자동 skip 됩니다.

```powershell
# (1회) 성과 DB 초기화
python main.py seo-init-db
# (1회/주기) 과거 수집글을 성과 DB(posts)에 적재 — 내 블로그가 강한 키워드 학습용
python main.py seo-import-posts --id <블로그ID>

# (작업별) 키워드 조사 → SEO_BRIEF.md / SEO_REPORT.md 생성
python main.py seo-research-keywords --job <작업명>     # 키워드만 조사(선택)
python main.py seo-generate-brief    --job <작업명>     # 전략 브리프 생성 ⭐
```
```text
# (Claude Code) 글쓰기 — SEO_BRIEF.md 가 있으면 자동으로 반영(없으면 기존대로)
prompts/write_post.md 따라 <작업명> 글 써줘
```
```powershell
# (작성 후, 선택) 키워드 남용·길이·가로선 등 기계 품질검사
python main.py seo-quality-check --job <작업명>
# (발행 후, 선택) 1/3/7/30일 조회수·검색유입 회수 → 다음 글 전략에 학습
python main.py collect-outcomes --days 7
```
- 산출물: `data/drafts/<작업명>/SEO_BRIEF.md`(작성 프롬프트에 주입) · `SEO_REPORT.md`(사람 검토용)
- 우선순위: **① 사진/영상 사실 → ② 페르소나 말투 → ③ SEO 전략 → ④ 자연스러운 문체.**
  SEO 는 ①②를 깨지 않습니다(키워드 욱여넣기·낚시 제목·날조 금지).
- 설정: `config/blog_growth.yaml`(점수 가중치·후보/태그 한도·품질 기준), 토글은 `.env` 의 `NAVER_KEYWORD_USE_*`.

### 산출물 형식 — `layout.json`

발행 단계가 그대로 파싱하는 사진 배치도입니다. 블록을 위에서 아래로 순서대로 입력합니다.

```jsonc
{
  "title": "글 제목",
  "persona": "맛집카페방문",
  "blocks": [
    { "type": "image", "file": "photo_01.jpg", "align": "center" },     // 단독 사진
    { "type": "text",  "content": "도입부 문단..." },
    { "type": "image", "files": ["a.jpg", "b.jpg"], "align": "center" }, // 그룹(슬라이드/콜라주)
    { "type": "tags",  "items": ["성수맛집", "성수데이트"] }
  ]
}
```

단독 사진은 `"file"`(문자열), 그룹은 `"files"`(배열) — 발행기가 이걸로 단독/그룹을 구분합니다.

## 책임 있는 사용 ⚠️

voiceprint는 **자동 도배/스팸 도구가 아닙니다.** 사람이 검토·발행하는 것을 전제로 설계되었습니다.

- **사람이 마지막에 본다** — 발행은 기본 `save_as_draft`(임시저장)에서 멈추고, 최종 '발행'은 직접 누릅니다.
- **데이터는 로컬에만** — `data/` 하위의 네이버 계정/개인 데이터는 외부로 내보내지 않습니다.
- **플랫폼 약관 존중** — 네이버는 자동 로그인·도배·매크로를 약관으로 제한하며 봇 탐지가 강합니다.
  답방 댓글 등 자동 상호작용은 **계정 정지 위험**이 있어 기본 dry-run, 소량·느린 간격·사람처럼 동작하도록 보수적으로 설계했습니다. 사용 책임은 사용자에게 있습니다.
- 셀렉터가 깨지면 `config/selectors.yaml` 한 곳만 고치면 됩니다.

## 라이선스

개인용 프로젝트. 사용 전 대상 플랫폼의 이용약관을 확인하세요.
