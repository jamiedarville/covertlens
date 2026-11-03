"""CL-66: the static Pyodide Analyze page works offline in a real browser.

Acceptance: after the first load the page analyses a fixture without
any network request to a server. The test serves `dist-static/` from a
local HTTP server, loads the page once (the service worker precaches
every file), stops the server, switches the browser offline, reloads,
and analyses a built-in example; every response must come from the
service worker.

Needs `npm run build:static` (app/frontend), Playwright and a Chromium
(`COVERTLENS_CHROMIUM`, default /usr/bin/chromium); skips otherwise.
Marked slow: it boots Pyodide in a browser.
"""

import functools
import http.server
import os
import threading
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parent.parent / "app" / "frontend" / "dist-static"
CHROMIUM = os.environ.get("COVERTLENS_CHROMIUM", "/usr/bin/chromium")

pytestmark = pytest.mark.slow


@pytest.fixture()
def site_server():
    if not (SITE / "index.html").is_file():
        pytest.skip("static build missing: run npm run build:static in app/frontend")
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(SITE)
    )
    handler.log_message = lambda *args: None  # type: ignore[attr-defined]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    seen: list[str] = []
    original = handler.func.do_GET  # type: ignore[attr-defined]

    def counting_get(self):  # noqa: ANN001
        seen.append(self.path)
        return original(self)

    handler.func.do_GET = counting_get  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, seen
    server.shutdown()
    handler.func.do_GET = original  # type: ignore[attr-defined]


def test_static_page_analyses_a_fixture_offline(site_server):
    sync_api = pytest.importorskip("playwright.sync_api")
    if not Path(CHROMIUM).exists():
        pytest.skip(f"no Chromium at {CHROMIUM}")
    server, seen = site_server
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
        context = browser.new_context()
        page = context.new_page()
        page.goto(url)
        status = page.get_by_test_id("runtime-status")
        status.filter(has_text="offline cache: ready").wait_for(timeout=60_000)
        status.filter(has_text="Python runtime ready").wait_for(timeout=120_000)
        assert any(path.endswith("pyodide.asm.wasm") for path in seen)

        # Offline from here on: the HTTP server stops and the browser
        # has no network, so anything not cached would fail.
        server.shutdown()
        context.set_offline(True)
        requests_before = len(seen)
        responses = []
        page.on("response", lambda r: responses.append(r))
        page.reload()
        status.filter(has_text="Python runtime ready").wait_for(timeout=120_000)
        page.locator("#fixture-select").select_option(index=2)
        page.get_by_role("button", name="Analyze example").click()
        page.get_by_role("heading", name="Result", exact=False).wait_for(
            timeout=120_000
        )
        assert page.locator(".results").get_by_text("Verdict", exact=False).count() >= 1
        assert len(seen) == requests_before, "a request reached the server"
        assert responses, "the reload produced no responses"
        assert all(r.from_service_worker for r in responses if r.url.startswith(url))
        csp = page.locator('meta[http-equiv="Content-Security-Policy"]').get_attribute(
            "content"
        )
        assert "connect-src 'self'" in csp
        browser.close()
