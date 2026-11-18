from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from scrapy import Request

from scrapy_quanticdata import QuanticDataConfigError, QuanticDataMiddleware

from .conftest import KEY, DummySpider, MakeMiddleware

TARGET = "https://quotes.toscrape.com/page/2/"


def body(request: Request) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(request.body)
    return data


def routed(mw: QuanticDataMiddleware, request: Request) -> Request:
    out = mw.process_request(request)
    assert isinstance(out, Request)
    return out


class TestRouting:
    def test_untouched_without_meta_when_disabled(self, mw: QuanticDataMiddleware) -> None:
        assert mw.process_request(Request(TARGET)) is None

    def test_meta_true_routes_to_default_backend(self, mw: QuanticDataMiddleware) -> None:
        api = routed(mw, Request(TARGET, meta={"quanticdata": True}))
        assert api.url == "https://api.quanticdata.io/v1/scraper/unlock"
        assert api.method == "POST"

    def test_enabled_routes_every_request_and_meta_false_bypasses(self, make_mw: MakeMiddleware) -> None:
        mw = make_mw(QUANTICDATA_ENABLED=True)
        assert isinstance(mw.process_request(Request(TARGET)), Request)
        assert mw.process_request(Request(TARGET, meta={"quanticdata": False})) is None

    def test_backend_from_meta(self, mw: QuanticDataMiddleware) -> None:
        api = routed(mw, Request(TARGET, meta={"quanticdata": {"backend": "extract", "format": "markdown"}}))
        assert api.url == "https://api.quanticdata.io/v1/scraper/extract"
        assert body(api) == {"url": TARGET, "format": "markdown"}

    def test_backend_from_settings(self, make_mw: MakeMiddleware) -> None:
        mw = make_mw(QUANTICDATA_BACKEND="extract", QUANTICDATA_EXTRACT_PARAMS={"format": "html", "country": "us"})
        api = routed(mw, Request(TARGET, meta={"quanticdata": {"render": True}}))
        assert body(api) == {"url": TARGET, "format": "html", "country": "us", "render": True}

    def test_api_requests_are_not_routed_again(self, mw: QuanticDataMiddleware) -> None:
        api = routed(mw, Request(TARGET, meta={"quanticdata": True}))
        assert mw.process_request(api) is None

    def test_non_http_schemes_are_ignored(self, make_mw: MakeMiddleware) -> None:
        mw = make_mw(QUANTICDATA_ENABLED=True)
        assert mw.process_request(Request("data:,hello")) is None

    def test_base_url_override(self, make_mw: MakeMiddleware, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QUANTICDATA_API_BASE", "http://127.0.0.1:4012/v1/")
        mw = make_mw()
        assert routed(mw, Request(TARGET, meta={"quanticdata": True})).url == "http://127.0.0.1:4012/v1/scraper/unlock"

    def test_bad_meta_value(self, mw: QuanticDataMiddleware) -> None:
        with pytest.raises(QuanticDataConfigError):
            mw.process_request(Request(TARGET, meta={"quanticdata": "yes"}))


class TestRobotsTxt:
    def robots(self) -> Request:
        return Request("https://quotes.toscrape.com/robots.txt", meta={"dont_obey_robotstxt": True})

    def test_direct_by_default_even_when_enabled(self, make_mw: MakeMiddleware) -> None:
        mw = make_mw(QUANTICDATA_ENABLED=True)
        assert mw.process_request(self.robots()) is None

    def test_through_unlock_when_configured(self, make_mw: MakeMiddleware) -> None:
        mw = make_mw(QUANTICDATA_ROBOTSTXT="unlock", QUANTICDATA_BACKEND="extract")
        api = routed(mw, self.robots())
        assert api.url.endswith("/scraper/unlock")
        assert body(api)["url"] == "https://quotes.toscrape.com/robots.txt"

    def test_new_scrapy_meta_flag(self, make_mw: MakeMiddleware) -> None:
        mw = make_mw(QUANTICDATA_ENABLED=True)
        assert mw.process_request(Request("https://quotes.toscrape.com/robots.txt", meta={"is_robotstxt_request": True})) is None


class TestApiRequest:
    def test_key_only_in_the_api_authorization_header(self, mw: QuanticDataMiddleware) -> None:
        api = routed(mw, Request(TARGET, meta={"quanticdata": True}))
        assert api.headers[b"Authorization"] == f"Bearer {KEY}".encode()
        assert KEY not in api.body.decode()
        assert api.headers[b"Content-Type"] == b"application/json"
        assert api.headers[b"Accept-Encoding"] == b"identity"

    def test_target_headers_forwarded_without_scrapy_defaults(self, mw: QuanticDataMiddleware) -> None:
        req = Request(
            TARGET,
            headers={
                "User-Agent": "Scrapy/2",
                "Accept": "text/html",
                "Accept-Encoding": "gzip",
                "X-Test": "1",
                "Referer": "https://quotes.toscrape.com/",
            },
            meta={"quanticdata": True},
        )
        req.headers.appendlist("Cookie", "a=1")
        req.headers.appendlist("Cookie", "b=2")
        sent = body(routed(mw, req))["headers"]
        assert sent == {"X-Test": "1", "Referer": "https://quotes.toscrape.com/", "Cookie": "a=1; b=2"}

    def test_target_authorization_is_the_users_own(self, mw: QuanticDataMiddleware) -> None:
        req = Request(TARGET, headers={"Authorization": "Basic dXNlcjpwYXNz"}, meta={"quanticdata": True})
        api = routed(mw, req)
        assert body(api)["headers"] == {"Authorization": "Basic dXNlcjpwYXNz"}
        assert api.headers[b"Authorization"] == f"Bearer {KEY}".encode()

    @pytest.mark.parametrize(("mode", "expected"), [("all", {"User-Agent": "Scrapy/2", "X-Test": "1"}), ("none", None)])
    def test_forward_header_modes(self, make_mw: MakeMiddleware, mode: str, expected: dict[str, str] | None) -> None:
        mw = make_mw(QUANTICDATA_FORWARD_HEADERS=mode)
        req = Request(TARGET, headers={"User-Agent": "Scrapy/2", "X-Test": "1"}, meta={"quanticdata": True})
        assert body(routed(mw, req)).get("headers") == expected

    def test_post_body_text_and_binary(self, mw: QuanticDataMiddleware) -> None:
        text = body(routed(mw, Request(TARGET, method="POST", body='{"q": 1}', meta={"quanticdata": True})))
        assert text["method"] == "POST"
        assert text["body"] == '{"q": 1}'
        raw = body(routed(mw, Request(TARGET, method="PUT", body=b"\xff\x00", meta={"quanticdata": True})))
        assert base64.b64decode(raw["bodyBase64"]) == b"\xff\x00"
        assert "body" not in raw

    def test_keeps_callback_priority_and_meta(self, mw: QuanticDataMiddleware) -> None:
        spider = DummySpider()
        req = Request(
            TARGET,
            callback=spider.parse,
            priority=7,
            cb_kwargs={"page": 2},
            meta={"quanticdata": True, "mine": 1, "_download_slot_stamp": "x"},
        )
        api = routed(mw, req)
        assert api.callback == spider.parse
        assert api.priority == 7
        assert api.cb_kwargs == {"page": 2}
        assert api.meta["mine"] == 1
        assert api.dont_filter is True
        assert api.meta["download_slot"] == "quotes.toscrape.com"
        assert "_download_slot_stamp" not in api.meta
        assert api.meta["dont_obey_robotstxt"] is True  # the API host is not checked for robots.txt

    def test_unlock_params_merge(self, make_mw: MakeMiddleware) -> None:
        mw = make_mw(QUANTICDATA_UNLOCK_PARAMS={"country": "us", "timeout_ms": 30000})
        sent = body(routed(mw, Request(TARGET, meta={"quanticdata": {"country": "de", "fail_on_block": True}})))
        assert sent == {"url": TARGET, "method": "GET", "country": "de", "timeout_ms": 30000, "fail_on_block": True}


class TestValidation:
    def test_missing_key(self, make_mw: MakeMiddleware) -> None:
        mw = make_mw(QUANTICDATA_API_KEY="")
        with pytest.raises(QuanticDataConfigError, match="QUANTICDATA_API_KEY"):
            mw.process_request(Request(TARGET, meta={"quanticdata": True}))

    def test_key_from_environment(self, make_mw: MakeMiddleware, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QUANTICDATA_API_KEY", "qd_env_key")
        mw = make_mw(QUANTICDATA_API_KEY=None)
        assert routed(mw, Request(TARGET, meta={"quanticdata": True})).headers[b"Authorization"] == b"Bearer qd_env_key"

    def test_unknown_field(self, mw: QuanticDataMiddleware) -> None:
        with pytest.raises(ValueError, match="Not a documented field of the unlock endpoint: wait_for"):
            mw.process_request(Request(TARGET, meta={"quanticdata": {"wait_for": "x"}}))

    def test_reserved_field(self, mw: QuanticDataMiddleware) -> None:
        with pytest.raises(ValueError, match="url is taken from the Scrapy request"):
            mw.process_request(Request(TARGET, meta={"quanticdata": {"url": "https://example.com/"}}))

    def test_extract_only_get(self, mw: QuanticDataMiddleware) -> None:
        with pytest.raises(QuanticDataConfigError, match="only fetches GET"):
            mw.process_request(Request(TARGET, method="POST", meta={"quanticdata": {"backend": "extract"}}))

    def test_extract_format(self, mw: QuanticDataMiddleware) -> None:
        with pytest.raises(ValueError, match="extract format"):
            mw.process_request(Request(TARGET, meta={"quanticdata": {"backend": "extract", "format": "pdf"}}))

    @pytest.mark.parametrize(
        "settings",
        [
            {"QUANTICDATA_BACKEND": "proxy"},
            {"QUANTICDATA_ROBOTSTXT": "skip"},
            {"QUANTICDATA_FORWARD_HEADERS": "some"},
            {"QUANTICDATA_UNLOCK_PARAMS": {"nope": 1}},
        ],
    )
    def test_bad_settings(self, make_mw: MakeMiddleware, settings: dict[str, Any]) -> None:
        with pytest.raises(ValueError, match=r"must be|Not a documented field"):
            make_mw(**settings)

    def test_unknown_backend_in_meta(self, mw: QuanticDataMiddleware) -> None:
        with pytest.raises(ValueError, match="Unknown QuanticData backend"):
            mw.process_request(Request(TARGET, meta={"quanticdata": {"backend": "proxy"}}))
