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
| 3. 사진·설명 다운로드 | **Python / gdown** | 구글 드라이브·docs → `data/input/<job>/` |
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

[다운로드]  python main.py fetch     --url <드라이브 공유링크> --job <작업명>
            python main.py fetch-doc --url <구글 docs 링크>     # 여러 글 일괄
            │
            ▼
   data/input/<job>/photos/*  +  description.txt

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
│   └── selectors.yaml            # 네이버 DOM 셀렉터 (UI 바뀌면 여기만 고침)
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
│   └── utils/                    # 브라우저 팩토리·파일 헬퍼
├── data/                         # 로컬 전용: collected / input / drafts / engage / auth
└── logs/                         # 실행 로그 + 그룹 레이아웃 스크린샷
```

## 설치

요구사항: Python 3.10+, Playwright(Chromium). 그 외 의존성은 `requirements.txt` 참고.
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

## 사용

```powershell
python main.py collect  --id <블로그ID>                       # 1. 과거 글 수집
# (Claude Code) 페르소나 분석 → personas/*.md
python main.py fetch    --url <드라이브링크> --job 맛집_260611  # 3. 사진/설명 받기
# (Claude Code) 글 작성 → data/drafts/<job>/
python main.py publish  --job 맛집_260611 --dry-run           # 미리보기(저장 안 함)
python main.py publish  --job 맛집_260611                      # 임시저장
```

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

### (옵션) 자동 답방 — `engage`

내 글에 댓글 단 사람의 블로그를 방문해 **충분히 체류**한 뒤, 글 내용에 맞는 댓글을 남기는 품앗이 보조.

```powershell
python main.py engage scan --post <내글 logNo/URL> --job 답방_260611   # 댓글러+최근글 수집
# (Claude Code) prompts/write_comments.md 따라 댓글 생성 → comments.json
python main.py engage run  --job 답방_260611          # 방문·체류만 (dry-run, 안전)
python main.py engage run  --job 답방_260611 --go      # 실제 댓글 등록
```

## 책임 있는 사용 ⚠️

voiceprint는 **자동 도배/스팸 도구가 아닙니다.** 사람이 검토·발행하는 것을 전제로 설계되었습니다.

- **사람이 마지막에 본다** — 발행은 기본 `save_as_draft`(임시저장)에서 멈추고, 최종 '발행'은 직접 누릅니다.
- **데이터는 로컬에만** — `data/` 하위의 네이버 계정/개인 데이터는 외부로 내보내지 않습니다.
- **플랫폼 약관 존중** — 네이버는 자동 로그인·도배·매크로를 약관으로 제한하며 봇 탐지가 강합니다.
  답방 댓글 등 자동 상호작용은 **계정 정지 위험**이 있어 기본 dry-run, 소량·느린 간격·사람처럼 동작하도록 보수적으로 설계했습니다. 사용 책임은 사용자에게 있습니다.
- 셀렉터가 깨지면 `config/selectors.yaml` 한 곳만 고치면 됩니다.

## 라이선스

개인용 프로젝트. 사용 전 대상 플랫폼의 이용약관을 확인하세요.
