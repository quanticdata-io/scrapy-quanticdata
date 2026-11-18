from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from scrapy import Request, Spider
from scrapy.http import Response, TextResponse
from scrapy.utils.test import get_crawler

from scrapy_quanticdata import QuanticDataMiddleware

FIXTURES = Path(__file__).parent / "fixtures"
KEY = "qd_test_123"


class DummySpider(Spider):
    name = "dummy"

    def parse(self, response: Response, **kwargs: Any) -> Any:
        return None


def fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


def api_response(
    request: Request, data: dict[str, Any] | str, status: int = 200, headers: dict[str, str] | None = None
) -> TextResponse:
    body = data if isinstance(data, str) else json.dumps(data)
    return TextResponse(
        url=request.url,
        status=status,
        headers={"Content-Type": "application/json", **(headers or {})},
        body=body.encode("utf-8"),
        request=request,
    )


MakeMiddleware = Callable[..., QuanticDataMiddleware]


@pytest.fixture
def make_mw(monkeypatch: pytest.MonkeyPatch) -> MakeMiddleware:
    monkeypatch.delenv("QUANTICDATA_API_KEY", raising=False)
    monkeypatch.delenv("QUANTICDATA_API_BASE", raising=False)

    def make(**settings: Any) -> QuanticDataMiddleware:
        merged = {"QUANTICDATA_API_KEY": KEY, **settings}
        crawler = get_crawler(DummySpider, merged)
        mw = QuanticDataMiddleware.from_crawler(crawler)
        if crawler.stats is not None:
            try:
                crawler.stats.open_spider()
            except TypeError:  # Scrapy < 2.13 requires the spider argument
                crawler.stats.open_spider(DummySpider())
        return mw

    return make


@pytest.fixture
def mw(make_mw: MakeMiddleware) -> QuanticDataMiddleware:
    return make_mw()
