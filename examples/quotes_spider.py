"""Crawl quotes.toscrape.com (a public sandbox for scraping practice) through QuanticData.

    export QUANTICDATA_API_KEY=qd_live_your_key
    scrapy runspider examples/quotes_spider.py -O quotes.json

Every request goes through the Web Unlocker (QUANTICDATA_ENABLED). robots.txt is
obeyed and fetched directly unless you pass -s QUANTICDATA_ROBOTSTXT=unlock.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import scrapy
from scrapy.http import Response


class QuotesSpider(scrapy.Spider):
    name = "quotes"
    start_urls = ["https://quotes.toscrape.com/page/1/"]
    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "DOWNLOADER_MIDDLEWARES": {"scrapy_quanticdata.QuanticDataMiddleware": 725},
        "QUANTICDATA_ENABLED": True,
        "QUANTICDATA_UNLOCK_PARAMS": {"country": "us"},
        # robots.txt counts as one page
        "CLOSESPIDER_PAGECOUNT": 4,
        "DOWNLOAD_DELAY": 1,
    }

    def parse(self, response: Response, **kwargs: Any) -> Iterator[Any]:
        for quote in response.css("div.quote"):
            yield {
                "text": quote.css("span.text::text").get(),
                "author": quote.css("small.author::text").get(),
                "tags": quote.css("a.tag::text").getall(),
                "url": response.url,
            }
        next_page = response.css("li.next a::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)
