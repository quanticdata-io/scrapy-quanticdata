# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems. Email **hello@quanticdata.io** with the subject "Security: scrapy-quanticdata" and include a description, steps to reproduce and the version you use. We acknowledge reports within 3 business days and keep you informed until a fix is released.

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | yes |

## API keys

Never commit an API key. The middleware reads `QUANTICDATA_API_KEY` from the Scrapy settings or the environment and sends it only in the `Authorization` header of requests to the API base URL. It never adds it to the headers or body forwarded to the target site. Headers you set on your own requests (including `Authorization` and `Cookie`) are forwarded to the target, as with a direct download. If a key leaks, rotate it on the API keys page of the QuanticData dashboard.
