"""SEO 레이어 도메인 모델.

모든 모듈이 공유하는 데이터 계약(contract)이다. DB 컬럼과 1:1 대응되는 모델은
to_dict/from_row 로 직렬화한다. JSON 컬럼(*_json)은 파이썬 리스트/딕트로 들고 다니고
repository 가 저장 시점에 json.dumps 한다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# ───────────────────────── 영속(DB) 모델 ─────────────────────────

@dataclass
class PostRecord:
    """posts 테이블 — 과거글/신규글 메타데이터."""
    post_id: str
    title: str
    url: str | None = None
    category: str | None = None
    published_at: str | None = None
    updated_at: str | None = None
    content_md: str | None = None
    content_text: str | None = None
    tags: list[str] = field(default_factory=list)
    media_count: int = 0
    image_count: int = 0
    gif_count: int = 0
    video_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PostMetric:
    """post_metrics 테이블 — 글별 일자별 성과."""
    post_id: str
    metric_date: str                       # 'YYYY-MM-DD'
    views: int = 0
    visitors: int = 0
    search_inflow: int = 0
    likes: int = 0
    comments: int = 0
    new_neighbors: int = 0
    avg_duration_seconds: float | None = None
    source: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InflowKeyword:
    """inflow_keywords 테이블 — 글별 유입 키워드."""
    post_id: str
    metric_date: str
    keyword: str
    inflow_count: int = 0
    source: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KeywordResearch:
    """keyword_research 테이블 — 키워드별 수요/경쟁도/트렌드 스냅샷."""
    keyword: str
    collected_date: str                    # 'YYYY-MM-DD'
    search_demand_score: float | None = None
    trend_score: float | None = None
    trend_direction: str | None = None     # 'up' | 'down' | 'flat'
    shopping_trend_score: float | None = None
    shopping_category: str | None = None
    blog_document_count: int | None = None
    competition_score: float | None = None
    opportunity_score: float | None = None
    top_titles: list[str] = field(default_factory=list)
    top_urls: list[str] = field(default_factory=list)
    related_keywords: list[str] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KeywordRanking:
    """keyword_rankings 테이블 — 특정 키워드에서 내 글 노출 여부."""
    keyword: str
    checked_date: str
    post_id: str | None = None
    post_url: str | None = None
    is_exposed: bool = False
    rank: int | None = None
    page: int | None = None
    search_result_url: str | None = None
    source: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SeoBrief:
    """generated_briefs 테이블 — 작성 전 결정된 SEO 전략."""
    brief_id: str
    input_folder: str | None = None
    category: str | None = None
    detected_topics: list[str] = field(default_factory=list)
    primary_keyword: str | None = None
    secondary_keywords: list[str] = field(default_factory=list)
    avoid_keywords: list[str] = field(default_factory=list)
    recommended_title: str | None = None
    title_alternatives: list[dict[str, Any]] = field(default_factory=list)
    selected_tags: list[str] = field(default_factory=list)
    keyword_scores: list[dict[str, Any]] = field(default_factory=list)
    strategy_reason: str | None = None
    seo_brief_md: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PostOutcome:
    """post_outcomes 테이블 — brief 와 실제 성과 연결."""
    brief_id: str
    post_id: str | None = None
    post_url: str | None = None
    published_at: str | None = None
    views_1d: int | None = None
    views_3d: int | None = None
    views_7d: int | None = None
    views_30d: int | None = None
    search_inflow_1d: int | None = None
    search_inflow_3d: int | None = None
    search_inflow_7d: int | None = None
    search_inflow_30d: int | None = None
    top_inflow_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ───────────────────────── 비영속(파이프라인) 모델 ─────────────────────────

@dataclass
class TopicExtraction:
    """topic_extractor 출력 — 입력 콘텐츠에서 뽑은 주제/카테고리/검색 의도."""
    input_folder: str
    category: str = "기타"
    detected_topics: list[str] = field(default_factory=list)
    location: str | None = None
    product_type: str | None = None
    brand: str | None = None
    age_group: str | None = None
    content_type: str | None = None        # '방문 후기' | '제품 리뷰' | ...
    target_intents: list[str] = field(default_factory=list)
    is_product_review: bool = False        # 쇼핑인사이트 호출 여부 판단
    has_parking_evidence: bool = False
    has_date_mood: bool = False
    has_kid_context: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KeywordCandidates:
    """keyword_candidate_generator 출력 — 후보 키워드 묶음(문자열 리스트)."""
    primary_candidates: list[str] = field(default_factory=list)
    secondary_candidates: list[str] = field(default_factory=list)
    tag_candidates: list[str] = field(default_factory=list)
    avoid_candidates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def all_research_targets(self) -> list[str]:
        """데이터 수집 대상(중복 제거, 순서 보존). avoid 는 제외."""
        seen: dict[str, None] = {}
        for kw in self.primary_candidates + self.secondary_candidates:
            k = (kw or "").strip()
            if k and k not in seen:
                seen[k] = None
        return list(seen.keys())


@dataclass
class ScoredKeyword:
    """keyword_scoring 출력 — 후보 1개의 세부 점수 + 최종 점수."""
    keyword: str
    role: str = "secondary"                # 'primary' | 'secondary'
    final_score: float = 0.0
    search_demand_score: float = 0.0
    opportunity_score: float = 0.0
    my_blog_fit_score: float = 0.0
    content_fit_score: float = 0.0
    seasonality_score: float = 0.0
    competition_penalty: float = 0.0
    mismatch_penalty: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TitleCandidate:
    """title_optimizer 출력 — 제목 후보 1개."""
    title: str
    score: float = 0.0
    reason: str = ""
    components: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QualityResult:
    """quality_guard 출력."""
    passed: bool = True
    score: float = 0.0
    issues: list[str] = field(default_factory=list)
    suggested_fixes: list[str] = field(default_factory=list)
    final_title: str = ""
    final_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
