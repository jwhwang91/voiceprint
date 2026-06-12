# CLAUDE.md — Claude Code 오케스트레이션 가이드

이 프로젝트는 **Python이 기계적 작업, Claude Code(너)가 인지적 작업**을 맡는 하이브리드 구조다.
너의 역할은 두 가지 단계다. 각 단계의 상세 지시는 `prompts/`에 있다.

## 네가 하는 일

### 1) 페르소나 분석 — `prompts/analyze_persona.md`
- 입력: `data/collected/<id>/*.json` (수집된 과거 글들)
- 작업: 글 종류(맛집/제품리뷰/육아 등)별로 분류 → 말투·문장길이·이모지·해시태그·**사진 배치 패턴**을 분석
- 출력: `personas/<글종류>.md` (`src/blog_automation/persona/templates/persona_template.md` 형식)
- ⭐ 이 .md가 전체 품질을 좌우한다. 구체적이고 재현 가능하게 써라(예: "보통 도입부 1문단 뒤 첫 사진", "문장 끝 'ㅎㅎ' 빈도 높음").

### 2) 사진 분석 + 글·배치 작성 — `prompts/write_post.md`
- 모델: **Opus 4.8**(`.claude/settings.json` 기본값). 사진 비전 분석 + 페르소나 모사 품질용.
- 입력: `personas/<글종류>.md` + `data/input/<job>/photos/*` + `data/input/<job>/description.txt`
  - 사진·메모는 **사용자가 수동**으로 채운다(드라이브 폴더를 ZIP으로 받아 `photos/`에 풀고 `description.txt` 작성). `fetch`/`fetch-doc`(gdown)은 Drive 익명 다운로드 횟수제한으로 배치 시 뒤쪽 폴더가 0장 실패해 더는 기본 경로가 아니다.
  - 사진은 보통 `photos/<카테고리>/` 하위폴더로 분류돼 들어온다. **모든 사진을 재귀로 직접 열어** 태깅하고, **폴더 이름은 카테고리 힌트**로 활용한다. layout.json의 `file`/`files`에는 파일명만 적으면 되며(publish가 재귀 해석), 같은 파일명이 여러 폴더에 있을 때만 `<카테고리>/<파일>`로 구분한다.
- 작업:
  1) `photos/*` 를 **직접 열어 분석·태깅**(파일명 순서 의존 금지) → `data/drafts/<job>/photo_tags.json`
  2) 페르소나 말투로 **약 2000자** 본문 작성
  3) 태그를 근거로 각 사진을 **내용에 맞는 위치**에 배치
- 출력:
  - `data/drafts/<job>/photo_tags.json` — 사진별 분석 태그(category/subject/hero/group_key)
  - `data/drafts/<job>/post.md` — 본문(사진 자리는 `{{photo: 파일명}}`)
  - `data/drafts/<job>/layout.json` — `src/blog_automation/content/schema.py` 스키마 배치도
- 사진 배치는 페르소나 패턴 + 사진 분석 태그를 반드시 반영할 것.
- ⚠️ 대시(`-- — ·`)·구분 기호 금지(네이버가 글 위에 가로선 생성). 텍스트 블록 3개+ 연속 금지.

### 3) 자동 답방 댓글 생성 — `prompts/write_comments.md`
- 입력: `data/engage/<job>/targets.json` (댓글 단 사람들의 최근 글 발췌)
- 작업: 각 글 내용에 맞는 자연스러운 댓글 1~2문장 생성(복붙 금지)
- 출력: `data/engage/<job>/comments.json`
- ⚠️ 스팸/제재 위험 → 글마다 구체 디테일을 짚어 진심 어린 톤으로.

## 절대 규칙
- Python 스크립트(`main.py collect/publish/engage`)는 **사용자가** 실행한다. 너는 산출물 폴더를 읽고 쓰기만 한다.
- 사진 입력은 **사용자가 수동 ZIP 다운로드**로 `data/input/<job>/photos/`에 넣는다(자동 `fetch` 의존 금지). 사진이 비어 있으면 글쓰기를 멈추고 사용자에게 알린다.
- `layout.json`은 `publish` 단계가 그대로 파싱하므로 스키마를 정확히 지켜라.
- 네이버 계정/개인 데이터(`data/` 하위)는 외부로 내보내지 마라.

## 디렉터리 한눈에
- `src/blog_automation/collector/` — 과거 글 수집(Playwright)
- `src/blog_automation/persona/`   — 분석 헬퍼 + 페르소나 템플릿
- `src/blog_automation/drive/`     — 드라이브 다운로드(gdown)
- `src/blog_automation/content/`   — 배치도 스키마/검증
- `src/blog_automation/publisher/` — 네이버 새 글 작성(Playwright)
- `config/selectors.yaml`          — 네이버 DOM 셀렉터(UI 바뀌면 여기만 고침)
