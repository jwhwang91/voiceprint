# Voiceprint Studio — v0 프로토타입

블로그 자동화 워크플로(`/blog`)를 **코드 모르는 사람도 버튼으로** 굴리게 하는 데스크톱 셸.
핵심: **API 를 쓰지 않는다.** 사용자가 *자기 손으로 로그인한* `claude` CLI 를 앱 안 터미널에 그대로 띄우고,
버튼/드래그앤드롭을 그 위에 얹는다 → 본인 구독으로 과금되고, 헤드리스 빌링 버그/SDK ToS 를 피한다.

## 이 v0 가 검증하는 것
1. 앱 안 터미널에 **진짜 claude TUI** 가 뜨는가
2. 버튼이 그 세션에 명령을 주입하는가 (`/blog`, `1/2/3`, `/status`, Ctrl-C)
3. **과금이 구독으로** 떨어지는가 → `/status (과금 확인)` 버튼으로 플랜 표시 확인
   (만약 `ANTHROPIC_API_KEY` 가 환경에 깔려 있으면 종량제 API 로 청구되니 `unset` 후 실행)
4. 드래그앤드롭이 `data/input/<job>/photos/` 로 사진을 꽂고 HEIC→JPG 변환하는가

## 사전 준비
- Node 18+ (현재 머신 확인됨), macOS Xcode Command Line Tools (네이티브 빌드용)
- `claude` 설치 + 로그인 완료 (`claude` 로 한 번 로그인 → 구독 연결)

## 실행
```bash
cd app
npm install        # postinstall: node-pty 를 Electron ABI 로 rebuild + electron 바이너리 무결성 보장
npm start
```
postinstall 이 두 가지를 자동 처리한다:
- `electron-rebuild -f -w node-pty` — 네이티브 PTY 모듈을 Electron ABI 로 빌드
- `node scripts/ensure-electron.js` — Electron dist 가 불완전하면(Node 26 + electron 33 의
  extract-zip 무음 실패 케이스) 캐시된 zip 을 시스템 unzip 으로 직접 풀어 복구

문제가 생기면 개별 실행:
```bash
npm run rebuild        # node-pty 만 재빌드
npm run fix-electron   # electron 바이너리만 복구
```

## 첫 실행 때 보이는 것
- 창이 뜨고 가운데 터미널에 로그인 셸 프롬프트(레포 루트 cwd)
- 우측 상단 칩에 `claude 2.1.x` (초록) — 미설치면 빨강
- **▶ Claude 시작** 클릭 → 터미널에서 claude TUI 가 뜸
- **/status (과금 확인)** 클릭 → 플랜이 구독으로 잡히는지 확인
  (`ANTHROPIC_API_KEY` 가 셸에 깔려 있으면 종량제로 빠지니 `unset` 후 실행)

## 화면
- 가운데: 실제 claude 가 도는 터미널(xterm.js) — 직접 타이핑도 됨(파워유저 비상구)
- 오른쪽 버튼:
  - **▶ Claude 시작** → 터미널에 `claude` 입력. 먼저 누르고 시작.
  - **/status (과금 확인)** → 구독 플랜인지 확인
  - **/blog 메뉴 열기** + **① 페르소나 / ② 글쓰기·발행 / ③ 답방** → 메뉴 번호 주입
  - **+ 새 글 폴더** → `data/input/<이름>/photos/` 생성, 드롭존 활성화
  - **드롭존** → 사진/영상 폴더째 드롭 (HEIC 자동 변환, 영상은 video-scan 필요 안내)
  - **⛔ 중단** → Ctrl-C

## v0 가 아직 안 하는 것 (다음 단계)
- 온보딩 게이트(미설치/미로그인 시 설치·로그인 버튼) — 지금은 상태칩 표시만
- 버튼 시퀀싱(프롬프트 대기 후 다음 입력 자동 전송)
- 서명·공증된 설치 파일(.dmg/.exe) + 자동 업데이트 (배포 단계)
- 영상 드롭 시 `video-scan` 자동 트리거

## 구조
```
app/
  package.json
  src/
    main.js              # PTY(claude) 스폰, IPC, 드롭 적재, claude 경로 해석
    preload.js           # contextBridge (유일한 renderer<->main 통로)
    renderer/
      index.html         # 레이아웃 (터미널 + 버튼 레일)
      renderer.js        # xterm 바인딩, 버튼=PTY 주입, 드롭존
      styles.css
```
