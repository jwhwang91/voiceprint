# 셀렉터 자가치유(Selector Self-Healing)

네이버 에디터/블로그 UI는 예고 없이 바뀐다. 이 문서는 **발행(publish)이 셀렉터 때문에 실패했을 때**,
사람이 코드를 고치지 않고도 자동으로 회복하는 **자가치유(self-healing)** 구조와 절차를 설명한다.

이 프로젝트는 API SaaS가 아니라 **로컬 데스크톱 도구**다. 기계적인 작업(브라우저 자동화, DOM 조사)은
Python(Playwright)이, 인지적인 작업(바뀐 DOM을 보고 올바른 새 셀렉터를 고르는 판단)은 **사용자의 Claude
Code CLI**가 맡는다. Python은 절대 Claude를 호출하지 않는다. 자가치유의 "판단" 부분은
`prompts/self_heal_selector.md` 와 `/blog-run` 스킬(`.claude/commands/blog-run.md`)이 이끈다.

---

## 1) 셀렉터는 왜 깨지는가

네이버 스마트에디터/블로그 화면은 빌드할 때마다 **클래스 이름에 해시가 붙는다**
(예: `se-l-text_3aB9x` 처럼). 또한 버튼/패널의 **DOM 구조 자체가 개편**되기도 한다. 우리가
`config/selectors.yaml` 에 박아 둔 CSS 셀렉터가 어느 날 갑자기 아무 요소도 못 잡으면(`MISS`),
발행 자동화가 그 단계에서 멈춘다. 이런 변경은 우리 통제 밖에서 일어나므로, 코드를 매번 손보는 대신
**셀렉터만 런타임에 갈아끼우는** 회복 경로가 필요하다.

핵심 원칙: **깨지는 것은 셀렉터(설정값)지, 로직(코드)이 아니다.** 그래서 치유도 설정값만 바꾼다.

---

## 2) 번들 기본 셀렉터 vs 사용자 오버라이드

셀렉터는 두 층으로 관리된다.

### 번들 기본값 — `config/selectors.yaml`
- 저장소에 포함되어 배포되는 **안정적인 기본 셀렉터** 모음.
- **자가치유는 이 파일을 절대 수정하지 않는다.** 앱 업데이트가 와도 깨끗하게 갈린다.

### 사용자 런타임 오버라이드 — `<ws>/config/selectors.user.yaml`
- 워크스페이스(`<ws>`) 아래에 있는 **사용자 전용 오버라이드** 파일.
- 로드 시 기본값 위에 **딥 머지(deep-merge)** 된다. 즉 같은 키가 있으면 오버라이드가 이긴다.
- **자가치유가 쓰는 곳은 오직 이 파일 하나다.**
- 이 파일이 없거나 깨져 있어도 **발행은 멈추지 않는다.** 경고만 찍고 기본값으로 폴백한다.

> 워크스페이스(`<ws>`)는 런타임 데이터 루트다. 개발(데브) 모드에서는 저장소의 `data/` 가 루트가 되고,
> 앱/워크스페이스 모드에서는 사용자가 고른 폴더가 루트가 된다. 앱은 PTY 환경에 `VOICEPRINT_WORKSPACE`
> 를 주입하므로, 앱 안에서 Claude가 돌리는 명령은 `--workspace` 없이도 알아서 올바른 워크스페이스로
> 해석된다.

### 값 형식: old-string vs new-dict
오버라이드 값은 **두 가지 형식**을 모두 지원한다.

- **old 문자열 형식** — 그냥 셀렉터 문자열:
  ```yaml
  write:
    publish_open_button: "button:has-text('발행')"
  ```
- **new 딕셔너리 형식** — 메타데이터를 함께 보관(치유가 기록을 남기기 좋다):
  ```yaml
  write:
    publish_open_button:
      selector: "[class*='publish_btn']"
      updated_at: "2026-06-30T12:00:00Z"
      reason: "네이버가 발행 버튼 클래스 해시를 변경함"
      confidence: 0.91
      source: "self-heal"
  ```

`load_selectors()` 가 로드 시점에 **모든 값을 문자열로 평탄화(flatten)** 한다. 그래서 dict 형식으로
적어 두어도 **기존 소비 코드는 한 줄도 바꿀 필요가 없다(zero consumer changes).** 코드에서 셀렉터를
꺼낼 때는 헬퍼를 쓴다:

```python
get_selector(sel, "write.publish_open_button")
```

---

## 3) 셀렉터 패치 JSON 스키마와 규칙

치유는 "이 키를, 이 옛 셀렉터에서, 이 새 셀렉터로 바꿔라"는 **패치(patch)** 단위로 진행한다.
패치는 JSON 파일이며 스키마는 다음과 같다(아래가 정확한 예시다):

```json
{
  "type": "selector_patch",
  "target": "write.publish_open_button",
  "old_selector": "...",
  "new_selector": "[class*='publish_btn']",
  "evidence": { "matched_count": 1, "visible": true, "text": "발행" },
  "confidence": 0.91,
  "reason": "..."
}
```

### 좋은 셀렉터 규칙(robust 우선)
새 셀렉터는 **바뀌어도 잘 안 깨지는** 것을 골라야 한다. 우선순위:

1. **안정적인 `data-*` 속성** (예: `button[data-name="map"]`) — 가장 선호.
2. **눈에 보이는 텍스트** (예: `:has-text('발행')`).
3. **`aria-label`** 등 접근성 속성.
4. **부분 클래스 매칭** (예: `[class*='publish_btn']`) — **정당한 근거가 있을 때만**.
   해시 부분이 아니라 의미가 있는 클래스 조각을 골라야 한다.

### 거부되는 셀렉터(too-broad)
`div`, `button`, `*` 같은 **맨몸 태그/와일드카드**처럼 너무 광범위한 셀렉터는 **거부된다.**
여러 요소를 한꺼번에 잡아 엉뚱한 클릭을 유발하기 때문이다. 빈 셀렉터도 거부된다.

---

## 4) 명령어

자가치유에 쓰는 Python 명령은 모두 `python main.py <cmd>` 형태다(데브 모드에선 사용자가, 앱 안에서는
Claude의 셸이 실행). 전역 플래그 `--workspace <path>` 는 서브커맨드 앞에 붙일 수 있다.

### `inspect-dom` — 살아있는 DOM 조사
지금 화면의 DOM에서 셀렉터가 잡히는지, 무엇이 있는지 구조적으로 들여다본다.

```bash
python main.py inspect-dom --selector "button:has-text('발행')" --json
```

`--json` 은 구조화된 JSON을 출력한다: `status`(`OK`/`MISS`/`AMBIGUOUS`/`ERROR`), `matched`, `visible`,
`suggested_selectors`, `elements`, `url`, `timestamp` 등. 자가치유 판단은 이 JSON을 근거로 한다.

주요 변형:

```bash
python main.py inspect-dom --text "발행"                 # 텍스트로 요소 찾기
python main.py inspect-dom --list buttons                # buttons|inputs|editable|links|interactive 나열
python main.py inspect-dom --selector "[class*='publish_btn']"  # 특정 CSS 확인
python main.py inspect-dom --html "div.header"           # 해당 요소의 HTML 덤프
```

그 밖에 `--section <name>`, `--editor`, `--goto <url>`, `--blog-id <id>` 옵션도 있다.

### `validate-selector-patch` — 패치 검증(쓰지 않음)
패치 JSON이 스키마에 맞는지, 너무 광범위하지 않은지 검사한다. `--verify` 를 주면 새 셀렉터가
실제 살아있는 DOM과 맞는지까지 확인한다. **파일을 바꾸지는 않는다.**

```bash
python main.py validate-selector-patch --patch patch.json --verify
```

### `apply-selector-patch` — 패치 적용(쓰기)
스키마를 검증하고, 너무 광범위/빈 셀렉터를 거부하고, (앱 모드/`--verify` 시) 새 셀렉터가 실제 DOM과
매칭되는지 확인한 뒤 — **오직 `<ws>/config/selectors.user.yaml` 에만** 기록하고,
**`<ws>/logs/healing-history.jsonl` 에 로그를 남긴다.** `config/selectors.yaml` 이나 소스 코드는
**절대 건드리지 않는다.**

```bash
python main.py apply-selector-patch --patch patch.json --verify
# --no-verify 로 라이브 DOM 확인을 건너뛸 수 있다(권장하지 않음)
```

---

## 5) 자가치유 FLOW (단계별)

발행이 셀렉터 때문에 실패했을 때, Claude는 `prompts/self_heal_selector.md` 와 `/blog-run` 스킬을 따라
다음 루프를 돈다.

1. **발행 시도** — `python main.py publish --job <job>` 가 어떤 셀렉터 단계에서 실패한다.
2. **DOM 조사** — 실패한 셀렉터 키를 `inspect-dom --json` 으로 살핀다.
   `status: MISS` 라면 그 셀렉터가 지금 화면에 없다는 뜻이다.
3. **대체 셀렉터 탐색** — `--text` / `--list` / `--html` / `suggested_selectors` 를 활용해
   같은 기능을 하는 요소의 **robust한 새 셀렉터**(§3 규칙)를 찾는다.
4. **패치 JSON 작성** — `selector_patch` 스키마(§3)로 `target`/`old_selector`/`new_selector`/
   `evidence`/`confidence`/`reason` 을 채운다.
5. **검증** — `validate-selector-patch --patch ... --verify` 로 스키마/광범위성/라이브 매칭을 확인한다.
6. **적용** — `apply-selector-patch --patch ... --verify` 로 `selectors.user.yaml` 에 쓰고
   `healing-history.jsonl` 에 기록한다.
7. **재조사로 확인** — `inspect-dom --json` 으로 새 셀렉터가 `OK` 인지 다시 확인한다.
8. **발행 재시도** — 다시 `publish` 를 돌린다.

이 루프는 **발행 시도 총 3회로 제한된다(MAX 3 publish attempts).** 3회 안에 못 고치면 멈추고
사용자에게 상황을 알린다. 무한 반복으로 계정을 위험에 빠뜨리지 않기 위한 안전장치다.

> 참고: `publish` 는 **설계상 임시저장(temp-save)까지만** 한다. 최종 **발행** 버튼은 사용자가 네이버에서
> 직접 누른다. 자가치유가 성공해도 "글이 자동 발행됐다"고 말하면 안 된다.

---

## 6) `healing-history.jsonl` 형식

적용된 패치마다 `<ws>/logs/healing-history.jsonl` 에 **JSON 한 줄(JSON Lines)** 이 추가된다.
한 줄은 하나의 적용 기록이며, 다음 필드를 담는다:

```json
{"timestamp":"2026-06-30T12:00:00Z","target":"write.publish_open_button","old":"button:has-text('발행')","new":"[class*='publish_btn']","confidence":0.91,"reason":"네이버가 발행 버튼 클래스 해시를 변경함","verified":true}
```

- `timestamp` — 적용 시각
- `target` — 바꾼 셀렉터 키
- `old` / `new` — 옛 셀렉터 / 새 셀렉터
- `confidence` — 신뢰도
- `reason` — 바꾼 이유
- `verified` — 라이브 DOM 매칭 확인 여부

이 로그로 "언제 무엇이 왜 바뀌었는지"를 추적할 수 있다.

---

## 7) HARD-FAIL — 치유를 멈추고 사용자에게 넘겨야 하는 경우

다음은 **셀렉터 한 줄을 바꿔서 풀 문제가 아니다.** 자가치유를 **즉시 중단**하고, 사용자가
**눈에 보이는 브라우저에서 직접 처리**하도록 안내한다.

- **CAPTCHA** (캡차)
- **로그인 / 로그인 보안 절차**
- **안티봇·자동화 차단(security challenge)**
- **에디터 대규모 개편** — 단일 셀렉터 교체로 해결되지 않는 구조적 변경

⚠️ **CAPTCHA와 로그인 보안은 절대 우회하지 않는다.** 캡차 풀이 자동화, 로그인 우회 같은 행위는
하지 않는다. 이런 상황에서는 앱의 `🌐 네이버 보기` / `네이버 로그인(1회)` 를 통해 사용자가 직접
해결하게 한다.

---

## 8) 코어 파일을 건드리지 않는 이유

자가치유는 **`config/selectors.yaml`(번들 기본값)과 소스 코드를 절대 수정하지 않는다.** 이유는 두 가지다.

1. **앱 업데이트가 깨끗하게 유지된다.** 새 버전 ZIP을 받아도 기본 셀렉터와 코드는 그대로 갈리고,
   머지 충돌이나 덮어쓰기 걱정이 없다.
2. **사용자 패치가 보존된다.** 치유 결과는 워크스페이스의 `selectors.user.yaml` 에만 쌓이므로,
   업데이트와 무관하게 살아남고 딥 머지로 계속 적용된다. (배포 패키징도 `selectors.user.yaml` 과
   `healing-history.jsonl` 을 제외하므로, 사용자별 패치가 배포본에 섞이지 않는다.)

즉, **기본값은 안정적으로 배포하고, 변화는 사용자 오버라이드 층에만 흡수한다** — 이것이 자가치유
설계의 핵심이다.

---

## 관련 파일

- `prompts/self_heal_selector.md` — 자가치유 판단 프롬프트(이 절차의 "두뇌")
- `.claude/commands/blog-run.md` — `/blog-run` 스킬: 자가치유를 포함한 발행 러너
- `config/selectors.yaml` — 번들 기본 셀렉터(치유가 수정하지 않음)
- `<ws>/config/selectors.user.yaml` — 사용자 오버라이드(치유가 쓰는 유일한 셀렉터 파일)
- `<ws>/logs/healing-history.jsonl` — 적용된 패치 이력
