"""End to end: the example spider runs in a real Scrapy crawl against the local mock API.

The crawl runs in a subprocess (a Twisted reactor cannot be restarted in one
process). Every request, robots.txt included, goes to the mock on 127.0.0.1,
so nothing reaches the network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from .mock_api import serve

ROOT = Path(__file__).parent.parent
REACTORS = {
    "asyncio": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
    "select": "twisted.internet.selectreactor.SelectReactor",
}


@pytest.mark.parametrize("reactor", list(REACTORS))
def test_example_spider_through_mock_api(tmp_path: Path, reactor: str) -> None:
    server, state = serve()
    port = server.server_address[1]
    out = tmp_path / "quotes.json"
    env = {
        **os.environ,
        "QUANTICDATA_API_KEY": "qd_test_123",
        "QUANTICDATA_API_BASE": f"http://127.0.0.1:{port}/v1",
    }
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "scrapy",
                "runspider",
                str(ROOT / "examples" / "quotes_spider.py"),
                "-O",
                str(out),
                "-s",
                "QUANTICDATA_ROBOTSTXT=unlock",
                "-s",
                "DOWNLOAD_DELAY=0",
                "-s",
                f"TWISTED_REACTOR={REACTORS[reactor]}",
                "-s",
                "TELNETCONSOLE_ENABLED=0",
            ],
            env=env,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    finally:
        server.shutdown()
    assert proc.returncode == 0, proc.stderr[-3000:]
    items = json.loads(out.read_text(encoding="utf-8"))
    # page/1/ and page/3/ both answer with the recorded page 2 (two quotes each);
    # page/3/ links to itself and the duplicate filter stops there.
    assert [i["author"] for i in items] == ["J.K. Rowling", "Albert Einstein"] * 2
    assert {i["url"] for i in items} == {"https://quotes.toscrape.com/page/1/", "https://quotes.toscrape.com/page/3/"}
    urls = [r["body"]["url"] for r in state.requests]
    assert urls[0] == "https://quotes.toscrape.com/robots.txt"
    assert sorted(urls[1:]) == ["https://quotes.toscrape.com/page/1/", "https://quotes.toscrape.com/page/3/"]
    assert all(r["path"] == "/v1/scraper/unlock" for r in state.requests)
    assert all(r["authorization"] == "Bearer qd_test_123" for r in state.requests)
    assert all(r["body"].get("country") == "us" for r in state.requests[1:])
    assert all("qd_test_123" not in json.dumps(r["body"]) for r in state.requests)
