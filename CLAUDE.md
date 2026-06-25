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
- 입력: `personas/<글종류>.md` + `data/input/<job>/photos/*` + `data/input/<job>/description.txt` **(메모는 선택)**
  - 사진·메모는 **사용자가 수동**으로 채운다(드라이브 폴더를 ZIP으로 받아 `photos/`에 풀고 `description.txt` 작성). `fetch`/`fetch-doc`(gdown)은 Drive 익명 다운로드 횟수제한으로 배치 시 뒤쪽 폴더가 0장 실패해 더는 기본 경로가 아니다.
  - 사진은 보통 `photos/<카테고리>/` 하위폴더로 분류돼 들어온다. **모든 사진을 재귀로 직접 열어** 태깅하고, **폴더 이름은 카테고리 힌트**로 활용한다. layout.json의 `file`/`files`에는 파일명만 적으면 되며(publish가 재귀 해석), 같은 파일명이 여러 폴더에 있을 때만 `<카테고리>/<파일>`로 구분한다.
  - ⭐ **메모(description.txt)가 없으면** 멈추지 말고 **비전 단독 모드**로 사진만 보고 글을 쓴다(사진에서 확인 안 되는 가격·고유명사는 지어내지 말 것). 상세는 `prompts/write_post.md` §0.
  - ⭐ **영상(MOV/MP4)이 섞여 있으면** GIF 움짤로 넣는다. 원본 영상을 통으로 열지 말고(토큰 폭증),
    먼저 `video-scan` 이 뽑은 **프레임**만 보고 "쓸 영상·자를 구간"을 정해 `video_plan.json` 을 쓴 뒤,
    `video-render` 로 GIF 를 만든다(Python=프레임추출·렌더, 너=구간 선정). 상세는 `prompts/write_post.md` §2.5.
- 작업:
  1) `photos/*` 를 **직접 열어 분석·태깅**(파일명 순서 의존 금지) → `data/drafts/<job>/photo_tags.json`
  2) 페르소나 말투로 **약 2000자** 본문 작성
  3) 태그를 근거로 각 사진을 **내용에 맞는 위치**에 배치
- 출력:
  - `data/drafts/<job>/photo_tags.json` — 사진별 분석 태그(category/subject/hero/group_key)
  - `data/drafts/<job>/post.md` — 본문(사진 자리는 `{{photo: 파일명}}`)
  - `data/drafts/<job>/layout.json` — `src/blog_automation/content/schema.py` 스키마 배치도
- 사진 배치는 페르소나 패턴 + 사진 분석 태그를 반드시 반영할 것.
- ⭐ **장소(지도)**: 방문형 글이면 상호를 **웹검색으로 네이버 플레이스 정식 지점명·주소를 확정**해
  `place` 블록(`{"type":"place","query":...,"name":...,"address":...}`)을 넣는다. 발행 시 publish 가
  네이버 '장소' 버튼을 눌러 지도 카드를 본문에 삽입한다. 엉뚱한 지점·날조 주소 금지(모호하면 질문/생략).
- ⭐ **줄바꿈(모바일 우선)**: 블로그는 모바일로 읽힌다. 페르소나의 줄바꿈/문단 형식을 텍스트 블록
  `content` 안 `\n` 으로 그대로 재현(블록을 쪼개지 말 것).
- ⚠️ 대시(`-- — ·`)·구분 기호 금지(네이버가 글 위에 가로선 생성). 텍스트 블록 3개+ 연속 금지.

### 3) 자동 답방 댓글 생성 — `prompts/write_comments.md`
- 입력: `data/engage/<job>/targets.json` (댓글 단 사람들의 최근 글 발췌)
- 작업: 각 글 내용에 맞는 자연스러운 댓글 1~2문장 생성(복붙 금지)
- 출력: `data/engage/<job>/comments.json`
- ⚠️ 스팸/제재 위험 → 글마다 구체 디테일을 짚어 진심 어린 톤으로.

### 4) (선택) SEO 전략 브리프 소비 — `data/drafts/<job>/SEO_BRIEF.md`
- SEO 레이어(`src/blog_automation/seo/`, 별도 부가 모듈)가 글쓰기 **앞단**에서 검색 유입이 높은
  **Primary/Secondary 키워드·추천 제목·태그·검색 의도**를 정해 `SEO_BRIEF.md` 로 만들어 둔다.
  생성은 **사용자가** `python main.py seo-generate-brief --job <job>` 으로 실행한다(너는 산출물만 소비).
- 글쓰기(2단계)에서 `data/drafts/<job>/SEO_BRIEF.md` 가 **있으면 반드시 반영**한다. 상세는 `prompts/write_post.md`.
  - ⚠️ 우선순위: ① 사진/영상 **사실** → ② **페르소나** 말투 → ③ SEO 키워드/제목/태그 → ④ 자연스러운 문체.
    SEO 가 ①②를 깨지 않는다. 키워드 욱여넣기·낚시 제목·사진과 안 맞는 키워드(브리프의 Avoid)는 금지.
  - 브리프가 **없으면** 기존대로 페르소나 글쓰기로 진행(멈추지 말 것).
- ⚠️ SEO 레이어는 **절대 자동 발행하지 않는다**(임시저장까지만). 네이버 통계/크롤링은 사용자 로그인 세션만 쓰고 캡차 우회 금지.

## 절대 규칙
- Python 스크립트(`main.py collect/fetch/video-scan/video-render/publish/engage` 및 SEO: `seo-init-db/seo-import-posts/seo-research-keywords/seo-generate-brief/seo-quality-check/collect-outcomes`)는 **사용자가** 실행한다. 너는 산출물 폴더를 읽고 쓰기만 한다.
- 사진 입력은 **사용자가 수동 ZIP 다운로드**로 `data/input/<job>/photos/`에 넣는다(자동 `fetch` 의존 금지). 사진이 비어 있으면 글쓰기를 멈추고 사용자에게 알린다. `description.txt`(메모)는 **선택** — 없으면 사진만으로 쓰는 **비전 단독 모드**로 진행한다.
- 영상(MOV/MP4)은 같은 `photos/` 폴더에 섞여 들어온다. **GIF 움짤로만** 글에 넣고(네이버 동영상 첨부 X), 원본 영상을 비전으로 통째 분석하지 마라(`video-scan` 프레임만 본다). 만든 GIF 는 `photos/_gifs/` 에 떨어져 사진과 동일하게 발행된다(`.gif` 는 이미 이미지 취급).
- `layout.json`은 `publish` 단계가 그대로 파싱하므로 스키마를 정확히 지켜라.
- 네이버 계정/개인 데이터(`data/` 하위)는 외부로 내보내지 마라.

## 디렉터리 한눈에
- `src/blog_automation/collector/` — 과거 글 수집(Playwright)
- `src/blog_automation/persona/`   — 분석 헬퍼 + 페르소나 템플릿
- `src/blog_automation/drive/`     — 드라이브 다운로드(gdown)
- `src/blog_automation/video/`     — 영상 → GIF(프레임 추출 scan + ffmpeg 렌더 render)
- `src/blog_automation/content/`   — 배치도 스키마/검증
- `src/blog_automation/publisher/` — 네이버 새 글 작성(Playwright). `place_inserter.py` = 장소(지도) 카드 삽입
- `src/blog_automation/seo/`        — (선택) Naver Blog Growth Agent: 키워드 조사·점수·제목/태그·SEO_BRIEF 생성·성과 회수
- `config/selectors.yaml`          — 네이버 DOM 셀렉터(UI 바뀌면 여기만 고침)
- `config/blog_growth.yaml`        — (선택) SEO 레이어 설정(점수 가중치·후보/태그 한도·API 토글)
