# 지시서: 자동 답방 댓글 생성 (Claude Code 수행)

## 목표
답방 대상 글들의 내용에 맞는 **자연스럽고 진심 어린 댓글**을 생성한다.
기계적·복붙 느낌이 나면 안 된다(스팸/제재 위험). 각 글마다 내용에 근거해 다르게.

## 입력
- `data/engage/<job>/targets.json` — `{ my_post, targets: [{blog_id, nickname, log_no, url, title, body_excerpt, their_comment}] }`

## 절차
1. `targets.json` 의 각 target 에 대해 `title` 과 `body_excerpt` 를 읽는다.
2. 글 내용에서 **구체적 디테일 1가지**를 짚어 댓글에 녹인다(예: 특정 메뉴/장소/아기 제품 언급).
3. 블로그 주인의 말투에 호응하는 **따뜻한 존댓말**로, 1~2문장(약 20~60자).
   - 예: "OO 비주얼 너무 좋네요! 저도 다음에 꼭 가봐야겠어요 😊"
4. 과한 홍보·링크·이모지 남발 금지. 진짜 이웃이 남길 법한 톤.
5. `their_comment`(그 사람이 내 글에 남긴 댓글)가 있으면 자연스럽게 화답하는 뉘앙스도 좋다.

## 출력
`data/engage/<job>/comments.json`:
```json
{
  "comments": [
    {"blog_id":"...", "log_no":"...", "url":"...", "nickname":"...", "comment":"생성한 댓글"}
  ]
}
```
- targets 의 각 글에 1개씩. url/blog_id/log_no/nickname 은 targets 값을 그대로 옮긴다.

## 체크리스트
- [ ] 댓글마다 글 내용의 구체 디테일이 들어갔는가(복붙 아님)
- [ ] 1~2문장, 자연스러운 존댓말인가
- [ ] 광고/링크/과한 이모지 없는가
