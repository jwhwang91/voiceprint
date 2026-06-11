# 아키텍처

## 설계 원칙: 역할 분리
- **Python (기계적)**: 브라우저 제어(Playwright), 다운로드(gdown), 파일 IO. 결정적이고 반복적인 작업.
- **Claude Code (인지적)**: 스타일 학습, 글쓰기, 사진 배치 계획. 판단이 필요한 작업.
- 둘은 **파일(폴더)** 로만 주고받는다 → 느슨한 결합, 각 단계 독립 실행/디버깅 가능.

## 디렉터리
```
AutomateBlogWriting/
├── main.py                     # CLI 진입점
├── config/
│   ├── settings.yaml           # 경로/브라우저/수집/발행 옵션
│   └── selectors.yaml          # 네이버 DOM 셀렉터 (UI 변경 시 여기만 수정)
├── src/blog_automation/
│   ├── cli.py                  # 서브커맨드 라우팅 (collect/fetch/publish)
│   ├── config.py               # settings.yaml + .env 로딩
│   ├── collector/              # [Python] 과거 글 수집
│   │   ├── naver_login.py      #   로그인(수동 권장/자동)
│   │   ├── post_collector.py   #   목록 순회 → 본문/이미지 수집
│   │   └── models.py           #   CollectedPost
│   ├── persona/                # [Claude 영역] 분석 보조 + 템플릿
│   │   ├── analyzer.py         #   종류별 분석 번들 생성(보조)
│   │   └── templates/persona_template.md
│   ├── drive/                  # [Python] 구글 드라이브 다운로드
│   │   └── downloader.py
│   ├── content/                # [Claude 영역] 배치도 스키마/검증
│   │   ├── schema.py           #   layout.json 스키마 + 검증
│   │   └── layout_planner.py   #   배치도 텍스트 미리보기
│   ├── publisher/              # [Python] 네이버 새 글 작성
│   │   ├── naver_editor.py     #   blocks 순서대로 입력/발행
│   │   └── image_uploader.py   #   파일 선택창 가로채 사진 업로드
│   └── utils/
│       ├── browser.py          #   Playwright persistent context + stealth
│       └── files.py
├── prompts/                    # Claude Code 작업 지시서
│   ├── analyze_persona.md      #   2단계 지시
│   └── write_post.md           #   4단계 지시
├── personas/                   # ⭐ 분석 결과 (글 종류별 .md)
├── data/                       # 런타임 산출물 (gitignore)
│   ├── collected/<id>/         #   수집된 과거 글 + 이미지
│   ├── input/<job>/            #   드라이브에서 받은 사진/설명
│   ├── drafts/<job>/           #   생성된 본문 + 배치도
│   └── auth/<profile>/         #   Playwright 세션(쿠키)
└── docs/
```

## 데이터 흐름(파일 핸드오프)
```
collect ─writes→ data/collected/<id>/*.json
                       │ reads
analyze (Claude) ──────┴──writes→ personas/<종류>.md
fetch   ─writes→ data/input/<job>/photos + description.txt
                       │ reads (+ personas/)
write   (Claude) ──────┴──writes→ data/drafts/<job>/post.md + layout.json
                       │ reads
publish ───────────────┴──→ 네이버 새 글 작성
```

## 네이버 자동화 메모
- SmartEditor ONE 은 `#mainFrame` iframe 안의 contenteditable. frame 진입 필수.
- 사진 업로드는 OS 파일창 → Playwright `expect_file_chooser` 로 경로 주입.
- 셀렉터는 스킨/버전마다 다르므로 `selectors.yaml` 의 TODO 를 최초 1회 채워야 함.
- 봇 탐지 회피: persistent context(세션 재사용), slow_mo, stealth JS, 사람같은 타이핑 delay.
