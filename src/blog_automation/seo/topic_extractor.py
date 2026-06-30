"""입력 콘텐츠(사진 태그·메모·폴더명)에서 SEO 주제/카테고리/검색 의도를 추출한다.

Claude 가 이미 만들어 둔 산출물을 소비한다:
  - drafts/<job>/photo_tags.json : 비전 태그(photos[].category/subject/group_key)
  - input/<job>/**              : 사용자 메모(텍스트)를 **재귀로** 찾는다. 이름/위치가
                                  description.txt 가 아니어도(예: photos/모리몰리) 찾아낸다.
  - input/<job>/photos/*         : 카테고리 하위폴더 이름(카테고리 힌트)

⭐ 핵심 원칙: **날조 금지**. 사진/메모에서 확인되지 않는 지역·상호·제품명은 비워 둔다(None).
   파일이 일부/전부 없어도 죽지 않고 가능한 만큼만 채운 TopicExtraction 을 돌려준다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..logging_setup import get_logger
from ..utils.files import read_json
from . import constants
from .models import TopicExtraction

log = get_logger()

# ───────────────────────── 휴리스틱 사전(키워드 매칭용) ─────────────────────────

# 카테고리별 content_type 기본값
_CONTENT_TYPE_BY_CATEGORY: dict[str, str] = {
    "맛집": "방문 후기",
    "여행": "방문 후기",
    "육아템": "제품 리뷰",
    "육아": "일상",
    "일상": "일상",
}

# 카테고리별 현실적인 검색 의도(3~5개). 키워드가 아니라 '왜 검색하는가' 관점.
_TARGET_INTENTS_BY_CATEGORY: dict[str, list[str]] = {
    "맛집": ["메뉴·가격 확인", "분위기·내부 사진", "주차·웨이팅 정보", "예약 가능 여부", "추천 메뉴"],
    "여행": ["코스·동선 계획", "숙소·주차 정보", "아이랑 가기 좋은지", "실내/우천 대비", "주변 가볼만한곳"],
    "육아템": ["실사용 후기", "장단점·단점 확인", "가격·가성비", "세척·관리 편의", "또래 사용 적합성"],
    "육아": ["월령별 정보", "준비물 체크", "외출·여행 팁", "수면·놀이 노하우", "병원·어린이집"],
    "일상": ["일상 기록", "추천·공유", "장소·분위기"],
}

# 주차 근거 신호(메모/카테고리/subject)
_PARKING_WORDS = ("주차", "발렛", "발레파킹", "parking", "주차장")

# 데이트/분위기 신호(2인·와인·분위기 등)
_DATE_WORDS = (
    "데이트", "분위기", "와인", "wine", "2인", "둘이", "연인", "기념일", "감성",
    "무드", "야경", "루프탑", "칵테일", "위스키",
)

# 아이/육아 맥락 신호.
# ⚠️ '돌'·'개월' 같은 짧은 토큰은 단독 부분일치 시 오탐(테이블·오동통 등)이 많아 제외하고,
#    나이대(돌아기/N개월)는 _AGE_PATTERNS 로 따로 잡는다(= age_group 있으면 kid 맥락).
_KID_WORDS = (
    "아이", "아기", "유모차", "키즈", "kids", "아가", "신생아",
    "이유식", "아이랑", "아기랑", "노키즈", "어린이", "돌아기", "돌잔치",
)

# 음식 카테고리(맛집 판별 보조) — 사진 카테고리에 흔히 등장
_FOOD_CATEGORY_HINTS = (
    "메뉴음식", "음식", "메뉴", "메뉴판", "음료", "디저트", "안주", "먹태",
)
# 맛집 외관/내부 카테고리(방문형 판별 보조)
_VENUE_CATEGORY_HINTS = ("외관", "내부", "매장", "전경", "입구")

# 제품 리뷰(육아템) 강신호 — '후기'처럼 맛집에도 흔한 약신호는 제외(오탐 방지).
_STRONG_PRODUCT_SIGNALS = (
    "내돈내산", "장단점", "언박싱", "사용후기", "리뷰", "추천템", "육아템",
    "제품", "구매", "비교", "협찬", "체험단",
)
# 아이/육아 맥락 신호(카테고리 판별 보조)
_KID_SIGNALS = ("아기", "아이", "돌아기", "개월", "이유식", "유아", "육아", "신생아", "수유")

# 나이대(육아) 패턴: '6개월', '돌아기', '신생아', '24개월' 등
_AGE_PATTERNS = [
    re.compile(r"(신생아)"),
    re.compile(r"(\d{1,2}\s*개월)"),
    re.compile(r"(\d{1,2}\s*살)"),
    re.compile(r"(돌\s*아기|돌아기|두\s*돌|세\s*돌)"),
    re.compile(r"(\d{1,2}\s*세)"),
]

# 한글 명사 토큰(아주 짧은 조사/숫자 제거용) — detected_topics 보정
_HANGUL_TOKEN = re.compile(r"[가-힣A-Za-z0-9]+")

# 알려진 지역/상권 토큰(지역 추출 + 상호 추출에서 '지역은 상호 아님' 판별에 공용). 보수적으로.
_KNOWN_LOCATIONS = [
    "성수", "연남", "연희", "망원", "합정", "홍대", "이태원", "한남", "압구정",
    "청담", "신사", "가로수길", "강남", "역삼", "삼성", "잠실", "송파", "여의도",
    "광화문", "종로", "을지로", "명동", "용산", "마포", "서촌", "북촌", "익선동",
    "문래", "영등포", "건대", "성수동", "뚝섬", "서울숲", "판교", "분당", "수원",
    "인천", "부산", "해운대", "광안리", "전주", "강릉", "속초", "제주", "대구",
    "대전", "광주", "경주", "여수", "춘천", "가평", "양양", "포항", "거제",
]

# 상호로 보기엔 의미 없는 일반어(폴더명에서 상호 추출 시 제외).
_STORE_STOPWORDS = {
    "맛집", "카페", "후기", "리뷰", "방문", "사진", "음식", "메뉴", "데이트",
    "외식", "점심", "저녁", "브런치", "디저트", "주차", "예약", "웨이팅",
}

# 토픽으로는 의미 없는 카테고리/일반어(제외)
_STOPWORD_TOPICS = {
    "기타", "디테일", "정보", "인물상황", "내부", "외관", "사진", "이미지",
    "그리고", "약간", "느낌", "정도", "여기", "거기", "우리", "오늘", "이번",
}


# ───────────────────────── 공개 헬퍼 ─────────────────────────

def load_photo_tags(path: Path) -> list[dict]:
    """photo_tags.json 의 photos 리스트를 안전하게 읽어 반환(없으면 빈 리스트).

    파일 없음/깨진 JSON/스키마 불일치 모두 graceful — 경고 로그 후 [] 반환.
    """
    try:
        if not path or not Path(path).is_file():
            return []
        data: Any = read_json(Path(path))
    except Exception as exc:  # noqa: BLE001
        log.warning("[topic_extractor] photo_tags 읽기 실패(%s): %s", path, exc)
        return []
    # data 가 {"photos": [...]} 형태이거나(정상) 곧장 리스트일 수도 있다.
    if isinstance(data, dict):
        photos = data.get("photos", [])
    elif isinstance(data, list):
        photos = data
    else:
        photos = []
    return [p for p in photos if isinstance(p, dict)]


def extract_topics(
    growth_cfg: Any,
    *,
    job: str,
    input_dir: Path,
    drafts_dir: Path,
    category_hint: str | None = None,
) -> TopicExtraction:
    """입력 폴더(사진 태그·메모·하위폴더)에서 TopicExtraction 을 추출한다.

    파일이 일부/전부 없어도 죽지 않는다(비전 단독·메모 누락 모드 대응).
    """
    input_dir = Path(input_dir)
    drafts_dir = Path(drafts_dir)

    # ── 1) 원천 데이터 수집(전부 graceful) ──
    photos = load_photo_tags(drafts_dir / job / "photo_tags.json")
    memo = _find_memo(input_dir / job)
    folder_names = _list_photo_subfolders(input_dir / job / "photos")

    photo_categories = [str(p.get("category", "")).strip() for p in photos if p.get("category")]
    subjects = [str(p.get("subject", "")).strip() for p in photos if p.get("subject")]

    # 매칭에 쓸 통합 텍스트(메모 + subject + 폴더명). 카테고리/폴더는 힌트.
    blob = " ".join([memo] + subjects + folder_names + photo_categories)

    # ── 2) 카테고리 추론 ──
    category = _infer_category(
        category_hint=category_hint,
        folder_names=folder_names,
        photo_categories=photo_categories,
        memo=memo,
    )

    # ── 3) 플래그 ──
    has_parking_evidence = _contains_any(blob, _PARKING_WORDS) or _category_hits(
        photo_categories + folder_names, _PARKING_WORDS
    )
    has_date_mood = _contains_any(blob, _DATE_WORDS)

    is_product_review = (category == "육아템") or _contains_any(
        blob, constants.PRODUCT_SIGNAL_WORDS
    )

    # ── 4) 세부 필드 ──
    age_group = _extract_age_group(blob)
    # 나이대(돌아기/N개월)가 잡히거나 명시 키워드가 있으면 아이 맥락으로 본다.
    has_kid_context = bool(age_group) or _contains_any(blob, _KID_WORDS) or category in ("육아", "육아템")
    location = _extract_location(category=category, memo=memo, job=job)
    product_type, brand = _extract_product_and_brand(
        category=category, memo=memo, subjects=subjects, job=job
    )
    # ⭐ 맛집/여행은 '상호(가게명)'가 1순위 검색어다. 육아템 제품 추출과 별개로,
    #    job 폴더명·메모·subject 에서 상호를 뽑아 brand 에 채운다(없던 핵심 키워드 복구).
    store_name = _extract_store_name(category=category, memo=memo, subjects=subjects, job=job)
    if store_name and not brand:
        brand = store_name
    content_type = _CONTENT_TYPE_BY_CATEGORY.get(category, "일상")
    target_intents = list(_TARGET_INTENTS_BY_CATEGORY.get(category, _TARGET_INTENTS_BY_CATEGORY["일상"]))

    detected_topics = _detect_topics(
        subjects=subjects,
        memo=memo,
        folder_names=folder_names,
        location=location,
        product_type=product_type,
        brand=brand,
    )

    extra: dict[str, Any] = {
        "photo_count": len(photos),
        "photo_categories": _dedup_keep_order(photo_categories),
        "folder_names": folder_names,
        "has_memo": bool(memo),
    }
    if store_name:
        extra["상호"] = store_name

    topic = TopicExtraction(
        input_folder=job,
        category=category,
        detected_topics=detected_topics,
        location=location,
        product_type=product_type,
        brand=brand,
        age_group=age_group,
        content_type=content_type,
        target_intents=target_intents,
        is_product_review=is_product_review,
        has_parking_evidence=has_parking_evidence,
        has_date_mood=has_date_mood,
        has_kid_context=has_kid_context,
        extra=extra,
    )
    log.info(
        "[topic_extractor] job=%s cat=%s loc=%s product=%s topics=%d "
        "(review=%s parking=%s date=%s kid=%s)",
        job, category, location, product_type, len(detected_topics),
        is_product_review, has_parking_evidence, has_date_mood, has_kid_context,
    )
    return topic


# ───────────────────────── 내부 헬퍼: 원천 데이터 ─────────────────────────

# 메모로 보지 않을 미디어/이진/생성물 확장자(재귀 탐색 시 건너뜀).
_NON_MEMO_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".bmp", ".tiff",
    ".mov", ".mp4", ".m4v", ".avi", ".mkv", ".webm",
    ".json", ".zip", ".pdf", ".heif", ".ds_store",
}
# 메모 파일 1개 최대 크기(엉뚱한 큰 파일을 메모로 빨아들이지 않게).
_MEMO_MAX_BYTES = 200_000


def _read_memo(path: Path) -> str:
    """단일 텍스트 파일을 UTF-8 로 읽는다(못 읽으면 빈 문자열)."""
    try:
        raw = Path(path).read_bytes()
    except Exception:  # noqa: BLE001
        return ""
    if not raw or b"\x00" in raw or len(raw) > _MEMO_MAX_BYTES:
        return ""  # 빈/이진/과대 파일은 메모 아님
    try:
        return raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return ""


def _find_memo(job_dir: Path) -> str:
    """job 폴더 **전체를 재귀**로 뒤져 사용자 메모(텍스트)를 찾는다.

    예전엔 `<job>/description.txt` 한 곳만 봤다. 그런데 드롭으로 들어온 폴더에서는
    메모가 `photos/모리몰리`(확장자 없음·photos 하위)처럼 엉뚱한 이름·위치에 묻혀
    들어오기 일쑤라, 멀쩡히 존재하는 메모를 통째로 놓치고 '비전 단독'으로 빠졌다
    (→ 위치·상호를 못 뽑아 키워드가 쓰레기가 됨).

    개선: job 폴더 아래 모든 텍스트 파일을 찾아 우선순위대로 합친다.
      ① description.txt(있으면 최우선)  ② 그 외 .txt/.md  ③ 확장자 없는 UTF-8 텍스트
    `.`/`_` 로 시작하는 파일·폴더(.DS_Store, _gifs 등)와 미디어/이진/생성물은 제외.
    확장자 없는 파일은 실제 UTF-8 로 디코드될 때만 메모로 인정(이미지 오인 방지).
    """
    job_dir = Path(job_dir)
    if not job_dir.is_dir():
        return ""

    desc_txt: list[tuple[Path, str]] = []   # ① description.txt
    txt_md: list[tuple[Path, str]] = []     # ② 기타 .txt/.md
    extless: list[tuple[Path, str]] = []    # ③ 확장자 없는 텍스트

    for p in sorted(job_dir.rglob("*")):
        if not p.is_file():
            continue
        # 숨김/언더스코어/__MACOSX 경로 제외(경로 어디든 한 segment 라도 걸리면 skip).
        if any(seg.startswith(".") or seg.startswith("_") or seg == "__MACOSX"
               for seg in p.relative_to(job_dir).parts):
            continue
        ext = p.suffix.lower()
        if ext in _NON_MEMO_EXTS:
            continue
        text = _read_memo(p)
        if not text:
            continue
        if p.name.lower() == "description.txt":
            desc_txt.append((p, text))
        elif ext in (".txt", ".md"):
            txt_md.append((p, text))
        elif ext == "":
            extless.append((p, text))
        # 그 외 알 수 없는 확장자는 보수적으로 무시(오탐 방지).

    chosen = desc_txt + txt_md + extless
    if not chosen:
        return ""
    for p, _ in chosen:
        log.info("[topic_extractor] 메모 발견: %s", p)
    # 여러 개면 우선순위 순서로 합쳐 아무 메모도 잃지 않는다.
    return "\n\n".join(t for _, t in chosen).strip()


def _list_photo_subfolders(photos_dir: Path) -> list[str]:
    """photos/ 바로 아래 하위폴더 이름들(카테고리 힌트). 없으면 빈 리스트."""
    try:
        p = Path(photos_dir)
        if not p.is_dir():
            return []
        names = [c.name for c in p.iterdir() if c.is_dir() and not c.name.startswith("_")]
        return _dedup_keep_order([n.strip() for n in names if n.strip()])
    except Exception as exc:  # noqa: BLE001
        log.warning("[topic_extractor] photos 하위폴더 조회 실패(%s): %s", photos_dir, exc)
        return []


# ───────────────────────── 내부 헬퍼: 추론 ─────────────────────────

def _infer_category(
    *,
    category_hint: str | None,
    folder_names: list[str],
    photo_categories: list[str],
    memo: str,
) -> str:
    """CATEGORY_ALIASES + 휴리스틱으로 SEO 정규 카테고리를 추론.

    우선순위(중요):
      ① 명시적 힌트 → ② 음식 사진(맛집) → ③ 제품리뷰 강신호+아이맥락(육아템) →
      ④ 별칭 점수(단, '육아'가 이겨도 제품 강신호 있으면 '육아템'으로 보정) →
      ⑤ 외관/내부만(여행) → ⑥ 기타.
    """
    # 1) 명시적 힌트 우선(별칭 매칭).
    if category_hint:
        cat = _alias_match(category_hint)
        if cat:
            return cat

    joined = " ".join(folder_names + photo_categories + [memo or ""])
    has_food = _category_hits(photo_categories + folder_names, _FOOD_CATEGORY_HINTS)
    has_venue = _category_hits(photo_categories + folder_names, _VENUE_CATEGORY_HINTS)
    strong_product = _contains_any(joined, _STRONG_PRODUCT_SIGNALS)
    kid_signal = _contains_any(joined, _KID_SIGNALS)

    # 2) 음식 사진이 핵심이면 방문형(맛집) 우선 — 아이/제품 단어가 섞여도 맛집.
    if has_food:
        return "맛집"

    # 3) 제품 리뷰 강신호 + 아이 맥락이면 '육아' 가 아니라 '육아템'(제품 리뷰).
    if strong_product and kid_signal:
        return "육아템"

    # 4) 폴더명/사진 카테고리/메모 단어를 별칭과 대조(가장 많이 맞는 카테고리 선택).
    haystack = folder_names + photo_categories + _tokens(memo)
    scores: dict[str, int] = {}
    for cat, aliases in constants.CATEGORY_ALIASES.items():
        hits = sum(1 for token in haystack for a in aliases if a and a in token)
        if hits:
            scores[cat] = scores.get(cat, 0) + hits
    if scores:
        winner = max(scores, key=lambda k: scores[k])
        # '육아' 로 분류됐지만 제품 강신호가 있으면 '육아템' 으로 보정.
        if winner == "육아" and strong_product:
            return "육아템"
        return winner

    # 5) 외관/내부만 있고 음식이 없으면 여행/장소 방문일 가능성.
    if has_venue:
        return "여행"

    return "기타"


def _alias_match(text: str) -> str | None:
    """텍스트 1개가 어떤 정규 카테고리의 별칭과 맞는지."""
    t = (text or "").strip()
    if not t:
        return None
    # 정확 카테고리명이면 그대로.
    if t in constants.CATEGORY_ALIASES:
        return t
    for cat, aliases in constants.CATEGORY_ALIASES.items():
        for a in aliases:
            if a and (a == t or a in t):
                return cat
    return None


def _extract_age_group(blob: str) -> str | None:
    """메모/subject 에서 나이대(신생아/N개월/돌아기 등) 추출. 없으면 None(날조 금지)."""
    for pat in _AGE_PATTERNS:
        m = pat.search(blob or "")
        if m:
            return re.sub(r"\s+", "", m.group(1))
    return None


def _extract_location(*, category: str, memo: str, job: str) -> str | None:
    """맛집/여행에 한해 지역을 추출. **명시적일 때만** — 모호하면 None.

    우선순위:
      1) 메모에 '<지역>에/은/는/맛집/위치한' 식으로 명시된 한국 지명.
      2) job 폴더명에 들어간 알려진 지역 토큰(예: '0624 바오 서울' → '서울').
    확신이 없으면 None 을 돌려준다(엉뚱한 지점 날조 방지).
    """
    if category not in ("맛집", "여행"):
        return None

    known = _KNOWN_LOCATIONS

    # 1) 메모 우선(가장 신뢰도 높음).
    if memo:
        for loc in known:
            # '성수에', '성수동', '성수 맛집' 등 자연스러운 등장만 인정.
            if re.search(rf"{re.escape(loc)}(?:에|은|는|동|역|쪽|에서|\s|맛집|$)", memo):
                return loc

    # 2) job 폴더명(예: '0624 바오 서울'): 명시된 지역 토큰만.
    for token in _tokens(job):
        if token in known:
            return token

    return None


def _extract_store_name(
    *, category: str, memo: str, subjects: list[str], job: str
) -> str | None:
    """맛집/여행의 '상호(가게명)'를 추출. 상호는 맛집 글의 1순위 검색어다.

    근거 우선순위(전부 사용자/현장 유래라 신뢰도 높음):
      1) job 폴더명에서 날짜·번호 접두와 지역 토큰을 뺀 나머지
         (예: '0630 모리몰리' → '모리몰리', '0624 바오 서울' → '바오').
      2) (1)이 비면 메모 첫 줄이 짧은 고유명사면 그것을 상호로.
    확신이 없으면 None(날조 금지). 일반어(맛집·카페 등)는 상호로 보지 않는다.
    """
    if category not in ("맛집", "여행"):
        return None

    # 1) job 폴더명 파싱.
    parts = []
    for t in _tokens(job):
        if re.fullmatch(r"\d{2,8}", t):       # 날짜/번호 접두(0630, 20240630 등)
            continue
        if t in _KNOWN_LOCATIONS:             # 지역은 상호 아님
            continue
        if t in _STORE_STOPWORDS:             # 맛집/카페 등 일반어 제외
            continue
        parts.append(t)
    name = " ".join(parts).strip()
    if name and len(name) >= 2:
        return name

    # 2) 메모 첫 줄(짧은 고유명사형)만 보수적으로.
    if memo:
        first = memo.splitlines()[0].strip() if memo.splitlines() else ""
        if 2 <= len(first) <= 20 and first not in _STORE_STOPWORDS and " " not in first:
            return first

    return None


def _extract_product_and_brand(
    *, category: str, memo: str, subjects: list[str], job: str
) -> tuple[str | None, str | None]:
    """육아템에 한해 제품명/브랜드 추출 시도. 확실치 않으면 None(날조 금지).

    메모/subject 가 핵심 근거다. 제품 리뷰가 아니면 둘 다 None.
    """
    if category != "육아템":
        return (None, None)

    text = " ".join([memo] + subjects)
    if not text.strip():
        return (None, None)

    product_type: str | None = None
    brand: str | None = None

    # 제품 유형: 흔한 육아템 명사(메모/subject에 실제로 등장할 때만).
    product_nouns = [
        "유모차", "카시트", "젖병", "분유포트", "쪽쪽이", "치발기", "보행기", "바운서",
        "아기띠", "힙시트", "범보의자", "이유식 마스터기", "이유식마스터기", "소독기",
        "젖병소독기", "체온계", "콧물흡입기", "기저귀", "물티슈", "손소독", "역류방지쿠션",
        "수유쿠션", "모빌", "쏘서", "점퍼루", "워크짐", "아기침대", "범퍼침대", "식판",
        "빨대컵", "스파우트컵", "턱받이", "치발", "역류방지", "분유", "손수건", "겉싸개",
    ]
    # 합성어(예: '흡착식판')까지 잡도록, 위 명사를 '접미사'로 포함하는 토큰을 통째로 채택.
    suffixes = ("식판", "유모차", "카시트", "젖병", "소독기", "흡입기", "체온계", "빨대컵",
                "턱받이", "바운서", "치발기", "보행기", "아기띠", "힙시트", "컵", "의자",
                "매트", "침대", "쿠션", "포트")
    tokens = _tokens(text)
    for tok in tokens:
        if len(tok) >= 3 and any(tok.endswith(s) for s in suffixes):
            product_type = tok        # '흡착식판', '실리콘빨대컵' 등 통째로
            break
    if not product_type:
        for noun in product_nouns:
            if noun in text:
                product_type = noun
                break

    # 브랜드: 일반 추출은 오탐 위험 → '브랜드/제조사/메이커' 라벨이 붙은 경우만 보수적으로.
    #   '브랜드는 마더케이', '제조사: 누비누비' 같은 조사/구분자 형태를 허용.
    m = re.search(
        r"(?:브랜드|제조사|메이커)\s*(?:는|은|이|가)?\s*[:：]?\s*([A-Za-z][A-Za-z가-힣0-9]{1,19}|[가-힣]{2,20})",
        text,
    )
    if m:
        cand = m.group(1).strip()
        if cand not in ("는", "은", "이", "가"):
            brand = cand

    return (product_type, brand)


def _detect_topics(
    *,
    subjects: list[str],
    memo: str,
    folder_names: list[str],
    location: str | None,
    product_type: str | None,
    brand: str | None,
) -> list[str]:
    """subject+메모+폴더명에서 의미 있는 명사를 뽑아 dedup(순서 보존).

    핵심 신호(location/product/brand)를 앞에 배치하고, 폴더명/subject 빈출어로 보강한다.
    """
    topics: list[str] = []

    # 1) 확정 신호 먼저.
    for v in (location, product_type, brand):
        if v:
            topics.append(v)

    # 2) 폴더명(촬영자가 직접 분류한 카테고리 — 신뢰도 높음). stopword 제외.
    for name in folder_names:
        name = name.strip()
        if name and name not in _STOPWORD_TOPICS and len(name) >= 2:
            topics.append(name)

    # 3) subject 빈출 토큰(2글자 이상, 너무 흔한 일반어 제외).
    freq: dict[str, int] = {}
    for s in subjects:
        for tok in _tokens(s):
            if len(tok) < 2 or tok in _STOPWORD_TOPICS:
                continue
            freq[tok] = freq.get(tok, 0) + 1
    # 2회 이상 등장한 토큰만 상위로(의미 있는 반복 = 핵심 주제일 확률↑).
    salient = sorted(
        (t for t, c in freq.items() if c >= 2),
        key=lambda t: -freq[t],
    )
    topics.extend(salient[:12])

    return _dedup_keep_order([t for t in topics if t])


# ───────────────────────── 내부 헬퍼: 텍스트 유틸 ─────────────────────────

def _tokens(text: str) -> list[str]:
    """한글/영문/숫자 토큰화(공백·기호 분리)."""
    return _HANGUL_TOKEN.findall(text or "")


def _contains_any(text: str, words: tuple[str, ...] | list[str]) -> bool:
    t = text or ""
    return any(w and w in t for w in words)


def _category_hits(categories: list[str], words: tuple[str, ...] | list[str]) -> bool:
    """카테고리/폴더 이름 목록 중 하나라도 신호 단어를 포함하는지."""
    for c in categories:
        if c and any(w and w in c for w in words):
            return True
    return False


def _dedup_keep_order(items: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    out: list[str] = []
    for it in items:
        k = (it or "").strip()
        if k and k not in seen:
            seen[k] = None
            out.append(k)
    return out
