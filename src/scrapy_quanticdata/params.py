"""Request fields of the two QuanticData endpoints this plugin calls.

The lists mirror the request bodies of ``POST /scraper/unlock`` and
``POST /scraper/extract`` in the public OpenAPI document
(https://quanticdata.io/docs/openapi.json). Fields the middleware fills in
itself from the Scrapy request are reserved and cannot be passed as parameters.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

UNLOCK = "unlock"
EXTRACT = "extract"
BACKENDS = (UNLOCK, EXTRACT)

UNLOCK_FIELDS = frozenset(
    {
        "url",
        "method",
        "headers",
        "body",
        "bodyBase64",
        "tier",
        "mode",
        "format",
        "max_bytes",
        "timeout_ms",
        "fail_on_block",
        "actions",
        "cache_ttl",
        "country",
        "state",
        "city",
        "rotation",
        "sessionId",
        "sessionDuration",
        "tlsProfile",
        "mobile",
        "render",
        "autoRender",
        "keepHeaders",
        "successStatusCodes",
        "timeoutMs",
        "failOnBlock",
        "waitForSelector",
        "waitMs",
        "returnCookies",
        "cookies",
    }
)

EXTRACT_FIELDS = frozenset(
    {
        "url",
        "html",
        "format",
        "formats",
        "data_format",
        "engine",
        "autoEscalate",
        "tlsProfile",
        "render",
        "mobile",
        "waitMs",
        "waitForSelector",
        "scrollToBottom",
        "actions",
        "screenshot",
        "xhr",
        "expect",
        "extract",
        "presetId",
        "contentMode",
        "content_modes",
        "fullPage",
        "mode",
        "include_links",
        "app_state",
        "parser",
        "reveal_hidden",
        "output",
        "frontmatter",
        "links_mode",
        "toc",
        "max_tokens",
        "images_mode",
        "query",
        "highlights",
        "chunk",
        "summary_sections",
        "ai_prompt",
        "ai_schema",
        "headers",
        "cookies",
        "country",
        "state",
        "city",
        "rotation",
        "sessionId",
        "sessionDuration",
    }
)

#: Filled in by the middleware from the Scrapy request.
RESERVED = {
    UNLOCK: frozenset({"url", "method", "headers", "body", "bodyBase64"}),
    EXTRACT: frozenset({"url", "html", "headers"}),
}

FIELDS = {UNLOCK: UNLOCK_FIELDS, EXTRACT: EXTRACT_FIELDS}

#: Formats of ``POST /scraper/extract`` that come back as page content.
EXTRACT_TEXT_FORMATS = {"html": "text/html", "raw": "text/html", "markdown": "text/markdown", "text": "text/plain"}


def check_params(backend: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """Returns a copy of ``params`` after checking every key against the documented fields."""
    if backend not in BACKENDS:
        raise ValueError(f"Unknown QuanticData backend {backend!r}; use one of {', '.join(BACKENDS)}")
    unknown = sorted(set(params) - FIELDS[backend])
    if unknown:
        raise ValueError(f"Not a documented field of the {backend} endpoint: {', '.join(unknown)}")
    reserved = sorted(set(params) & RESERVED[backend])
    if reserved:
        raise ValueError(
            f"{', '.join(reserved)} {'is' if len(reserved) == 1 else 'are'} taken from the Scrapy request; "
            "set them on the Request instead"
        )
    if backend == EXTRACT and "format" in params and params["format"] not in EXTRACT_TEXT_FORMATS:
        raise ValueError(f"extract format must be one of {', '.join(EXTRACT_TEXT_FORMATS)}")
    return dict(params)
