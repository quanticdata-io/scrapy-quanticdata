# scrapy-quanticdata

A Scrapy downloader middleware that sends selected requests through the [QuanticData](https://quanticdata.io/) Web Unlocker (`POST /scraper/unlock`) or scrape API (`POST /scraper/extract`) and hands your spider an ordinary Scrapy response for the URL it asked for, so `response.css()`, `response.xpath()` and `response.follow()` keep working unchanged.

[![CI](https://github.com/quanticdata-io/scrapy-quanticdata/actions/workflows/ci.yml/badge.svg)](https://github.com/quanticdata-io/scrapy-quanticdata/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

- Turn it on for every request, or per request with `meta={"quanticdata": True}`.
- `unlock` backend: the request (method, headers, body) is sent through the Web Unlocker and the target's response comes back with its own status, headers and raw body.
- `extract` backend: the page comes back as HTML or Markdown from the scrape endpoint.
- Callbacks, `cb_kwargs`, priority, meta and cookies behave as usual; per-site download slots (`DOWNLOAD_DELAY`, AutoThrottle, concurrency per domain) still apply to the target site.
- Your API key goes only to the API, in the `Authorization` header.

## Install

Not on PyPI yet. Install from source:

```bash
pip install git+https://github.com/quanticdata-io/scrapy-quanticdata
```

or from a clone:

```bash
git clone https://github.com/quanticdata-io/scrapy-quanticdata
cd scrapy-quanticdata
pip install -e .
```

Python 3.10 or later, Scrapy 2.11 or later (Scrapy 2.11 itself needs `w3lib<2.2`; CI tests 2.11.2 and the latest release). Works with the asyncio reactor and the other Twisted reactors (CI runs a crawl on the asyncio and select reactors).

## Quickstart

`settings.py`:

```python
DOWNLOADER_MIDDLEWARES = {
    "scrapy_quanticdata.QuanticDataMiddleware": 725,
}
QUANTICDATA_ENABLED = True  # every request; or leave False and opt in per request
QUANTICDATA_UNLOCK_PARAMS = {"country": "us"}
```

Set the key in the environment (create one on the API keys page of the [QuanticData dashboard](https://app.quanticdata.io/)):

```bash
export QUANTICDATA_API_KEY=qd_live_your_key
scrapy runspider examples/quotes_spider.py -O quotes.json
```

[`examples/quotes_spider.py`](examples/quotes_spider.py) crawls the public sandbox `quotes.toscrape.com` with `ROBOTSTXT_OBEY = True`. [`examples/markdown_spider.py`](examples/markdown_spider.py) downloads listing pages directly and only the product pages of `books.toscrape.com` as Markdown through the `extract` backend.

Per request:

```python
yield scrapy.Request(url, callback=self.parse)  # follows QUANTICDATA_ENABLED
yield scrapy.Request(url, meta={"quanticdata": True})  # through the default backend
yield scrapy.Request(url, meta={"quanticdata": {"country": "de", "fail_on_block": True}})
yield scrapy.Request(url, meta={"quanticdata": {"backend": "extract", "format": "markdown"}})
yield scrapy.Request(url, meta={"quanticdata": False})  # always direct
```

Try it with no key and no network against the bundled mock of the API (from a clone):

```bash
python tests/mock_api.py &     # mock API on http://127.0.0.1:4012/v1
export QUANTICDATA_API_KEY=qd_test_123 QUANTICDATA_API_BASE=http://127.0.0.1:4012/v1
scrapy runspider examples/quotes_spider.py -s QUANTICDATA_ROBOTSTXT=unlock -O quotes.json
```

## What the spider receives

With the `unlock` backend the response is built from the API's answer:

| Response attribute | Source |
| --- | --- |
| `response.url` | `payload.finalUrl` (the URL after redirects) |
| `response.status` | `payload.status`, the status the target answered |
| `response.headers` | `payload.headers`, without `Content-Encoding` and `Content-Length` |
| `response.body` | `payload.bodyBase64`, decoded: the raw page. With `format` `markdown` or `text`, the converted `payload.body` instead |
| `response.request` | your original request (URL, method, headers, body, callback, meta) |
| `response.meta["quanticdata_response"]` | every other field of `payload`: `request_id`, `blocked`, `blockClass`, `hint`, `attempts`, `tier_served`, `cost`... |

The class follows the content type, as in Scrapy (`HtmlResponse`, `XmlResponse`, `TextResponse`, `Response`).

With the `extract` backend, `response.body` is `payload.content` (UTF-8), as an `HtmlResponse` for `format: "html"` and a `TextResponse` with `Content-Type: text/markdown` or `text/plain` otherwise; `quanticdata_response` holds `title`, `metadata`, `engine`, `status` and the other payload fields.

An answer from the API (trimmed), recorded on 2026-11-18 for `https://quotes.toscrape.com/page/2/`:

```json
{
  "type": "response",
  "message": "Unlocker request successful",
  "payload": {
    "request_id": "...",
    "status": 200,
    "headers": { "content-type": ["text/html; charset=utf-8"] },
    "bodyBase64": "PCFET0NUWVBFIGh0bWw+...",
    "finalUrl": "https://quotes.toscrape.com/page/2/",
    "contentType": "text/html; charset=utf-8",
    "attempts": 1,
    "blocked": false,
    "rendered": false,
    "mode": "auto",
    "tier_served": "tls",
    "format": "html",
    "tier": "premium"
  }
}
```

### Pages that stay blocked

When the target still refuses the request, the API answers 200 with `blocked: true` and the target's own page and status (often 403). The spider gets that response with `response.meta["quanticdata_response"]["blocked"] == True`, `blockClass` and `hint`; Scrapy's `HttpErrorMiddleware` drops non-2xx responses unless you allow them (`handle_httpstatus_list`). With `fail_on_block: True` the API answers 424 instead and the request's errback receives a `QuanticDataAPIError` with `code == "target_blocked"`.

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `QUANTICDATA_API_KEY` | env `QUANTICDATA_API_KEY` | API key, sent as `Authorization: Bearer <key>` to the API only |
| `QUANTICDATA_API_BASE` | env `QUANTICDATA_API_BASE`, else `https://api.quanticdata.io/v1` | API base URL |
| `QUANTICDATA_ENABLED` | `False` | `True`: send every http(s) request through the API unless its meta says `False`. `False`: only requests with `meta["quanticdata"]` |
| `QUANTICDATA_BACKEND` | `"unlock"` | Default backend: `"unlock"` or `"extract"` |
| `QUANTICDATA_UNLOCK_PARAMS` | `{}` | Fields added to every unlock call, e.g. `{"country": "us", "timeout_ms": 30000}` |
| `QUANTICDATA_EXTRACT_PARAMS` | `{}` | Fields added to every extract call, e.g. `{"format": "html", "render": True}` |
| `QUANTICDATA_FORWARD_HEADERS` | `"custom"` | Which request headers go to the target. `"custom"`: all except transport headers and Scrapy's default `User-Agent`, `Accept`, `Accept-Language`. `"all"`: also those three. `"none"`: no headers |
| `QUANTICDATA_ROBOTSTXT` | `"direct"` | How robots.txt requests made by `ROBOTSTXT_OBEY` are downloaded: `"direct"` (normal Scrapy download) or `"unlock"` (through the Web Unlocker) |
| `QUANTICDATA_MAX_RETRIES` | `3` | Retries of an API call that answered one of `QUANTICDATA_RETRY_STATUSES` |
| `QUANTICDATA_RETRY_STATUSES` | `[429, 500, 503, 504]` | API statuses that are retried; the wait is the API's `Retry-After`, else 1, 2, 4... seconds |
| `QUANTICDATA_MAX_RETRY_DELAY` | `60` | A `Retry-After` longer than this (seconds) is not waited for; the request fails instead |

Parameters are checked against the request fields documented in the [API reference](https://quanticdata.io/docs/) (`src/scrapy_quanticdata/params.py`); an unknown name raises `ValueError` before anything is sent. `url`, `method`, `headers`, `body` and `bodyBase64` (unlock) and `url`, `html`, `headers` (extract) come from the Scrapy request and cannot be set as parameters.

Commonly used fields, as documented:

| Backend | Field | Meaning |
| --- | --- | --- |
| both | `country`, `state`, `city` | Exit location of the request |
| both | `rotation`, `sessionId`, `sessionDuration` | `"rotating"` (new exit per request) or `"sticky"` (keep one exit for a session id) |
| unlock | `tier` | `"premium"` (default) or `"mobile"` exits |
| unlock | `mode` | `"auto"` (default), `"tls"` or `"browser"` |
| unlock | `format` | `"html"` (default), `"markdown"` or `"text"` for HTML pages |
| unlock | `timeout_ms` | Total time budget of the call, 1000 to 120000 |
| unlock | `fail_on_block` | Answer 424 instead of 200 with `blocked: true` |
| unlock | `cache_ttl` | Seconds a successful GET may be served from your account's cache |
| unlock | `max_bytes` | Cap on the bytes one call may move |
| unlock | `actions`, `waitForSelector`, `waitMs` | Browser steps before the capture |
| extract | `format` | `"markdown"` (default), `"html"` or `"text"` |
| extract | `render` | Run the page in a browser |
| extract | `contentMode` | `"smart"` (default), `"article"` or `"full"` |

## Meta keys

| Key | Direction | Meaning |
| --- | --- | --- |
| `quanticdata` | you set it | `True`: through the default backend. A dict: through the API with these fields; `"backend"` in the dict picks the backend. `False`: always direct |
| `quanticdata_response` | the plugin sets it | The API payload without the body fields, plus `backend` |
| `download_slot` | the plugin sets it if missing | The target's host, so that per-site politeness applies to the API calls made for that site |

## Errors

Raised in the request's errback (and logged by Scrapy as download errors):

| Exception | When |
| --- | --- |
| `QuanticDataAPIError` | The API answered an error envelope: `status`, `code` (`payload.code`, e.g. `no_credit`, `target_blocked`, `rate_limited`), `message`, `payload`. 401: key missing or unknown; 402: no credit for the call; 424: blocked with `fail_on_block`; 429: rate limit after the retries |
| `QuanticDataConfigError` (a `ValueError`) | No API key, an unknown backend, an undocumented or reserved parameter, or a non-GET request on the `extract` backend |

Stats: `quanticdata/requests`, `quanticdata/requests/<backend>`, `quanticdata/responses/<target status>`, `quanticdata/blocked`, `quanticdata/retries`, `quanticdata/api_errors/<status>`.

## How it works

A downloader middleware, like other Scrapy plugins for scraping APIs. `process_request` replaces a routed request with a `POST` to the API that keeps the original callback, `cb_kwargs`, priority and meta (`dont_filter=True`, since the duplicate filter already saw the original request). `process_response` rebuilds the target's response from the JSON answer and attaches it to a copy of the original request. A middleware was chosen over a download handler because it works with Scrapy's own HTTP stack (proxies to the API, HTTP cache, retries of the target's status codes) and needs no reactor-specific code.

Recommended priority 725: after `CookiesMiddleware` (700), so the cookies Scrapy keeps for the target are forwarded to it and the target's `Set-Cookie` headers are stored for the target's domain. Because the middleware reads the API answer before `HttpCompressionMiddleware` (590) runs on it, API calls ask for an uncompressed body (`Accept-Encoding: identity`).

robots.txt: `RobotsTxtMiddleware` checks the target's robots.txt before this middleware sees the request. The robots.txt file itself is downloaded directly by default; set `QUANTICDATA_ROBOTSTXT = "unlock"` to fetch it through the Web Unlocker as well (it is then billed like any unlock call). The API calls themselves are marked `dont_obey_robotstxt`, because the API host is not the site being crawled.

## Cost

Every routed request is a billed API call. The Web Unlocker is metered in bytes against prepaid Web Unlocker GB; the scrape endpoint is billed per successful page. The API reference documents what is not charged (for example blocked pages on the scrape endpoint). See [pricing](https://quanticdata.io/pricing/) for the current rates. Route only the requests that need it (`QUANTICDATA_ENABLED = False` and `meta={"quanticdata": True}`), and keep `HTTPCACHE_ENABLED` on while you develop.

## Limits

- The middleware sends one API call per request; it does not use the batch endpoints.
- Request headers are sent at most 32 per request (the API's limit); identity headers may be replaced by the API unless you pass `keepHeaders: True` (unlock).
- `extract` fetches GET requests only, and returns page content, not the target's headers.
- Large downloads count against `max_bytes` and your unlocker balance; Scrapy's `DOWNLOAD_MAXSIZE` applies to the API's JSON answer, which carries the page base64-encoded.
- `DOWNLOAD_TIMEOUT` (default 180 s) must stay above the API's `timeout_ms` (default 60 s).

## Run against the real API

```bash
export QUANTICDATA_API_KEY=qd_live_your_key
scrapy runspider examples/quotes_spider.py -O quotes.json
```

The key is read from the environment unless `QUANTICDATA_API_KEY` is set in the Scrapy settings. Never commit it.

## Responsible use

- Crawl public pages you are allowed to access, keep `ROBOTSTXT_OBEY = True` and a `DOWNLOAD_DELAY`, and respect each site's terms.
- Do not collect personal data you have no lawful reason to process.
- Requests other than GET and HEAD can change data on the target site; the Web Unlocker sends them once, without retries.

## Development

```bash
uv venv && uv pip install -e . --group dev     # or: pip install -e . pytest pytest-cov mypy ruff
ruff check . && ruff format --check . && mypy && pytest
```

The tests never call the QuanticData API or any website: the middleware is tested against responses recorded from the live API on 2026-11-18 (sanitised, in `tests/fixtures/`), and `tests/test_crawl.py` runs the example spider in a real Scrapy crawl, on the asyncio and select reactors, against the local mock in `tests/mock_api.py`. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
