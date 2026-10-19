"""Tiny server that serves Buienradar rain graphs as PNG.

    python app.py [port]      ->  http://localhost:8000/putten.png
                                  http://localhost:8000/barneveld.png
"""
import io
import json
import sys
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageDraw, ImageFont

PLACES = {
    "putten": (52.2575, 5.6),
    "barneveld": (52.1403, 5.5875),
}
API = "https://graphdata.buienradar.nl/2.0/forecast/geo/RainHistoryForecast?lat={}&lon={}"
CACHE_SECONDS = 120

W, H, S = 720, 300, 2  # output size, supersampling factor
BG, GRID, FG, BAR, BASE = "#1c1c1c", "#4a4a4a", "#f2f2f2", "#ffffff", "#2f5f8a"
FONT_PATHS = [
    "/usr/share/fonts/opentype/inter/Inter-Regular.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "DejaVuSans.ttf",
    "Arial.ttf",
]
LEVELS = [(40, "Licht"), (70, "Matig"), (100, "Zwaar")]  # evenly spaced, like buienradar.nl

_cache = {}


def font(size):
    for p in FONT_PATHS:
        try:
            return ImageFont.truetype(p, size * S)
        except OSError:
            pass
    return ImageFont.load_default(size * S)


def fetch(place):
    hit = _cache.get(place)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    lat, lon = PLACES[place]
    req = urllib.request.Request(API.format(lat, lon), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)["forecasts"]
    _cache[place] = (time.time(), data)
    return data


def y_for(value, y0, step):
    """Piecewise scale: 0 -> baseline, 40/70/100 -> gridlines 1/2/3, evenly spaced."""
    pts = [0, 40, 70, 100]
    value = max(0, min(100, value))
    for i in range(3):
        if value <= pts[i + 1]:
            frac = (value - pts[i]) / (pts[i + 1] - pts[i])
            return y0 - (i + frac) * step
    return y0 - 3 * step


def render(place):
    data = fetch(place)
    times = [datetime.fromisoformat(d["datetime"]) for d in data]
    vals = [d["value"] for d in data]

    img = Image.new("RGB", (W * S, H * S), BG)
    d = ImageDraw.Draw(img)
    left, right, y0, step = 122 * S, 679 * S, 208 * S, 42 * S

    for i, (_, label) in enumerate(LEVELS, 1):
        y = y0 - i * step
        d.line([(left, y), (right, y)], fill=GRID, width=S)
        d.text((40 * S, y), label, font=font(22), fill="#bdbdbd", anchor="lm")

    n = len(data)
    slot = (right - left) / n
    bw = max(2, int(slot * 0.55))
    for i, v in enumerate(vals):
        if v > 0:
            x = left + (i + 0.5) * slot
            d.rectangle([x - bw / 2, y_for(v, y0, step), x + bw / 2, y0], fill=BAR)

    d.line([(left, y0), (right, y0)], fill=BASE, width=S)

    # x labels every hour, anchored at the first slot's minutes (e.g. 12:20, 13:20 ...)
    f = font(24)
    start = next((i for i, t in enumerate(times) if t.minute % 20 == 0 and t.minute == times[0].minute), 0)
    for i in range(start, n, 12):
        text = times[i].strftime("%H:%M")
        x = min(left + i * slot, right - d.textlength(text, font=f))  # keep inside the plot
        d.text((x, 247 * S), text, font=f, fill=FG, anchor="lm")

    out = img.resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


INDEX = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<title>Buienradar</title><body style="background:#111;color:#eee;font-family:sans-serif;text-align:center">
{}</body>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0].strip("/")
        if path == "":
            body = INDEX.format("".join(
                f'<h2>{p.title()}</h2><img src="/{p}.png" style="max-width:100%">' for p in PLACES)).encode()
            return self.send(200, "text/html; charset=utf-8", body)
        name = path.removesuffix(".png").lower()
        if name not in PLACES:
            return self.send(404, "text/plain", b"Unknown place. Try: " + ", ".join(PLACES).encode())
        try:
            self.send(200, "image/png", render(name), {"Cache-Control": f"max-age={CACHE_SECONDS}"})
        except Exception as e:  # upstream failure
            self.send(502, "text/plain", f"Could not fetch Buienradar data: {e}".encode())

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
