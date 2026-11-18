"""Downloader middleware that sends Scrapy requests through the QuanticData API.

How it works: ``process_request`` turns a request into a ``POST`` to the API
(``/scraper/unlock`` or ``/scraper/extract``) that keeps the callback, errback,
priority and meta of the original request. The API request goes back to the
scheduler, is downloaded like any other request, and ``process_response``
rebuilds the target's response from the API's JSON answer, attached to a copy
of the original request. Spiders see an ordinary ``HtmlResponse`` or
``TextResponse`` for the URL they asked for.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from scrapy import Request
from scrapy.http import Headers, HtmlResponse, Response, TextResponse
from scrapy.responsetypes import responsetypes
from scrapy.utils.defer import maybe_deferred_to_future

from ._version import __version__
from .params import EXTRACT, EXTRACT_TEXT_FORMATS, UNLOCK, check_params

if TYPE_CHECKING:
    from scrapy import Spider
    from scrapy.crawler import Crawler
    from scrapy.settings import BaseSettings
    from scrapy.statscollectors import StatsCollector

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.quanticdata.io/v1"
META_KEY = "quanticdata"
RESULT_META_KEY = "quanticdata_response"
_STATE_KEY = "_quanticdata"
# Slot stamp set by recent Scrapy versions; removed so that download_slot is honoured.
_SLOT_STAMP_KEY = "_download_slot_stamp"

#: Headers never forwarded to the target: transport headers of the Scrapy request.
_TRANSPORT_HEADERS = frozenset(
    {
        "accept-encoding",
        "content-length",
        "host",
        "connection",
        "transfer-encoding",
        "proxy-authorization",
        "proxy-connection",
        "te",
    }
)
#: Headers Scrapy adds by default; not forwarded unless QUANTICDATA_FORWARD_HEADERS is "all".
_DEFAULT_SCRAPY_HEADERS = frozenset({"user-agent", "accept", "accept-language"})
#: Response headers that describe the API transport, not the target's body.
_DROP_RESPONSE_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})

_MAX_FORWARDED_HEADERS = 32
_MISSING = "__missing__"


class QuanticDataError(Exception):
    """Base class of the errors this plugin raises (passed to the request's errback)."""


class QuanticDataConfigError(QuanticDataError, ValueError):
    """Missing API key, unknown backend or an undocumented parameter."""


class QuanticDataAPIError(QuanticDataError):
    """The API answered with an error envelope (HTTP status other than 200)."""

    def __init__(self, status: int, message: str, payload: Mapping[str, Any] | None = None) -> None:
        self.status = status
        self.message = message
        self.payload: dict[str, Any] = dict(payload or {})
        self.code: str | None = self.payload.get("code")
        super().__init__(f"QuanticData API {status}{f' {self.code}' if self.code else ''}: {message}")


async def _twisted_sleep(seconds: float) -> None:
    # Imported here: importing the reactor at module level would install it too early.
    from twisted.internet import reactor  # noqa: PLC0415
    from twisted.internet.task import deferLater  # noqa: PLC0415

    await maybe_deferred_to_future(deferLater(reactor, seconds, lambda: None))


class QuanticDataMiddleware:
    """Add to ``DOWNLOADER_MIDDLEWARES`` (priority 725 recommended)."""

    def __init__(
        self,
        settings: BaseSettings,
        stats: StatsCollector | None = None,
        sleep: Callable[[float], Awaitable[None]] = _twisted_sleep,
    ) -> None:
        self.api_key: str = settings.get("QUANTICDATA_API_KEY") or os.environ.get("QUANTICDATA_API_KEY", "")
        base = settings.get("QUANTICDATA_API_BASE") or os.environ.get("QUANTICDATA_API_BASE") or DEFAULT_API_BASE
        self.api_base: str = str(base).rstrip("/")
        self.enabled: bool = settings.getbool("QUANTICDATA_ENABLED", False)
        self.backend: str = settings.get("QUANTICDATA_BACKEND", UNLOCK)
        self.default_params: dict[str, dict[str, Any]] = {
            UNLOCK: check_params(UNLOCK, settings.getdict("QUANTICDATA_UNLOCK_PARAMS")),
            EXTRACT: check_params(EXTRACT, settings.getdict("QUANTICDATA_EXTRACT_PARAMS")),
        }
        self.max_retries: int = settings.getint("QUANTICDATA_MAX_RETRIES", 3)
        self.retry_statuses: set[int] = {int(s) for s in settings.getlist("QUANTICDATA_RETRY_STATUSES", [429, 500, 503, 504])}
        self.max_retry_delay: float = settings.getfloat("QUANTICDATA_MAX_RETRY_DELAY", 60.0)
        self.robotstxt: str = settings.get("QUANTICDATA_ROBOTSTXT", "direct")
        self.forward_headers: str = settings.get("QUANTICDATA_FORWARD_HEADERS", "custom")
        self.stats = stats
        self._sleep = sleep
        if self.backend not in (UNLOCK, EXTRACT):
            raise QuanticDataConfigError(f"QUANTICDATA_BACKEND must be 'unlock' or 'extract', not {self.backend!r}")
        if self.robotstxt not in ("direct", "unlock"):
            raise QuanticDataConfigError("QUANTICDATA_ROBOTSTXT must be 'direct' or 'unlock'")
        if self.forward_headers not in ("custom", "all", "none"):
            raise QuanticDataConfigError("QUANTICDATA_FORWARD_HEADERS must be 'custom', 'all' or 'none'")

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> QuanticDataMiddleware:
        return cls(crawler.settings, crawler.stats)

    # Routing ----------------------------------------------------------------

    def _inc(self, key: str) -> None:
        if self.stats is not None:
            self.stats.inc_value(f"quanticdata/{key}")

    def _is_api_request(self, request: Request) -> bool:
        return _STATE_KEY in request.meta and request.url.startswith(self.api_base + "/")

    @staticmethod
    def _is_robotstxt(request: Request) -> bool:
        if request.meta.get("is_robotstxt_request"):
            return True
        return bool(request.meta.get("dont_obey_robotstxt")) and urlparse(request.url).path == "/robots.txt"

    def route(self, request: Request) -> tuple[str, dict[str, Any]] | None:
        """Backend and parameters for ``request``, or ``None`` to download it directly."""
        if urlparse(request.url).scheme not in ("http", "https"):
            return None
        if self._is_robotstxt(request):
            return (UNLOCK, dict(self.default_params[UNLOCK])) if self.robotstxt == "unlock" else None
        option = request.meta.get(META_KEY)
        if option is False or (option is None and not self.enabled):
            return None
        params: dict[str, Any] = {}
        backend = self.backend
        if isinstance(option, Mapping):
            params = dict(option)
            backend = params.pop("backend", backend)
        elif option not in (None, True):
            raise QuanticDataConfigError(f"meta['{META_KEY}'] must be True, False or a dict, not {option!r}")
        merged = {**self.default_params.get(backend, {}), **check_params(backend, params)}
        return backend, merged

    # Request ----------------------------------------------------------------

    def _target_headers(self, request: Request) -> dict[str, str]:
        if self.forward_headers == "none":
            return {}
        out: dict[str, str] = {}
        for raw_name, raw_values in request.headers.items():
            name = raw_name.decode("latin-1") if isinstance(raw_name, bytes) else str(raw_name)
            lower = name.lower()
            if lower in _TRANSPORT_HEADERS:
                continue
            if self.forward_headers == "custom" and lower in _DEFAULT_SCRAPY_HEADERS:
                continue
            values = [v.decode("latin-1") if isinstance(v, bytes) else str(v) for v in raw_values]
            out[name] = ("; " if lower == "cookie" else ", ").join(values)
        if len(out) > _MAX_FORWARDED_HEADERS:
            raise QuanticDataConfigError(f"The API accepts at most {_MAX_FORWARDED_HEADERS} headers per request")
        return out

    def build_api_request(self, request: Request, backend: str, params: Mapping[str, Any]) -> Request:
        if not self.api_key:
            raise QuanticDataConfigError(
                "QUANTICDATA_API_KEY is not set (Scrapy setting or environment variable); "
                f"cannot send {request.url} through the QuanticData API"
            )
        body: dict[str, Any] = {"url": request.url}
        headers = self._target_headers(request)
        if backend == UNLOCK:
            body["method"] = request.method
            if headers:
                body["headers"] = headers
            if request.body:
                try:
                    body["body"] = request.body.decode("utf-8")
                except UnicodeDecodeError:
                    body["bodyBase64"] = base64.b64encode(request.body).decode("ascii")
        else:
            if request.method != "GET":
                raise QuanticDataConfigError(f"The extract backend only fetches GET requests, not {request.method}")
            if headers:
                body["headers"] = headers
        body.update(params)
        state = dict(request.meta.get(_STATE_KEY) or {})
        state.update(
            {
                "backend": backend,
                "url": request.url,
                "method": request.method,
                "headers": [(k, list(v)) for k, v in request.headers.items()],
                "body": request.body,
                "format": params.get("format"),
                "retries": state.get("retries", 0),
                "dont_obey_robotstxt": request.meta.get("dont_obey_robotstxt", _MISSING),
            }
        )
        meta = dict(request.meta)
        meta.pop(_SLOT_STAMP_KEY, None)
        meta[_STATE_KEY] = state
        # robots.txt was already checked for the target; the API host is not crawled.
        meta["dont_obey_robotstxt"] = True
        # Keep per-site politeness: the API request uses the target's download slot.
        host = urlparse(request.url).hostname
        if host:
            meta.setdefault("download_slot", host)
        return cast(
            "Request",
            request.replace(
                url=f"{self.api_base}/scraper/{backend}",
                method="POST",
                body=json.dumps(body),
                headers=Headers(
                    {
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        # This middleware reads the API answer before HttpCompressionMiddleware (590) would
                        # decode it, so ask for an uncompressed body.
                        "Accept-Encoding": "identity",
                        "User-Agent": f"scrapy-quanticdata/{__version__}",
                    }
                ),
                meta=meta,
                dont_filter=True,
            ),
        )

    def process_request(self, request: Request, spider: Spider | None = None) -> Request | None:
        if self._is_api_request(request):
            return None
        routed = self.route(request)
        if routed is None:
            return None
        backend, params = routed
        self._inc("requests")
        self._inc(f"requests/{backend}")
        return self.build_api_request(request, backend, params)

    # Response ---------------------------------------------------------------

    def _original_request(self, api_request: Request, state: Mapping[str, Any]) -> Request:
        meta = {k: v for k, v in api_request.meta.items() if k != _STATE_KEY}
        if state.get("dont_obey_robotstxt", _MISSING) is _MISSING:
            meta.pop("dont_obey_robotstxt", None)
        else:
            meta["dont_obey_robotstxt"] = state["dont_obey_robotstxt"]
        return cast(
            "Request",
            api_request.replace(
                url=state["url"],
                method=state["method"],
                headers=Headers(state["headers"]),
                body=state["body"],
                meta=meta,
            ),
        )

    @staticmethod
    def _retry_delay(response: Response, attempt: int) -> float:
        value = response.headers.get(b"Retry-After")
        if value:
            try:
                return max(0.0, float(value.decode("latin-1")))
            except ValueError:
                pass
        return float(2**attempt)

    async def process_response(self, request: Request, response: Response, spider: Spider | None = None) -> Request | Response:
        if not self._is_api_request(request):
            return response
        state: dict[str, Any] = request.meta[_STATE_KEY]
        if response.status != 200:
            return await self._handle_error(request, response, state)
        try:
            envelope = json.loads(response.body)
            payload = envelope["payload"]
        except (ValueError, KeyError, TypeError) as exc:
            raise QuanticDataAPIError(response.status, f"Unexpected answer from the API: {exc}") from exc
        original = self._original_request(request, state)
        info = {k: v for k, v in payload.items() if k not in ("body", "bodyBase64", "content", "headers")}
        info["backend"] = state["backend"]
        original.meta[RESULT_META_KEY] = info
        self._inc(f"responses/{payload.get('status')}")
        if payload.get("blocked"):
            self._inc("blocked")
        if state["backend"] == UNLOCK:
            return self._unlock_response(original, payload, state)
        return self._extract_response(original, payload, state)

    async def _handle_error(self, request: Request, response: Response, state: dict[str, Any]) -> Request:
        message = response.text if isinstance(response, TextResponse) else response.body.decode("utf-8", "replace")
        payload: dict[str, Any] = {}
        try:
            envelope = json.loads(response.body)
            message = str(envelope.get("message") or message)
            payload = envelope.get("payload") or {}
        except ValueError:
            pass
        self._inc(f"api_errors/{response.status}")
        attempt = int(state.get("retries", 0))
        if response.status in self.retry_statuses and attempt < self.max_retries:
            delay = self._retry_delay(response, attempt)
            if delay <= self.max_retry_delay:
                logger.debug("QuanticData API %s for %s, retry %d in %.1fs", response.status, state["url"], attempt + 1, delay)
                self._inc("retries")
                await self._sleep(delay)
                retry = cast("Request", request.copy())
                retry.meta[_STATE_KEY] = {**state, "retries": attempt + 1}
                return retry
        raise QuanticDataAPIError(response.status, message, payload)

    @staticmethod
    def _headers(raw: Any) -> Headers:
        headers = Headers()
        if isinstance(raw, Mapping):
            for name, value in raw.items():
                if str(name).lower() in _DROP_RESPONSE_HEADERS:
                    continue
                values = value if isinstance(value, list) else [value]
                headers[str(name)] = [str(v) for v in values]
        return headers

    def _unlock_response(self, original: Request, payload: Mapping[str, Any], state: Mapping[str, Any]) -> Response:
        url = str(payload.get("finalUrl") or original.url)
        status = int(payload.get("status") or 200)
        headers = self._headers(payload.get("headers"))
        fmt = payload.get("format") or state.get("format")
        if fmt in ("markdown", "text") and isinstance(payload.get("body"), str):
            ctype = "text/markdown" if fmt == "markdown" else "text/plain"
            headers[b"Content-Type"] = f"{ctype}; charset=utf-8"
            return TextResponse(
                url=url, status=status, headers=headers, body=payload["body"].encode("utf-8"), encoding="utf-8", request=original
            )
        body = base64.b64decode(payload.get("bodyBase64") or "")
        cls = responsetypes.from_args(headers=headers, url=url, body=body)
        return cls(url=url, status=status, headers=headers, body=body, request=original)

    def _extract_response(self, original: Request, payload: Mapping[str, Any], state: Mapping[str, Any]) -> Response:
        url = str(payload.get("finalUrl") or payload.get("url") or original.url)
        status = int(payload.get("status") or 200)
        fmt = str(payload.get("format") or state.get("format") or "markdown")
        ctype = EXTRACT_TEXT_FORMATS.get(fmt, "text/plain")
        headers = Headers({"Content-Type": f"{ctype}; charset=utf-8"})
        body = str(payload.get("content") or "").encode("utf-8")
        cls = HtmlResponse if ctype == "text/html" else TextResponse
        return cls(url=url, status=status, headers=headers, body=body, encoding="utf-8", request=original)
