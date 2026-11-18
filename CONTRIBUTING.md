# Contributing

Thanks for helping.

## Setup

```bash
git clone https://github.com/quanticdata-io/scrapy-quanticdata
cd scrapy-quanticdata
uv venv && uv pip install -e . --group dev
```

Plain pip works too: `pip install -e . pytest pytest-cov mypy ruff`.

## Checks

CI runs these on Python 3.10 to 3.13, on Ubuntu and Windows, and once with the lowest supported Scrapy (2.11):

```bash
ruff check .
ruff format --check .
mypy
pytest
```

## Ground rules

- Tests never call the QuanticData API or a website. Unit tests build API answers from `tests/fixtures/`; `tests/test_crawl.py` runs a real crawl against the mock in `tests/mock_api.py` on 127.0.0.1.
- Fixtures are recorded from the live API and sanitised: no request ids, exit IPs, session ids, balances or keys. Keep page content to public sample sites.
- Parameters must be documented request fields of the endpoint (`src/scrapy_quanticdata/params.py`, from https://quanticdata.io/docs/openapi.json). Update the lists when the API adds a field.
- Keep the middleware reactor-agnostic: no reactor imports at module level, no blocking calls.
- Settings, meta keys and the `quanticdata_response` fields are public: renaming or removing one is a major release.
- User-facing changes need a CHANGELOG entry under "Unreleased".

## Design notes

The plugin is a downloader middleware rather than a download handler: it rewrites a routed request into an API call that keeps the callback, meta and priority, and rebuilds the target response in `process_response`. This keeps Scrapy's HTTP stack (proxies, cache, retries) for the API call and needs no Twisted-specific code. API calls set `download_slot` to the target host, `dont_obey_robotstxt`, `dont_filter` and `Accept-Encoding: identity` (the middleware reads the answer before `HttpCompressionMiddleware` would decode it).
