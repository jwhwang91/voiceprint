"""NaverSearchAdClient 자동 스킵 동작 + GrowthConfig 설정 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import blog_automation.seo.naver_searchad_client as searchad_mod  # noqa: E402
from blog_automation.seo.config import load_growth_config  # noqa: E402
from blog_automation.seo.naver_searchad_client import NaverSearchAdClient  # noqa: E402


def test_unconfigured_client_skips_without_raising(monkeypatch):
    """미구성(use_searchad_api False)이면 예외 없이 None 반환(자동 스킵)."""
    g = load_growth_config()

    # .env 상태에 의존하지 않도록 미구성 상태를 인스턴스에 강제한다.
    monkeypatch.setattr(g, "use_searchad_api", lambda: False)

    client = NaverSearchAdClient(g)

    assert client.is_configured() is False
    # 미구성이면 예외 없이 None 을 돌려준다(자동 스킵).
    assert client.get_keyword_data("아기 식판") is None


def test_configured_client_normalizes_keyword_data(monkeypatch):
    """토글/creds 를 강제로 켜고 requests 를 가짜로 바꿔 정규화 dict 를 검증."""
    g = load_growth_config()

    # 인스턴스 단위로 토글/creds 를 켠다(.env 를 건드리지 않음).
    monkeypatch.setattr(g, "use_searchad_api", lambda: True)
    monkeypatch.setattr(g, "has_searchad_credentials", lambda: True)

    # _signed_headers 와 base URL 이 필요로 하는 env 값을 가짜로 제공.
    fake_env = {
        "NAVER_SEARCHAD_ACCESS_LICENSE": "fake-access",
        "NAVER_SEARCHAD_SECRET_KEY": "fake-secret",
        "NAVER_SEARCHAD_CUSTOMER_ID": "12345",
        "NAVER_SEARCHAD_BASE_URL": "https://example.test/searchad",
    }
    monkeypatch.setattr(g, "env", lambda name, default=None: fake_env.get(name, default))

    captured = {}

    class _FakeResp:
        status_code = 200

        def json(self):
            return {
                "keywordList": [
                    {
                        "relKeyword": "아기식판",
                        # '< 10' 류 문자열 카운트가 예외 없이 int 로 변환되어야 한다.
                        "monthlyPcQcCnt": "< 10",
                        "monthlyMobileQcCnt": "1,200",
                        "compIdx": "높음",
                    }
                ]
            }

    def _fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _FakeResp()

    monkeypatch.setattr(searchad_mod.requests, "get", _fake_get)

    client = NaverSearchAdClient(g)
    assert client.is_configured() is True

    result = client.get_keyword_data("아기 식판")
    assert isinstance(result, dict)

    # 정규화 dict 의 키와 값(코드 기준) 검증.
    assert result["keyword"] == "아기 식판"
    assert result["monthly_pc"] == 0          # '< 10' → 0
    assert result["monthly_mobile"] == 1200   # '1,200' → 1200
    assert result["monthly_total"] == 1200
    assert result["comp_idx"] == "높음"
    assert result["source"] == "naver_searchad_api"

    # hintKeywords 는 공백 제거형으로 전달된다.
    assert captured["params"]["hintKeywords"] == "아기식판"


def test_growth_config_scoring_and_paths():
    """scoring 가중치 합 ~1.0, db_path 파일명, use_crawling_fallback() 가 bool."""
    g = load_growth_config()

    weights = g.scoring
    total = sum(float(v) for v in weights.values())
    assert abs(total - 1.0) < 1e-6

    assert str(g.db_path).endswith("blog_growth.db")

    assert isinstance(g.use_crawling_fallback(), bool)
