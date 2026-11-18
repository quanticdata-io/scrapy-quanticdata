"""Local stand-in for the two QuanticData endpoints this plugin calls.

Run it to try the example spider without a key or network:

    python tests/mock_api.py            # http://127.0.0.1:4012/v1
    QUANTICDATA_API_KEY=qd_test_123 QUANTICDATA_API_BASE=http://127.0.0.1:4012/v1 \\
        scrapy runspider examples/quotes_spider.py -s QUANTICDATA_ROBOTSTXT=unlock -O quotes.json

Every page answers with the recorded page 2 of quotes.toscrape.com, and
robots.txt allows everything. Responses follow the documented envelope.
"""

from __future__ import annotations

import base64
import gzip
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"
PAGE = (FIXTURES / "quotes-page-2.html").read_text(encoding="utf-8")
ROBOTS = "User-agent: *\nAllow: /\n"


class MockState:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    state: MockState

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send(self, status: int, data: dict[str, Any]) -> None:
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        # Like most HTTP servers, compress when the client accepts it.
        if "gzip" in (self.headers.get("Accept-Encoding") or ""):
            raw = gzip.compress(raw)
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        with self.state.lock:
            self.state.requests.append({"path": self.path, "authorization": self.headers.get("Authorization"), "body": body})
        if self.headers.get("Authorization", "") != "Bearer qd_test_123":
            self._send(401, {"type": "error", "message": "Missing or unknown API key."})
            return
        url = str(body.get("url", ""))
        is_robots = url.endswith("/robots.txt")
        text = ROBOTS if is_robots else PAGE
        ctype = "text/plain; charset=utf-8" if is_robots else "text/html; charset=utf-8"
        if self.path == "/v1/scraper/unlock":
            payload = {
                "request_id": f"req_mock_{len(self.state.requests)}",
                "status": 200,
                "headers": {"content-type": [ctype]},
                "bodyBase64": base64.b64encode(text.encode()).decode(),
                "body": text,
                "finalUrl": url,
                "contentType": ctype,
                "attempts": 1,
                "blocked": False,
                "rendered": False,
                "escalated": False,
                "mode": "auto",
                "tier_served": "tls",
                "format": "html",
                "tier": "premium",
            }
            self._send(200, {"type": "response", "message": "Unlocker request successful", "payload": payload})
        elif self.path == "/v1/scraper/extract":
            payload = {"url": url, "finalUrl": url, "status": 200, "format": body.get("format", "markdown"), "content": text}
            self._send(200, {"type": "response", "message": "Extraction successful", "payload": payload})
        else:
            self._send(404, {"type": "error", "message": "Not found"})


def serve(port: int = 0) -> tuple[ThreadingHTTPServer, MockState]:
    state = MockState()
    handler = type("BoundHandler", (Handler,), {"state": state})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4012
    srv, _ = serve(port)
    print(f"QuanticData mock API on http://127.0.0.1:{port}/v1 (Ctrl+C to stop)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
