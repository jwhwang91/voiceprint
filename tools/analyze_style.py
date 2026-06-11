"""수집된 글의 문체를 정량 분석(전수).

카테고리별로 어미 빈도, 추임새/이모지, 문장·문단 길이, 사진 배치 리듬,
자주 쓰는 단어/2-gram, 오프닝/클로징 패턴을 집계한다.
사용: python tools/analyze_style.py <blog_id>
"""
from __future__ import annotations

import glob
import json
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

ZW = "​"  # 제로폭 공백
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️❤]")

ENDINGS = ["습니다", "했어요", "됐어요", "좋았어요", "더라구요", "더라고요", "같아요",
           "거든요", "네요", "았어요", "었어요", "이에요", "예요", "겠어요", "드라구요",
           "구요", "답니다", "보세요", "어요", "아요"]
FILLERS = ["진짜", "정말", "너무", "완전", "확실히", "워낙", "특히", "개인적으로",
           "솔직", "ㅎㅎ", "ㅋㅋ", "딱"]
STOP = {"정말", "너무", "그리고", "있는", "있어요", "같아요", "저는", "저희", "조금",
        "약간", "이렇게", "그래서", "하지만", "정도", "느낌", "생각", "부분"}


def categorize(title: str) -> str:
    event = ["돌잔치", "돌케이크", "키즈", "놀이텐트", "홈키즈", "관람기", "놀이부대", "유아 키즈"]
    baby = ["로션", "샴푸", "이불", "물병", "패치", "이유식", "블랭킷", "플리스", "아기옷",
            "큐브", "보리차", "세탁기", "빕", "손수건", "직구", "아기샴푸"]
    if any(k in title for k in event):
        return "돌잔치키즈나들이"
    if any(k in title for k in baby):
        return "육아제품리뷰"
    return "맛집카페방문"


def analyze(name: str, docs: list[dict]) -> None:
    end_c, fill_c, emoji_c, words, bigrams = Counter(), Counter(), Counter(), Counter(), Counter()
    line_lens, tb_lens, between, collage, tagc = [], [], [], [], []
    first_img = 0
    openers, closers = [], []
    for d in docs:
        blocks = d["body_blocks"]
        tagc.append(len(d["tags"]))
        if blocks and blocks[0]["type"] == "image":
            first_img += 1
        txts = [b["text"] for b in blocks if b["type"] == "text" and b.get("text")]
        if txts:
            openers.append(txts[0].replace(ZW, "").strip().split("\n")[0][:42])
            closers.append(txts[-1].replace(ZW, "").strip().split("\n")[-1][:42])
        for t in txts:
            tb_lens.append(len(t))
            for ln in t.split("\n"):
                ln = ln.replace(ZW, "").strip()
                if not ln:
                    continue
                line_lens.append(len(ln))
                for e in ENDINGS:
                    if re.search(e + r"[.!~?]*$", ln):
                        end_c[e] += 1
                        break
            for f in FILLERS:
                fill_c[f] += t.count(f)
            for ch in t:
                if EMOJI.match(ch):
                    emoji_c[ch] += 1
            ws = re.findall(r"[가-힣]{2,}", t)
            words.update(ws)
            for i in range(len(ws) - 1):
                bigrams[ws[i] + " " + ws[i + 1]] += 1
        run = 0
        for b in blocks:
            if b["type"] == "image":
                between.append(run)
                run = 0
                if b.get("srcs"):
                    collage.append(len(b["srcs"]))
            elif b["type"] == "text":
                run += 1

    av = lambda x: round(st.mean(x), 1) if x else 0
    print("\n" + "=" * 64)
    print(f"[{name}]  글 {len(docs)}개")
    print(f"  사진으로 시작: {first_img}/{len(docs)}")
    print(f"  텍스트블록 평균 {av(tb_lens)}자 | 줄 평균 {av(line_lens)}자 | 사진 사이 텍스트블록 평균 {av(between)}개")
    print(f"  콜라주 묶음 크기: {dict(Counter(collage).most_common())}")
    print(f"  태그 평균 {av(tagc)}개")
    print(f"  어미 TOP10: {end_c.most_common(10)}")
    print(f"  추임새: {[(k, v) for k, v in fill_c.most_common() if v > 0]}")
    print(f"  이모지 TOP: {emoji_c.most_common(8)}")
    print(f"  자주쓰는 단어: {[w for w, c in words.most_common(40) if w not in STOP][:18]}")
    print(f"  자주쓰는 2-gram: {[b for b, c in bigrams.most_common(15) if c > 1]}")
    print("  오프닝 예:")
    for o in openers[:4]:
        print(f"    · {o}")
    print("  클로징 예:")
    for c in closers[:4]:
        print(f"    · {c}")


def main() -> int:
    blog_id = sys.argv[1] if len(sys.argv) > 1 else "cloudy43_"
    root = Path(__file__).resolve().parents[1]
    files = glob.glob(str(root / "data" / "collected" / blog_id / "*.json"))
    docs = [json.load(open(f, encoding="utf-8")) for f in files]
    buckets: dict[str, list] = defaultdict(list)
    for d in docs:
        buckets[categorize(d["title"])].append(d)
    print("분류:", {k: len(v) for k, v in buckets.items()})
    for name in ("맛집카페방문", "육아제품리뷰", "돌잔치키즈나들이"):
        if buckets[name]:
            analyze(name, buckets[name])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
