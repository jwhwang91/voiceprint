# 작업 흐름 (실전)

## 0. 준비 (최초 1회)
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
```
- 처음 실행 시 `config/selectors.yaml` 의 `TODO` 셀렉터를 채워야 한다.
  네이버 글 목록/본문/작성 화면에서 개발자도구(F12)로 셀렉터를 확인해 입력.

## 1. 과거 글 수집
```powershell
python main.py collect --id 블로그주소아이디 --max 50
```
- ⚠️ **`--id` 는 블로그 주소 아이디**(예: `cloudy43_`)로, 로그인 ID(`cloudy9191`)와 다를 수 있음.
  본인 블로그 주소 `blog.naver.com/____` 의 `____` 부분.
- 네이버 공개 API(`PostTitleListAsync`/`PostView`/`BlogTagListInfo`)로 수집 → **로그인 불필요, Playwright 불필요**. 공개 글만 대상.
- 결과: `data/collected/<id>/*.json` (제목·본문·태그·**블록순서**) + `images/`

## 2. 페르소나 분석  ← Claude Code
Claude Code 세션에서:
> `prompts/analyze_persona.md` 따라 `data/collected/내블로그아이디` 분석해서 `personas/` 에 종류별 .md 만들어줘
- 결과: `personas/맛집방문.md`, `personas/제품리뷰.md` ...
- 사람이 한번 읽고 어색한 부분 수정하면 품질이 크게 오른다.

## 3. 드라이브 사진/설명 받기
```powershell
python main.py fetch --url "<구글드라이브 공유링크>" --job 맛집_240608
```
- 드라이브 폴더는 '링크가 있는 모든 사용자' 로 공개돼 있어야 한다.
- 결과: `data/input/맛집_240608/photos/*` + `description.txt`
- `description.txt` 에 사진별 간단 설명을 적는다(없으면 사진만 보고 작성).

## 4. 글 + 사진배치 작성  ← Claude Code
> `prompts/write_post.md` 따라 `맛집_240608` 글 써줘. 페르소나는 맛집방문.
- 결과: `data/drafts/맛집_240608/post.md` + `layout.json`
- `post.md` 로 본문 검토, 필요시 수정 요청.

## 5. 발행
```powershell
python main.py publish --job 맛집_240608 --dry-run   # 먼저 입력만 확인
python main.py publish --job 맛집_240608             # 임시저장(기본 안전모드)
```
- 발행 전 배치도 미리보기 + y/N 확인.
- 기본은 **임시저장**까지만(settings.yaml `save_as_draft: true`). 네이버에서 최종 검토 후 직접 발행 권장.
- 실제 자동 발행하려면 `save_as_draft: false`.

## 팁
- 세션은 `data/auth/<id>/` 에 저장돼 다음부터 로그인 생략.
- 네이버 발행은 하루 몇 건 이내로, 사람처럼. 도배는 계정 정지 위험.
