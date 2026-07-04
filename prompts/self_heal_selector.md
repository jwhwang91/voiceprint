# prompts/self_heal_selector.md — 셀렉터 자가치유 지시서 (Claude Code 전용)

네이버가 DOM(클래스 해시·버튼 구조)을 바꾸면 발행 셀렉터가 깨질 수 있다. 이때 **추측하지 말고
살아있는 DOM 을 실측**해서 새 셀렉터를 찾아 **패치 JSON** 으로 만들고, 그 패치를 적용한다.

> ⚠️ 이 흐름은 **소스 코드와 번들 기본값(`config/selectors.yaml`)을 절대 수정하지 않는다.**
> 새 셀렉터는 오직 `apply-selector-patch` 를 통해 **사용자 오버라이드**
> (`<workspace>/config/selectors.user.yaml`)에만 반영된다. 그래야 앱을 업데이트해도 사용자의
> 수정이 유지되고, 기본값은 안정적으로 남는다.

---

## 0. 언제 치유하는가 / 언제 멈추는가

- **셀렉터/DOM 오류일 때만** 치유한다. Playwright 오류는 보통 깨진 셀렉터를 직접 이름으로 알려준다.
- 다음은 **셀렉터 문제가 아니므로 치유하지 말고 즉시 멈추고 사용자에게 알린다**:
  - 로그인 필요 / 세션 만료 / 보안 추가 인증
  - **CAPTCHA**, 봇 차단, 비정상 접근 경고
  - 네트워크 오류, 파일 없음(사진/초고 누락), 타임아웃이 명백히 네트워크일 때
- ⛔ **CAPTCHA·로그인·보안 우회를 절대 시도하지 않는다.** 보이는 브라우저(앱의 네이버 화면)에서
  **사용자가 직접** 완료하도록 안내하고 대기한다.
- `inspect-dom --json` 의 건강검진에서 `any_miss: false`(모든 셀렉터 매칭)면 셀렉터 문제가 아니다 —
  그 사실을 근거로 다른 원인(네트워크/로그인/타이밍)을 보고한다.

---

## 1. 진단: 살아있는 DOM 을 JSON 으로 조회

발행은 앱 안 네이버 화면(WebContentsView)에서 CDP 로 동작하므로, 실패 직후 그 화면은 **깨진
에디터 상태 그대로** 떠 있다. 그 상태를 그대로 조회한다.

```bash
python main.py inspect-dom --json                 # write/login 건강검진(어느 셀렉터가 MISS 인지)
python main.py inspect-dom --json --text "발행"     # 보이는 텍스트로 후보 찾기(저장/제목 등도)
python main.py inspect-dom --json --list buttons    # 버튼 나열(+ 각 요소의 suggest 셀렉터)
python main.py inspect-dom --json --list editable    # contenteditable 나열(본문/제목)
python main.py inspect-dom --json --selector "<css>" # 후보 셀렉터 매칭 수/가시성 확인
python main.py inspect-dom --json --html "<css>"      # 첫 매칭 outerHTML(구조 파악)
```

(CLI 단독·앱 밖이면 `--editor` 를 붙여 먼저 글쓰기 화면으로 이동 — 로그인 세션 필요.)

JSON 필드: `status`(OK/MISS/AMBIGUOUS/ERROR), `matched`, `visible`, `elements[].suggest`,
`suggested_selectors`, `url`, `timestamp` 등. `[MISS]`/`status:"MISS"` 가 네이버가 바꾼 지점이다.

---

## 2. 새 셀렉터 고르기 — 견고함 우선순위

좋은 셀렉터는 빌드/해시 변동에 견딘다. 아래 순서로 선호한다:

1. **안정적인 `data-*` 속성** (예: `button[data-name="map"]`) — 해시 변동에 가장 강함.
2. **보이는 텍스트** (예: `:has-text("발행")`) / **aria-label**(예: `[aria-label="발행"]`).
3. **안정적인 role** (예: `[role="button"]` + 텍스트 조합).
4. **부분 클래스 매칭** — 정당할 때만(예: `[class*="publish_btn"]`). 네이버 클래스는
   `save_btn__m9KHH` 처럼 해시가 붙으므로 접두사만 부분일치(`[class*="save_btn"]`)로 잡는다.
   `inspect-dom` 이 제안하는 `suggest=` 값이 보통 이 형태다.

⛔ **너무 광범위한 셀렉터 금지**: `div`, `span`, `button`, `*`, `body` 같은 단독 태그/전역 셀렉터는
거부된다(오클릭·전역 매칭 위험). 반드시 **1개(또는 의도한 소수)만** 매칭하는지 `--selector` 로 확인한다.

---

## 3. 패치 JSON 만들기 — **오직 패치만 출력/저장**

새 셀렉터를 확정했으면 아래 스키마의 패치 파일을 만든다(예: `/tmp/patch.json`). 코드/기본 셀렉터를
직접 고치지 말고 **이 패치 JSON 만** 만든다.

```json
{
  "type": "selector_patch",
  "target": "write.publish_open_button",
  "old_selector": "[class*=\"publish_btn\"]",
  "new_selector": "[class*='publish_btn_v2']",
  "evidence": { "matched_count": 1, "visible": true, "text": "발행" },
  "confidence": 0.92,
  "reason": "기본 셀렉터 MISS; 라이브 DOM 에서 견고한 부분 클래스 매칭 확인"
}
```

- `target` 은 `config/selectors.yaml` 의 점 표기 키(예: `write.title_area`, `write.save_draft_button`).
- `evidence` 는 `inspect-dom --json` 에서 실측한 근거(매칭 수·가시성·텍스트)를 넣는다.
- `confidence` 는 0~1. 근거가 약하면 낮춘다.

---

## 4. 검증 → 적용 → 재확인 → 재시도

```bash
# (선택) 스키마/안전성 + 라이브 DOM 검증만:
python main.py validate-selector-patch --patch /tmp/patch.json --verify

# 적용: 사용자 오버라이드(selectors.user.yaml)에만 기록 + healing-history.jsonl 로깅.
#   앱 모드(CDP)면 적용 전 라이브 DOM 으로 new_selector 매칭을 자동 확인한다.
python main.py apply-selector-patch --patch /tmp/patch.json

# 재확인: 방금 고친 셀렉터가 이제 OK 인지.
python main.py inspect-dom --json
```

- 적용이 `applied: true` 면 발행을 **다시 시도**한다(`python main.py publish --job "<job>" --yes`).
- ⭐ **발행 시도는 한 번의 자가치유 사이클에서 총 3회를 넘기지 않는다.** 3회 후에도 실패하면
  멈추고 아래를 보고한다.

---

## 5. 3회 후에도 실패하면 — 명확히 보고하고 멈춤

다음을 사용자에게 보고한다(추가 시도 금지):
- 어떤 셀렉터(`target`)가 여전히 실패하는지
- 시도한 패치들(old → new, confidence)
- `inspect-dom --json` 요약(어떤 게 MISS/AMBIGUOUS 인지)
- 추정 원인(셀렉터/로그인/CAPTCHA/네트워크 중 무엇으로 보이는지)
- 사용자가 직접 해야 할 일(예: 네이버 화면에서 로그인/캡차 완료, 또는 개발자 점검 요청)

이력은 `<workspace>/logs/healing-history.jsonl` 에 자동 누적되므로, 반복되는 셀렉터는 그 로그로
추적할 수 있다.
