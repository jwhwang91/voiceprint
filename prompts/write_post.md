# 지시서: 글 + 사진배치 작성 (Claude Code 수행)

## 목표
페르소나 말투로 본문을 쓰고, 사진을 어디에 어떻게 배치할지 **배치도**를 만든다.

## 입력
- `personas/<글종류>.md` — 적용할 페르소나 (어떤 종류인지 사용자에게 확인하거나 설명으로 추론)
- `data/input/<job>/photos/*` — 사용할 사진들 (파일명 순 ≈ 촬영 순)
- `data/input/<job>/description.txt` — 사용자가 적은 간단한 설명
- 배치도 형식: `src/blog_automation/content/schema.py` 의 `LAYOUT_SCHEMA`

## 절차
1. 적용할 페르소나 .md 를 정한다(종류 확인).
2. `photos/` 의 사진 목록과 `description.txt` 를 읽고, 각 사진이 무엇인지 매칭한다.
   - 필요하면 사진을 직접 열어(Read) 내용을 파악한다.
3. 페르소나의 **글 구조**대로 본문을 쓴다 — 말투/어미/추임새/길이를 그대로 반영.
4. 페르소나의 **사진 배치 · 첨부 방식**대로 사진을 본문 사이에 배치한다:
   - 첫 사진 위치, 간격, 캡션 유무를 페르소나에 맞춘다.
   - 모든 사진을 빠짐없이 쓰되, 배치 패턴에 어긋나면 순서/그룹을 조정한다.
   - **단독 vs 그룹 비율**: 페르소나의 첨부 방식 수치를 따른다.
   - **그룹 크기**: 페르소나의 최빈 그룹 크기(2장/3장/4장)를 기본으로 하되,
     내용상 같이 묶이는 사진(같은 공간 여러 각도, 같은 메뉴 여러 컷 등)끼리 그룹화한다.
5. 두 파일을 만든다:
   - `data/drafts/<job>/post.md` — 사람이 읽기 좋은 본문. 사진 자리는 `{{photo: 파일명}}`.
   - `data/drafts/<job>/layout.json` — `LAYOUT_SCHEMA` 를 정확히 따르는 배치도(발행이 이걸 파싱).
     **image 블록 작성 규칙 (중요)**:
     - 단독 사진: `{"type":"image","file":"파일명.jpg","align":"center"}`
     - 그룹/콜라주: `{"type":"image","files":["a.jpg","b.jpg","c.jpg"],"align":"center"}`
     - `file`(문자열) vs `files`(배열)을 혼용하지 말 것. publisher가 이걸로 단독/그룹을 판별함.
6. 해시태그를 페르소나대로 마지막 `tags` 블록에 넣는다.

## 출력
- `data/drafts/<job>/post.md`
- `data/drafts/<job>/layout.json`  (blocks 배열: text/image/tags/heading/quote)

## 체크리스트
- [ ] 말투가 페르소나 예시 스니펫과 비슷한가
- [ ] 사진 배치가 페르소나 패턴과 일치하는가
- [ ] layout.json 의 모든 image.file 이 photos/ 에 실제로 존재하는가
- [ ] 사진을 하나도 빠뜨리지 않았는가
