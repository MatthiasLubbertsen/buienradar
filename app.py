"""Serves screenshots of the rain graph on buienradar.nl as PNG.

    python app.py [port]      ->  http://localhost:8000/putten.png
                                  http://localhost:8000/barneveld.png
                                  add ?theme=light for the light variant

The graph is the real `.area-graph` element of the Buienradar weather page,
captured with headless Chromium (Playwright).

Debug: BR_MOCK_RAIN=1 injects fake rain into the graph request so the
rendering can be checked on a dry day.
"""
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

# slug and Buienradar location id (https://location.buienradar.nl/1.1/location/search?query=...)
PLACES = {
    "putten": 2748392,
    "barneveld": 2759407,
}
PAGE = "https://www.buienradar.nl/weer/{}/nl/{}"
CACHE_SECONDS = 120
CHROMIUM_PATH = os.environ.get("CHROMIUM_PATH") or None  # None = Playwright's own browser
MOCK_RAIN = os.environ.get("BR_MOCK_RAIN") == "1"

# Hide the consent wall and the hover pointer + "12:45 / 0 mm/u" tooltip that covers the graph.
HIDE_CSS = ".payok__wrap, #onetrust-consent-sdk, .preciptation-line { display: none !important; }"

_cache = {}
_lock = threading.Lock()  # one browser at a time; renders are cached anyway


def mock_rain(route):
    """Replace the forecast with a fake rain shower (debug only)."""
    import json

    resp = route.fetch()
    data = resp.json()
    pts = data["forecasts"]
    shape = [0, 5, 15, 30, 45, 60, 75, 85, 70, 50, 30, 15, 5, 0]
    for i, pct in enumerate(shape):
        j = len(pts) // 2 + i
        if j < len(pts):
            pts[j]["percentageValue"] = float(pct)
            pts[j]["dataValue"] = round(pct / 25, 2)
    route.fulfill(response=resp, body=json.dumps(data))


def capture(place, theme):
    url = PAGE.format(place, PLACES[place])
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROMIUM_PATH, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        try:
            page = browser.new_page(
                viewport={"width": 1280, "height": 1000},
                device_scale_factor=2,
                locale="nl-NL",
                timezone_id="Europe/Amsterdam",
                color_scheme=theme,
            )
            if MOCK_RAIN:
                page.route("**/RainHistoryForecast*", mock_rain)
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.add_style_tag(content=HIDE_CSS)
            graph = page.locator(".area-graph").first
            graph.wait_for(timeout=30000)
            # wait until the SVG has been drawn, then let the fade-in animation settle
            page.wait_for_selector(".area-graph svg path", state="attached", timeout=30000)
            graph.scroll_into_view_if_needed()
            page.wait_for_timeout(1500)
            return graph.screenshot(type="png")
        finally:
            browser.close()


def get_png(place, theme):
    key = (place, theme)
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        png = capture(place, theme)
        _cache[key] = (time.time(), png)
        return png


INDEX = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<title>Buienradar</title><body style="background:#111;color:#eee;font-family:sans-serif;text-align:center">
{}</body>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        path = url.path.strip("/")
        if path == "":
            body = INDEX.format("".join(
                f'<h2>{p.title()}</h2><img src="/{p}.png" style="max-width:100%">' for p in PLACES)).encode()
            return self.send(200, "text/html; charset=utf-8", body)
        name = path.removesuffix(".png").lower()
        if name not in PLACES:
            return self.send(404, "text/plain", b"Unknown place. Try: " + ", ".join(PLACES).encode())
        theme = "light" if parse_qs(url.query).get("theme") == ["light"] else "dark"
        try:
            self.send(200, "image/png", get_png(name, theme), {"Cache-Control": f"max-age={CACHE_SECONDS}"})
        except Exception as e:  # upstream / browser failure
            self.send(502, "text/plain", f"Could not capture the Buienradar graph: {e}".encode())

    def send(self, code, ctype, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"Serving on http://localhost:{port}/")
    ThreadingHTTPServer(("", port), Handler).serve_forever()
