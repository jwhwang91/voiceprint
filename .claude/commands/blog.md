# 블로그 자동화 메인 메뉴

사용자에게 아래 세 가지 작업 중 무엇을 할지 묻는다. 번호나 이름으로 선택하면 해당 섹션의 절차를 따른다.

```
어떤 작업을 할까요?

1) 페르소나 업데이트   — 수집된 과거 글 분석 → personas/ 갱신
2) 포스트 작성 & 발행  — Google Drive 링크 입력 → 글 작성 → 네이버 발행
3) 답방 댓글 작성 & 발행 — 댓글 단 이웃 글 읽기 → 댓글 생성 → 네이버 발행
```

---

## 1) 페르소나 업데이트

### 준비
- `data/collected/` 아래에 수집된 JSON 파일이 있어야 한다.
- 없으면 사용자에게 먼저 `python main.py collect` 를 실행하라고 안내하고 중단.

### 절차
1. `data/collected/<blog_id>/` 의 모든 `.json` 파일을 읽는다.
2. `prompts/analyze_persona.md` 의 지시를 따라 글 종류별로 분석한다.
3. `personas/<글종류>.md` 를 생성/갱신한다 (템플릿: `src/blog_automation/persona/templates/persona_template.md`).
4. 완료 후 생성/수정된 파일 목록과 각 종류별 핵심 특징을 요약해서 보고한다.

---

## 2) 포스트 작성 & 발행

### 준비
1. 사용자에게 **job 이름**(예: `0624 바오 서울`)과 **글 종류**(맛집방문/제품리뷰/육아/여행/일상 등 — 해당 `personas/<글종류>.md` 사용)를 확인한다. 종류가 불명확하면 사진/메모로 추론하거나 1줄로 묻는다.
2. 사진·영상 입력을 확인한다. 기본은 **사용자가 수동 ZIP** 으로 `data/input/<job>/photos/`(하위 카테고리 폴더 포함)에 채운다. 비어 있으면 멈추고 안내한다. (드라이브 링크를 주면 `python main.py fetch --url <링크> --job <job명>` 도 가능하나 배치 시 다운로드 횟수 제한 주의.)
3. `data/input/<job>/description.txt`(메모)는 **선택**. 있으면 사실 근거로, 없으면 사진만 보는 비전 단독 모드로 쓴다(메모를 요구하지 말 것).
4. ⭐ **영상(MOV/MP4) 자동 감지**: `photos/` 하위에 영상 파일이 있으면 아래 5번에서 GIF 움짤로 처리한다. 없으면 5번은 건너뛴다.

### 글 작성
5. **(영상이 있을 때만) 영상 → GIF** — `prompts/write_post.md` §2.5 절차:
   1. `python main.py video-scan --job <job명>` 을 실행해 분석용 프레임을 추출한다.
   2. `data/drafts/<job>/video/frames/` 의 프레임만 보고(원본 영상은 열지 않음) **움직이는 컷만** 선별, 자를 구간(start/duration)을 정해 `data/drafts/<job>/video_plan.json` 을 작성한다.
   3. `python main.py video-render --job <job명>` 을 실행해 GIF 를 `photos/_gifs/` 에 만든다(발행 전 반드시 실행 — 안 하면 GIF 파일이 없어 검증 실패).
6. `prompts/write_post.md` 의 지시를 따라 본문과 배치도를 작성한다 — 사진 태깅 + (있으면) GIF 를 동작에 맞는 위치에 단독 블록으로 배치:
   - `data/drafts/<job>/photo_tags.json` · `post.md` · `layout.json` (영상 있으면 `video_plan.json` 도)
7. 작성 후 체크리스트를 자체 검토하고, 초안 요약(제목, 문단 수, 사진 수, **GIF 수**, 해시태그)을 사용자에게 보여주고 **발행 여부를 확인**한다:
   - 말투가 페르소나 스니펫과 일치 / 사진·GIF 배치가 페르소나 패턴과 일치
   - `layout.json` 의 모든 `image.file` 이 `photos/`(GIF 는 `photos/_gifs/`)에 실제로 존재
   - 사진을 빠뜨리지 않았는가 / GIF 를 대표·콜라주에 넣지 않았는가

### 발행 (자가 치유 포함)
8. `python main.py publish --job <job명>` 을 실행한다.
9. **성공 시**: 발행 완료를 보고하고 종료.
10. **실패 시 (DOM/셀렉터 오류)**:
    - 에러/트레이스백을 읽어 어느 셀렉터가 실패했는지 파악한다.
    - `config/selectors.yaml` 을 읽어 현재 정의를 확인한다.
    - 오류 패턴에서 네이버 구조 변경을 추론해 `config/selectors.yaml` 을 수정한다 (변경 줄에 주석으로 근거 기록).
    - `python main.py publish --job <job명>` 을 한 번 더 실행한다.
    - **재시도 성공 시**: 어떤 셀렉터가 깨졌고 어떻게 고쳤는지 보고 후 종료.
    - **재시도도 실패 시**: 추가 재시도 없이 중단. 실패한 셀렉터, 시도한 수정 내용, 수동 확인이 필요한 부분을 정리해서 보고한다.
11. **실패 시 (셀렉터 오류 아님 — 네트워크/로그인/파일 없음 등)**: `selectors.yaml` 은 건드리지 않고 에러를 그대로 보고한다.

---

## 3) 답방 댓글 작성 & 발행

### 준비
1. 사용자에게 **job 이름**을 묻는다 (예: `20250609_맛집`).
2. `data/engage/<job>/targets.json` 이 있는지 확인한다.
   - 없으면 사용자에게 먼저 `python main.py collect --engage <job명>` 을 실행하라고 안내하고 중단.

### 댓글 생성
3. `prompts/write_comments.md` 의 지시를 따라 댓글을 생성한다.
4. 자체 체크리스트 검토:
   - 댓글마다 글 내용의 구체 디테일이 들어갔는가 (복붙 아님)
   - 1~2문장, 자연스러운 존댓말인가
   - 광고/링크/과한 이모지 없는가
5. `data/engage/<job>/comments.json` 에 저장한다.
6. 생성된 댓글 목록을 사용자에게 미리 보여주고 **발행 여부를 확인**한다.

### 발행 (자가 치유 포함)
7. `python main.py publish --engage <job명>` 을 실행한다.
8. 발행 실패 시 **2) 포스트 작성 & 발행**의 8~11단계와 동일한 자가 치유 절차를 따른다.
