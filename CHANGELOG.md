# Changelog

## Unreleased

## 0.1.0 (2026-11-18)

- `QuanticDataMiddleware`: sends requests through `POST /scraper/unlock` (Web Unlocker) or `POST /scraper/extract` (scrape API) and returns ordinary Scrapy responses.
- Routing for every request (`QUANTICDATA_ENABLED`) or per request (`meta["quanticdata"]`), per-backend default parameters checked against the documented request fields.
- Retries of 429 and 5xx API answers honouring `Retry-After`; errors raised as `QuanticDataAPIError` with the API's `code`.
- Per-site download slots kept for API calls; robots.txt fetched directly or through the Web Unlocker (`QUANTICDATA_ROBOTSTXT`).
