"""NaverDataCollector 오케스트레이터 테스트.

핵심 검증:
  - 비제품 글은 쇼핑인사이트(get_shopping_trend)를 호출하지 않는다.
  - 제품 글(육아템)은 쇼핑인사이트를 호출할 수 있다(cat_id 매핑 존재).
  - collect 는 유니크 키워드당 1개의 KeywordResearch 를 만들고 repo 에 upsert 한다.
  - openapi.search_blog 가 None 이고 fallback 이 켜져 있어도 graceful 하게 결과를 반환한다.

모든 외부 호출은 fake 로 대체하고 실제 네트워크/.env 에 의존하지 않는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blog_automation.seo.config import load_growth_config  # noqa: E402
from blog_automation.seo.models import KeywordResearch, TopicExtraction  # noqa: E402
from blog_automation.seo.naver_data_collector import NaverDataCollector  # noqa: E402
from blog_automation.seo.repository import Repository  # noqa: E402


# ───────────────────────── 호출 기록용 fake 들 ─────────────────────────

class FakeOpenApi:
    """NaverOpenApiClient 대역. 호출을 기록하고 작은 정규화 응답을 돌려준다."""

    def __init__(self, available=True, search_blog_result="__default__"):
        self._available = available
        self._search_blog_result = search_blog_result
        self.calls = []

    def is_available(self):
        return self._available

    def search_blog(self, query, display=20, start=1, sort="sim"):
        self.calls.append(("search_blog", query, display))
        if self._search_blog_result == "__default__":
            return {
                "keyword": query,
                "total": 1234,
                "items": [
                    {"title": "첫번째 글", "link": "https://blog.naver.com/a/1"},
                    {"title": "두번째 글", "link": "https://blog.naver.com/a/2"},
                ],
                "source": "naver_blog_search_api",
            }
        return self._search_blog_result

    def get_search_trend(self, keyword_groups, start_date, end_date,
                         time_unit="month", device=None, ages=None, gender=None):
        self.calls.append(("get_search_trend", keyword_groups, start_date, end_date))
        return {
            "results": [
                {"title": "g", "data": [
                    {"period": "2026-01-01", "ratio": 40.0},
                    {"period": "2026-02-01", "ratio": 60.0},
                    {"period": "2026-03-01", "ratio": 80.0},
                ]},
            ],
            "source": "naver_datalab_search_api",
        }

    def get_shopping_trend(self, category, keyword_groups, start_date, end_date,
                           time_unit="month", device=None, ages=None, gender=None):
        # 호출 여부 + cat_id 를 기록한다(테스트1의 핵심 단서).
        self.calls.append(("get_shopping_trend", category, keyword_groups))
        return {
            "results": [
                {"title": "g", "data": [
                    {"period": "2026-01-01", "ratio": 30.0},
                    {"period": "2026-02-01", "ratio": 50.0},
                ]},
            ],
            "source": "naver_datalab_shopping_api",
        }

    def shopping_called(self):
        return any(c[0] == "get_shopping_trend" for c in self.calls)


class FakeSearchAd:
    """NaverSearchAdClient 대역. 기본값은 '미설정'이라 호출되지 않는다."""

    def __init__(self, configured=False, data=None):
        self._configured = configured
        self._data = data
        self.calls = []

    def is_configured(self):
        return self._configured

    def get_keyword_data(self, keyword):
        self.calls.append(("get_keyword_data", keyword))
        return self._data


class FakeFallback:
    """CrawlingFallback 대역. enabled/budget 토글 가능."""

    def __init__(self, enabled=False, budget=0, counts=None, related=None):
        self._enabled = enabled
        self._budget = budget
        self._counts = counts
        self._related = related or []
        self.calls = []

    def is_enabled(self):
        return self._enabled

    def remaining_budget(self):
        return self._budget

    def blog_search_counts(self, keyword):
        self.calls.append(("blog_search_counts", keyword))
        return self._counts

    def related_keywords(self, keyword):
        self.calls.append(("related_keywords", keyword))
        return list(self._related)

    def counts_called(self):
        return any(c[0] == "blog_search_counts" for c in self.calls)


# ───────────────────────── 테스트 ─────────────────────────

def test_non_product_topic_skips_shopping_trend(tmp_path):
    """비제품 글(is_product_review=False)은 쇼핑인사이트를 호출하지 않는다."""
    g = load_growth_config()
    repo = Repository(tmp_path / "growth.db")

    openapi = FakeOpenApi()
    searchad = FakeSearchAd()
    fallback = FakeFallback()
    collector = NaverDataCollector(g, repo, openapi=openapi, searchad=searchad, fallback=fallback)

    topic = TopicExtraction(
        input_folder="job1",
        category="맛집",
        is_product_review=False,
    )
    res = collector.collect_one("강남 맛집", topic=topic, use_cache=False)

    assert isinstance(res, KeywordResearch)
    # 핵심 단언: 쇼핑인사이트는 절대 불리지 않았다.
    assert openapi.shopping_called() is False
    # 블로그 검색/검색 트렌드는 정상적으로 시도됐다.
    assert any(c[0] == "search_blog" for c in openapi.calls)

    repo.close()


def test_product_topic_may_call_shopping_trend(tmp_path):
    """제품 글(육아템, is_product_review=True)은 cat_id 가 매핑돼 쇼핑인사이트를 호출한다."""
    g = load_growth_config()
    repo = Repository(tmp_path / "growth.db")

    openapi = FakeOpenApi()
    collector = NaverDataCollector(
        g, repo, openapi=openapi, searchad=FakeSearchAd(), fallback=FakeFallback()
    )

    topic = TopicExtraction(
        input_folder="job2",
        category="육아템",
        is_product_review=True,
    )
    res = collector.collect_one("흡착식판 후기", topic=topic, use_cache=False)

    assert isinstance(res, KeywordResearch)
    # 육아템 → 육아용품 → 50000005 매핑이 존재하므로 쇼핑인사이트가 호출된다.
    assert openapi.shopping_called() is True
    # cat_id 가 문자열로 넘어갔는지 확인.
    shop_call = next(c for c in openapi.calls if c[0] == "get_shopping_trend")
    assert isinstance(shop_call[1], str) and shop_call[1]

    repo.close()


def test_collect_returns_one_per_unique_keyword_and_upserts(tmp_path):
    """collect 는 유니크 키워드당 1개의 결과를 만들고 repo 에 저장한다(중복 제거)."""
    g = load_growth_config()
    repo = Repository(tmp_path / "growth.db")

    openapi = FakeOpenApi()
    collector = NaverDataCollector(
        g, repo, openapi=openapi, searchad=FakeSearchAd(), fallback=FakeFallback()
    )

    keywords = ["강남 맛집", "강남 맛집", "  ", "역삼 카페"]
    results = collector.collect(keywords, topic=None, use_cache=False)

    # 빈 문자열/중복 제거 후 유니크 2개.
    assert len(results) == 2
    out_keywords = {r.keyword for r in results}
    assert out_keywords == {"강남 맛집", "역삼 카페"}

    # repo 에 실제로 upsert 됐는지 확인(캐시 조회로 되짚는다).
    cache_fresh_days = int(g.naver_api.get("keyword_cache_fresh_days", 7) or 7)
    stored = repo.get_fresh_keyword_research("강남 맛집", cache_fresh_days)
    assert stored is not None
    assert stored.keyword == "강남 맛집"

    repo.close()


def test_graceful_when_search_blog_none_with_fallback(tmp_path):
    """search_blog 가 None 이고 fallback 이 켜져 있어도 결과를 반환하고 raise 하지 않는다."""
    g = load_growth_config()
    repo = Repository(tmp_path / "growth.db")

    # 블로그 검색은 None 을 반환 → fallback 으로 보충해야 한다.
    openapi = FakeOpenApi(search_blog_result=None)
    fallback = FakeFallback(
        enabled=True,
        budget=10,
        counts={"total": 5000, "top_titles": ["폴백 글1", "폴백 글2"],
                "top_urls": ["https://x/1", "https://x/2"]},
        related=["연관1", "연관2"],
    )
    collector = NaverDataCollector(
        g, repo, openapi=openapi, searchad=FakeSearchAd(), fallback=fallback
    )

    res = collector.collect_one("강남 맛집", topic=None, use_cache=False)

    assert isinstance(res, KeywordResearch)
    assert res.keyword == "강남 맛집"
    # fallback 카운트가 실제로 시도됐는지 확인.
    assert fallback.counts_called() is True
    # 블로그 총건수는 fallback 값으로 채워졌다.
    assert res.blog_document_count == 5000

    repo.close()
