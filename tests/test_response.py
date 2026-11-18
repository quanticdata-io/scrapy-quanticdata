from __future__ import annotations

import asyncio
from typing import Any

import pytest
from scrapy import Request
from scrapy.http import HtmlResponse, Response, TextResponse

from scrapy_quanticdata import QuanticDataAPIError, QuanticDataMiddleware

from .conftest import FIXTURES, DummySpider, MakeMiddleware, api_response, fixture

TARGET = "https://quotes.toscrape.com/page/2/"
PAGE = (FIXTURES / "quotes-page-2.html").read_text(encoding="utf-8")


def roundtrip(mw: QuanticDataMiddleware, request: Request, data: dict[str, Any] | str, **kw: Any) -> Request | Response:
    api = mw.process_request(request)
    assert isinstance(api, Request)
    return asyncio.run(mw.process_response(api, api_response(api, data, **kw)))


class TestUnlock:
    def test_rebuilds_the_target_response(self, mw: QuanticDataMiddleware) -> None:
        spider = DummySpider()
        req = Request(TARGET, callback=spider.parse, cb_kwargs={"page": 2}, meta={"quanticdata": True, "mine": 1})
        resp = roundtrip(mw, req, fixture("unlock-ok.json"))
        assert isinstance(resp, HtmlResponse)
        assert resp.url == TARGET
        assert resp.status == 200
        assert resp.text == PAGE
        assert resp.css("small.author::text").getall() == ["J.K. Rowling", "Albert Einstein"]
        assert resp.css("li.next a::attr(href)").get() == "/page/3/"
        assert resp.headers.getlist(b"Set-Cookie") == [b"session=example; Path=/"]
        assert resp.request is not None
        assert resp.request.url == TARGET
        assert resp.request.method == "GET"
        assert resp.request.callback == spider.parse
        assert resp.request.cb_kwargs == {"page": 2}
        assert resp.meta["mine"] == 1
        assert "_quanticdata" not in resp.meta
        assert "dont_obey_robotstxt" not in resp.meta
        info = resp.meta["quanticdata_response"]
        assert info["backend"] == "unlock"
        assert info["blocked"] is False
        assert info["request_id"] == "req_example_0001"
        assert "bodyBase64" not in info
        assert "body" not in info

    def test_follow_resolves_against_the_target(self, mw: QuanticDataMiddleware) -> None:
        resp = roundtrip(mw, Request(TARGET, meta={"quanticdata": True}), fixture("unlock-ok.json"))
        assert isinstance(resp, TextResponse)
        assert resp.follow("/page/3/").url == "https://quotes.toscrape.com/page/3/"

    def test_markdown_format(self, mw: QuanticDataMiddleware) -> None:
        resp = roundtrip(mw, Request(TARGET, meta={"quanticdata": {"format": "markdown"}}), fixture("unlock-markdown.json"))
        assert type(resp) is TextResponse
        assert resp.text.startswith("# Quotes to Scrape")
        assert resp.headers[b"Content-Type"] == b"text/markdown; charset=utf-8"

    def test_blocked_page_keeps_its_status(self, mw: QuanticDataMiddleware) -> None:
        resp = roundtrip(mw, Request("https://example.com/pricing", meta={"quanticdata": True}), fixture("unlock-blocked.json"))
        assert isinstance(resp, HtmlResponse)
        assert resp.status == 403
        info = resp.meta["quanticdata_response"]
        assert info["blocked"] is True
        assert info["blockClass"] == "js_challenge"
        assert info["hint"].startswith("Try tier")
        assert mw.stats is not None
        assert mw.stats.get_value("quanticdata/blocked") == 1


class TestExtract:
    def test_html(self, mw: QuanticDataMiddleware) -> None:
        resp = roundtrip(
            mw, Request(TARGET, meta={"quanticdata": {"backend": "extract", "format": "html"}}), fixture("extract-html.json")
        )
        assert isinstance(resp, HtmlResponse)
        assert resp.css("small.author::text").get() == "J.K. Rowling"
        assert resp.meta["quanticdata_response"]["title"] == "Quotes to Scrape"
        assert resp.meta["quanticdata_response"]["engine"] == "tls"

    def test_markdown(self, mw: QuanticDataMiddleware) -> None:
        resp = roundtrip(mw, Request(TARGET, meta={"quanticdata": {"backend": "extract"}}), fixture("extract-markdown.json"))
        assert type(resp) is TextResponse
        assert resp.headers[b"Content-Type"] == b"text/markdown; charset=utf-8"
        assert "J.K. Rowling" in resp.text


class TestErrors:
    def test_retry_after_429(self, make_mw: MakeMiddleware) -> None:
        mw = make_mw(QUANTICDATA_MAX_RETRIES=2)
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        mw._sleep = fake_sleep
        api = mw.process_request(Request(TARGET, meta={"quanticdata": True}))
        assert isinstance(api, Request)
        err = fixture("error-429.json")
        retry = asyncio.run(mw.process_response(api, api_response(api, err, status=429, headers={"Retry-After": "2"})))
        assert isinstance(retry, Request)
        assert retry.url == api.url
        assert retry.body == api.body
        assert retry.meta["_quanticdata"]["retries"] == 1
        retry2 = asyncio.run(mw.process_response(retry, api_response(retry, err, status=429)))
        assert isinstance(retry2, Request)
        assert slept == [2.0, 2.0]  # second wait without Retry-After: 2 ** 1
        with pytest.raises(QuanticDataAPIError) as info:
            asyncio.run(mw.process_response(retry2, api_response(retry2, err, status=429, headers={"Retry-After": "1"})))
        assert info.value.status == 429
        assert info.value.code == "rate_limited"
        assert mw.stats is not None
        assert mw.stats.get_value("quanticdata/retries") == 2

    def test_retry_after_too_long_fails_at_once(self, make_mw: MakeMiddleware) -> None:
        mw = make_mw(QUANTICDATA_MAX_RETRY_DELAY=10)
        with pytest.raises(QuanticDataAPIError):
            roundtrip(
                mw,
                Request(TARGET, meta={"quanticdata": True}),
                fixture("error-429.json"),
                status=429,
                headers={"Retry-After": "120"},
            )

    @pytest.mark.parametrize(
        ("name", "status", "code"), [("error-402.json", 402, "no_credit"), ("error-424.json", 424, "target_blocked")]
    )
    def test_error_envelopes(self, mw: QuanticDataMiddleware, name: str, status: int, code: str) -> None:
        with pytest.raises(QuanticDataAPIError) as info:
            roundtrip(mw, Request(TARGET, meta={"quanticdata": True}), fixture(name), status=status)
        assert info.value.status == status
        assert info.value.code == code
        assert info.value.message == fixture(name)["message"]

    def test_not_json(self, mw: QuanticDataMiddleware) -> None:
        with pytest.raises(QuanticDataAPIError, match="Unexpected answer"):
            roundtrip(mw, Request(TARGET, meta={"quanticdata": True}), "<html>gateway</html>")

    def test_other_responses_pass_through(self, mw: QuanticDataMiddleware) -> None:
        req = Request(TARGET)
        resp = HtmlResponse(url=TARGET, body=b"<p>x</p>", request=req)
        assert asyncio.run(mw.process_response(req, resp)) is resp
