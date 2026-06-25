# Naver Blog Growth Agent — 세션 핸드오프 / 정리

> 작성 2026-06-25. 이 문서 = "지난 세션에 뭘 했고, 지금 어디까지 됐고, 새 세션이 뭘 알아야 하는가".
> 새 세션은 이 파일 + `CLAUDE.md` + `README.md`(§4 SEO) 부터 읽으면 됩니다.

---

## 0. TL;DR

기존 블로그 자동화(수집→페르소나→글쓰기→임시저장) **앞단에 SEO 전략 레이어**를 추가했다.
글 쓰기 전에 **네이버 Open API로 키워드를 조사 → 점수화 → Primary 키워드/제목/태그 결정 → `SEO_BRIEF.md` 생성**,
그걸 기존 페르소나 글쓰기가 반영한다. **기존 파이프라인은 안 건드림(전부 additive), 자동 발행 없음(임시저장까지).**

- 새 패키지: `src/blog_automation/seo/` (22개 모듈, ~6,000줄)
- 테스트: `tests/test_*.py` 11개 — **`python -m pytest tests -q` → 77 passed**
- 상태: ✅ 코드/테스트 완료 · ✅ 50개 과거글 DB 적재 · ✅ 페르소나 3종 갱신 · ✅ `/blog`에 SEO 자동단계 박음
- ⚠️ **전부 uncommitted**(working tree). 커밋은 사용자가 원할 때.

---

## 1. 무엇을 만들었나 (SEO 레이어)

`src/blog_automation/seo/` — 역할 분리는 프로젝트 철학 그대로(Python=기계적, Claude=인지적).

| 모듈 | 역할 |
|---|---|
| `config.py` | `GrowthConfig` — `config/blog_growth.yaml` + `.env` 토글 로드 |
| `models.py` | 도메인 dataclass(PostRecord/KeywordResearch/SeoBrief/TopicExtraction/ScoredKeyword 등) |
| `db.py` / `repository.py` | SQLite 스키마(7테이블) + DAO. DB: `data/blog_growth/blog_growth.db` |
| `constants.py` | 카테고리 별칭·키워드 템플릿·롱테일 모디파이어·시즌성·빅키워드 |
| `html_sanitizer.py` | 스냅샷 저장 전 쿠키/토큰/이메일/전화/URL토큰 레다크션 |
| `naver_openapi_client.py` | 검색 API + 데이터랩(검색트렌드/쇼핑인사이트) |
| `naver_searchad_client.py` | 검색광고 키워드툴(HMAC) — **credential 없으면 자동 skip** |
| `crawling_fallback.py` | Open API로 안 되는 것(연관검색어 등) best-effort, rate-limit, sanitize 스냅샷 |
| `naver_data_collector.py` | 키워드별 캐시→API→폴백→정규화→`keyword_research` 적재 |
| `topic_extractor.py` | photo_tags.json + description.txt + 폴더명 → 주제/카테고리/플래그 |
| `keyword_candidate_generator.py` | 카테고리 템플릿 → primary/secondary/tag/avoid 후보 |
| `historical_performance.py` | 과거글 성과/태그 → 강점 키워드, `my_blog_fit_score` |
| `keyword_scoring.py` | 수요·기회·적합도·콘텐츠·시즌 − 경쟁·불일치 → 최종점수, primary 선정 |
| `title_optimizer.py` | 자연스러운 제목 후보 + 점수(스터핑/낚시 감점) |
| `tag_optimizer.py` | 압축 태그 선정 + 빅키워드는 avoid |
| `seo_brief_generator.py` | `SEO_BRIEF.md`/`SEO_REPORT.md` 렌더 |
| `quality_guard.py` | 기계적 품질검사(키워드 남용·길이·가로선·연속텍스트) |
| `blog_stats_crawler.py` | 내 블로그 통계 수집(⚠️ DOM 미확정 — 아래 §5) |
| `outcome_tracker.py` | 발행 후 1/3/7/30일 성과 회수 → `post_outcomes` |
| `pipeline.py` | CLI가 부르는 오케스트레이션(run_*) |

설정: `config/blog_growth.yaml`(가중치·한도·토글) · `config/selectors.yaml`의 `blog_stats:` 섹션(통계 DOM, 전부 null/TODO).

---

## 2. 현재 상태 (지난 세션에서 완료)

- **DB 적재**: `seo-import-posts --id cloudy43_` 로 과거글 **50개** 적재(정규화: 맛집 45 / 육아템 5). + 데모로 `keyword_research` 캐시 25건.
- **페르소나 3종 최신화**(최신 50개 기준 정량치 갱신):
  - `맛집카페방문`(38글): 첫블록 97% 단독 / 그룹 최빈 **2장** / 단독56:그룹43 / 태그 9.6 / 어미 ~어요·습니다 혼용
  - `육아제품리뷰`(6글): 첫블록 83% 단독 / 그룹 최빈 **2장** / 단독49:그룹51 / 태그 8 / 성분·인증 강조
  - `돌잔치키즈나들이`(6글): 첫블록 83% 단독 / 그룹 최빈 **4장** / 단독25:그룹74 / 태그 2.8 / 이모지 많음
- **`/blog` 통합**: `.claude/commands/blog.md` "2) 포스트 작성 & 발행"에 **5단계 = SEO 브리프 자동·필수** 삽입.
  흐름: 준비 → ⭐SEO(자동) → (영상GIF) → 글작성(SEO_BRIEF 반영) → 체크 → publish 임시저장.
- **강점 키워드 학습 활성화**: 통계(조회수) 아직 없어 `my_blog_fit`이 **글 태그 빈도**(성수데이트·성수맛집…)를 강점 신호로 폴백.
  부분일치 매칭이라 `성수`(키워드)⊂`성수데이트`(태그) 인식. → 성수/데이트/가로수길 키워드 +가산, 제주/부산은 중립.

---

## 3. 사용법 (명령어)

```bash
# 1회 셋업
python main.py seo-init-db                       # DB 초기화(멱등)
python main.py seo-import-posts --id cloudy43_    # 과거글 → posts(강점 키워드용)

# 작업별(글 1편)
python main.py seo-research-keywords --job <job>  # 키워드 조사만(선택)
python main.py seo-generate-brief    --job <job>  # ⭐ SEO_BRIEF.md/SEO_REPORT.md 생성 (API 1~3분)
python main.py seo-quality-check      --job <job>  # 작성된 post.md 기계 검사

# 발행 후
python main.py collect-outcomes --days 7          # 성과 회수(blog_stats DOM 확정돼야 실수치)
```

산출물: `data/drafts/<job>/SEO_BRIEF.md`(write_post가 주입) · `SEO_REPORT.md`(검토용) · `seo_brief.json`.
**가장 쉬운 길**: `/blog` → "2) 포스트 작성 & 발행" → job만 주면 SEO부터 임시저장까지 자동.

---

## 4. 알아둘 것 / 자주 하는 오해

- **네이버 개발자센터 사용량이 0으로 보임?** → ① `login_stat` 탭은 *로그인(OAuth) API* 통계라 우리완 무관(우리는 **검색/데이터랩** 탭). ② `seo-init-db`/`seo-import-posts`/`collect`는 API를 **안 부른다**(로컬/비공식). Open API는 `seo-research-keywords`·`seo-generate-brief`에서만. **연결은 정상**(라이브로 검색·데이터랩 호출 성공 확인함).
- **brief 생성이 1~3분** → 연관검색어 **크롤링 폴백의 3~8초 지연** 때문. 정상.
- **SearchAd API** → credential 비어서 `is_configured()=False` → 자동 skip(파이프라인 안 죽음).
- **쇼핑인사이트** → `topic.is_product_review`(육아템/제품리뷰)일 때만 호출.
- **자동 발행 절대 안 함** / 로그인·캡차 우회 안 함 / API key 로그에 안 찍음 / `.env`·DB·스냅샷 전부 `.gitignore`.

---

## 5. 아직 안 된 것 / 다음 할 일 ⭐

1. **블로그 통계 DOM 셀렉터 미확정** (`config/selectors.yaml` → `blog_stats:` 전부 null/TODO).
   - 그래서 `post_metrics`(조회수·검색유입)가 **비어 있음** → `my_blog_fit`은 지금 **태그 기반 추정**으로 동작.
   - 확정 방법: `collect-outcomes` 또는 `blog_stats_crawler`를 한 번 돌리면 실패 시 `logs/seo_crawler_failures/`에
     **sanitize된 HTML + 스크린샷**을 남긴다 → 그걸 보고 셀렉터를 채운다(place_inserter/representative_button과 동일한 self-healing 패턴).
   - 채워지면 "태그 영역 추정" → **"실제 검색 유입 성과"** 기반으로 업그레이드됨.
2. `keyword_rankings`(내 글 노출 순위) 자동 수집 루프 미연결(repository 헬퍼는 있음).
3. DataLab 쇼핑 `cat_id` 매핑이 육아용품 위주(`constants.SHOPPING_CATEGORY_CODES`) — 확장 여지.
4. 실데이터 쌓이면 `keyword_scoring` 가중치(`config/blog_growth.yaml` scoring) 튜닝.

---

## 6. 검증 상태

- `python -m pytest tests -q` → **77 passed** (기존 8 + 신규 69).
- 라이브 Open API 호출 성공(검색·데이터랩). 오프라인 end-to-end 브리프 생성 확인.
- 4-에이전트 적대적 리뷰 후 보안/견고성/정확성 결함 수정 완료(URL 토큰 레다크션, 누적치 중복합산, 깨진 layout.json 가드 등).
- 기존 CLI(collect/publish/engage) 회귀 없음(SEO는 lazy import라 leaf 문제가 기존 커맨드에 영향 X).

---

## 7. 변경/추가 파일 맵 (git 기준 — 전부 uncommitted)

**추가**: `config/blog_growth.yaml`, `scripts/init_blog_growth_db.py`, `src/blog_automation/seo/**`, `tests/test_*.py`(11개), `docs/SEO_GROWTH_AGENT.md`(이 파일)
**수정(additive)**: `src/blog_automation/cli.py`(seo-* 서브커맨드), `.claude/commands/blog.md`(SEO 자동단계), `prompts/write_post.md`(SEO_BRIEF 주입), `config/selectors.yaml`(blog_stats), `.env.example`(SEO 키), `README.md`, `CLAUDE.md`, `personas/*.md`(3종)

> ⚠️ git status에 보이는 `content/schema.py·layout_planner.py·publisher/naver_editor.py·persona_template.md·settings.yaml·analyze_persona.md`는 **이번 SEO 작업과 무관한, 그 전부터 있던 working-tree 변경**.
