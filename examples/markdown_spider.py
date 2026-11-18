"""Save book pages of books.toscrape.com (a public scraping sandbox) as Markdown.

    export QUANTICDATA_API_KEY=qd_live_your_key
    scrapy runspider examples/markdown_spider.py -O books.jsonl

Listing pages are downloaded directly by Scrapy; only the product pages go
through the QuanticData scrape endpoint, per request, with format "markdown".
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import scrapy
from scrapy.http import Response


class BookMarkdownSpider(scrapy.Spider):
    name = "book_markdown"
    start_urls = ["https://books.toscrape.com/catalogue/category/books/poetry_23/index.html"]
    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "DOWNLOADER_MIDDLEWARES": {"scrapy_quanticdata.QuanticDataMiddleware": 725},
        "CLOSESPIDER_ITEMCOUNT": 5,
        "DOWNLOAD_DELAY": 1,
    }

    def parse(self, response: Response, **kwargs: Any) -> Iterator[scrapy.Request]:
        for href in response.css("article.product_pod h3 a::attr(href)").getall():
            yield response.follow(
                href,
                callback=self.parse_book,
                meta={"quanticdata": {"backend": "extract", "format": "markdown", "contentMode": "article"}},
            )

    def parse_book(self, response: Response) -> Iterator[dict[str, Any]]:
        info = response.meta.get("quanticdata_response", {})
        yield {"url": response.url, "title": info.get("title"), "markdown": response.text}
