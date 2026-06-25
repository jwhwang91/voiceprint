"""네이버 Open API 클라이언트(blog_automation.seo.naver_openapi_client) 테스트.

네트워크는 전부 모킹한다(모듈의 requests 를 fake 로 교체). credential 부재/HTTP 오류 시
graceful 하게 None 을 반환하고, 정상 200 응답에서는 HTML 태그가 제거된 정규화 dict 를
돌려주는지 검증한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import requests as real_requests  # noqa: E402

from blog_automation.seo.config import load_growth_config  # noqa: E402
from blog_automation.seo.naver_openapi_client import NaverOpenApiClient  # noqa: E402


class _FakeResponse:
    """code 가 실제로 쓰는 속성(.status_code, .json()/.text)만 흉내내는 응답."""

    def __init__(self, status_code=200, payload=None, raise_on_json=False):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self._raise_on_json = raise_on_json
        self.text = "fake body"

    def json(self):
        if self._raise_on_json:
            # 코드가 except ValueError 로 잡는 JSON 파싱 실패를 흉내낸다.
            raise ValueError("no json")
        return self._payload


class _FakeRequests:
    """blog_automation.seo.naver_openapi_client.requests 대체용.

    code 는 except requests.RequestException 으로 네트워크 예외를 잡으므로
    실제 requests.RequestException 을 그대로 노출해야 한다.
    """

    RequestException = real_requests.RequestException

    def __init__(self, get_result=None, post_result=None):
        self._get_result = get_result
        self._post_result = post_result
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        if isinstance(self._get_result, Exception):
            raise self._get_result
        return self._get_result

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        if isinstance(self._post_result, Exception):
            raise self._post_result
        return self._post_result


def _client_with_creds(monkeypatch):
    """credential 이 있는 것처럼 보이는 클라이언트 + 설정 반환.

    URL/credential 은 .env 에 의존하지 않도록 cfg 인스턴스를 직접 패치한다.
    """
    g = load_growth_config()
    # credential 존재 + 토글 on 으로 강제(.env 무관, is_available()==True 보장).
    monkeypatch.setattr(g, "has_open_api_credentials", lambda: True)
    monkeypatch.setattr(g, "use_open_api", lambda: True)
    # 인증 헤더 생성에 필요한 env 값을 cfg 인스턴스 레벨에서 제공.
    monkeypatch.setattr(g, "env", lambda name, default=None: {
        "NAVER_CLIENT_ID": "fake-id",
        "NAVER_CLIENT_SECRET": "fake-secret",
    }.get(name, default))
    # 블로그 검색 URL 확정(.env 에 없을 수 있으므로).
    monkeypatch.setattr(g, "search_blog_api_url",
                        lambda: "https://openapi.naver.com/v1/search/blog.json")
    return NaverOpenApiClient(g), g


# ── Test 1: credential 없음 → is_available() False, search_blog None(예외 없음) ──
def test_missing_credentials_is_unavailable_and_returns_none(monkeypatch):
    g = load_growth_config()
    monkeypatch.setattr(g, "has_open_api_credentials", lambda: False)
    monkeypatch.setattr(g, "use_open_api", lambda: False)
    client = NaverOpenApiClient(g)

    assert client.is_available() is False
    # 예외 없이 None 을 반환해야 한다.
    assert client.search_blog("성수 맛집") is None


# ── Test 2: 정상 200 → 정규화 dict + HTML 태그 제거 ──
def test_search_blog_normalizes_and_strips_html(monkeypatch):
    client, g = _client_with_creds(monkeypatch)

    payload = {
        "total": "1234",  # 문자열로 와도 int 로 정규화돼야 한다.
        "items": [
            {
                "title": "<b>성수</b> 맛집 추천",
                "link": "https://blog.naver.com/a/1 ",
                "description": "여기 <b>분위기</b> 진짜 좋아요",
                "bloggername": "테스터",
                "bloggerlink": "https://blog.naver.com/a",
                "postdate": "20260101",
            },
            "not-a-dict",  # dict 아닌 항목은 무시돼야 한다.
        ],
    }
    fake = _FakeRequests(get_result=_FakeResponse(status_code=200, payload=payload))
    monkeypatch.setattr("blog_automation.seo.naver_openapi_client.requests", fake)

    result = client.search_blog("성수 맛집")

    assert isinstance(result, dict)
    assert result["source"] == "naver_blog_search_api"
    assert result["keyword"] == "성수 맛집"
    assert isinstance(result["total"], int)
    assert result["total"] == 1234
    assert isinstance(result["items"], list)
    # dict 아닌 항목은 제외 → 1개만.
    assert len(result["items"]) == 1

    item = result["items"][0]
    # HTML 태그가 모두 제거돼야 한다.
    assert item["title"] == "성수 맛집 추천"
    assert "<b>" not in item["title"]
    assert item["description"] == "여기 분위기 진짜 좋아요"
    assert "<b>" not in item["description"]
    assert item["link"] == "https://blog.naver.com/a/1"  # strip 적용
    assert item["bloggername"] == "테스터"

    # GET 이 실제로 호출됐는지 확인.
    assert len(fake.get_calls) == 1


# ── Test 3: HTTP 500 → None(graceful) ──
def test_search_blog_http_500_returns_none(monkeypatch):
    client, g = _client_with_creds(monkeypatch)
    fake = _FakeRequests(get_result=_FakeResponse(status_code=500, payload={}))
    monkeypatch.setattr("blog_automation.seo.naver_openapi_client.requests", fake)

    assert client.search_blog("성수 맛집") is None


# ── Test 3b: 네트워크 예외 raise → None(crash 안 함) ──
def test_search_blog_network_exception_returns_none(monkeypatch):
    client, g = _client_with_creds(monkeypatch)
    fake = _FakeRequests(
        get_result=real_requests.RequestException("boom")
    )
    monkeypatch.setattr("blog_automation.seo.naver_openapi_client.requests", fake)

    assert client.search_blog("성수 맛집") is None
