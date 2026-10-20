"""Serves the Buienradar rain graph (past + next ~2 hours) as a PNG.

    python app.py [port]      ->  http://localhost:8000/putten.png
                                  http://localhost:8000/barneveld.png
                                  add ?theme=light for the light variant

It fetches the same data the graph on buienradar.nl uses and draws the graph
with Pillow, following the page's own SVG: a 332x100 viewBox, y = 100 - percentage,
gridlines at 25/50/75 %, and cubic curves with flat tangents through the points.
No browser involved.
"""
import io
import json
import os
import re
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw, ImageFont

# slug -> (lat, lon) rounded to 2 decimals, as the site does (see
# https://location.buienradar.nl/1.1/location/search?query=putten); the API ignores finer precision
PLACES = {
    "putten": (52.26, 5.61),
    "barneveld": (52.14, 5.58),
}
API = "https://graphdata.buienradar.nl/3.0/forecast/geo/RainHistoryForecast?lat={}&lon={}&language=nl"
FONT_PAGE = "https://www.buienradar.nl/weer/putten/nl/2748392"
FONT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "rtlunitedtext-regular.woff2")
FALLBACK_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "DejaVuSans.ttf",
    "Arial.ttf",
]
DATA_CACHE_SECONDS = 60
UA = {"User-Agent": "Mozilla/5.0"}

# Layout in CSS pixels, copied from the page: legend column, 332x100 SVG stretched to 667x130, time row.
W, H = 715, 162
SVG_X, SVG_W, SVG_H = 48, 666.66, 130
VB_W = 332
PAD = 16   # CSS px of background around the graph
SCALE = 2  # output pixels per CSS pixel
SS = 2     # extra supersampling for smooth edges
THEMES = {
    "dark": dict(bg=(28, 28, 28), grid=(195, 195, 195), legend=(195, 195, 195), text=(255, 255, 255), now=(255, 255, 255)),
    "light": dict(bg=(255, 255, 255), grid=(117, 117, 117), legend=(117, 117, 117), text=(21, 43, 129), now=(21, 43, 129)),
}

DAYS = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]

_data_cache = {}
_font_lock = threading.Lock()


def http_get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
        return r.read()


def fetch(place):
    hit = _data_cache.get(place)
    if hit and time.time() - hit[0] < DATA_CACHE_SECONDS:
        return hit[1]
    data = json.loads(http_get(API.format(*PLACES[place])))
    _data_cache[place] = (time.time(), data)
    return data


def ensure_font_file():
    """Buienradar's own typeface (RTL United), fetched once from their site and kept in ./fonts."""
    with _font_lock:
        if os.path.exists(FONT_FILE):
            return FONT_FILE
        try:
            html = http_get(FONT_PAGE).decode("utf-8", "replace")
            path = re.search(r"(/frontend/[^\"' (\\]*rtlunitedtext-regular\.woff2)", html).group(1)
            os.makedirs(os.path.dirname(FONT_FILE), exist_ok=True)
            with open(FONT_FILE, "wb") as f:
                f.write(http_get("https://www.buienradar.nl" + path))
            return FONT_FILE
        except Exception as e:
            print(f"Could not fetch Buienradar font, using a fallback: {e}", file=sys.stderr)
            return None


_fonts = {}


def font(px):
    if px not in _fonts:
        size = px * SCALE * SS
        for p in [ensure_font_file()] + FALLBACK_FONTS:
            try:
                _fonts[px] = ImageFont.truetype(p, size) if p else None
            except (OSError, TypeError):
                _fonts[px] = None
            if _fonts[px]:
                break
        else:
            _fonts[px] = ImageFont.load_default(size)
    return _fonts[px]


def curve_points(vals):
    """The page's SVG path, as a polygon in viewBox units (x 0..332, y 0..100, y down)."""
    n = len(vals)
    step = VB_W / n
    q = step / 4
    ys = [100 - max(0.0, min(100.0, v)) for v in vals]
    xs = [i * step for i in range(n)]
    # path: M 0 100 M x1 y1, one cubic per further point, a closing point at x=332 on the baseline
    nodes = [(xs[i], ys[i]) for i in range(1, n)] + [(VB_W, 100.0)]
    pts = [(0.0, 100.0), nodes[0]]
    for (x0, y0), (x1, y1) in zip(nodes, nodes[1:]):
        c1, c2 = (x0 + q, y0), (x1 - q, y1)
        for k in range(1, 17):
            t = k / 16
            u = 1 - t
            pts.append((
                u**3 * x0 + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * x1,
                u**3 * y0 + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * y1,
            ))
    pts.append((0.0, 100.0))  # the page closes the path back along the baseline
    return pts


def render(place, theme="dark"):
    t = THEMES[theme]
    data = fetch(place)
    fc = data["forecasts"]
    n = len(fc)
    vals = [f["percentageValue"] for f in fc]
    k = SCALE * SS  # viewbox/CSS px -> canvas px
    img = Image.new("RGB", (W * k, H * k), t["bg"])
    d = ImageDraw.Draw(img)
    sx, sy = SVG_W / VB_W, SVG_H / 100  # viewBox -> CSS px

    def px(x, y):  # viewBox coords -> canvas px
        return ((SVG_X + x * sx) * k, y * sy * k)

    # gridlines (the page's 0.3 unit stroke is only 0.39 CSS px tall)
    for b in data["borders"]:
        y = (100 - b["percentageValue"]) * sy * k
        d.rectangle([SVG_X * k, y - 0.2 * k, (SVG_X + SVG_W) * k, y + 0.2 * k], fill=t["grid"])
    # legend labels: absolutely positioned at top 65/40/15 % of the graph, 21 px line boxes
    for b in data["borders"]:
        top = (100 - b["percentageValue"] - 10) / 100 * SVG_H
        d.text((0.5 * k, (top + 10) * k), b["title"], font=font(14), fill=t["legend"], anchor="lm")

    first = datetime.fromisoformat(fc[0]["dateTime"])
    # the page spreads markers over first..last point (width / (n-1) per 5 min), rounded to whole pixels
    marker_step = SVG_W / (n - 1)

    def marker(offset_px, label, color, dashed, label_shift=(0, 0)):
        """Vertical marker behind the graph: label on top, 1 px line below, as the page lays it out."""
        x = SVG_X + offset_px
        if dashed:
            for y in range(18, SVG_H, 8):  # 5 px on, 3 off
                d.rectangle([(x - 0.5) * k, y * k, (x + 0.5) * k, min(y + 5, SVG_H) * k], fill=color)
        else:
            d.rectangle([(x - 0.5) * k, 18 * k, (x + 0.5) * k, SVG_H * k], fill=color)
        d.text(((x + label_shift[0]) * k, (8.4 + label_shift[1]) * k), label, font=font(14), fill=color, anchor="mm")

    # "Nu": the page offsets the label's left edge by the elapsed time, so the line sits half a label further right
    utc_first = datetime.fromisoformat(fc[0]["utcDateTime"])
    now_local = datetime.utcnow() + (first - utc_first)
    off = round((now_local - first).total_seconds() / 300 * marker_step)
    if 0 <= off <= SVG_W:
        label_w = d.textlength("Nu", font=font(14)) / k
        marker(off + label_w / 2, "Nu", t["now"], True, (-0.5, -0.5))
    # midnight marker with the weekday of the new day
    midnight = first.replace(hour=0, minute=0, second=0) + timedelta(days=1)
    off = round((midnight - first).total_seconds() / 300 * marker_step)
    if 0 < off <= SVG_W:
        marker(off, DAYS[midnight.weekday()], t["legend"], False, (0.5, 0.5))

    fill = tuple(int(data["fillColor"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    poly = [px(x, y) for x, y in curve_points(vals)]
    d.polygon(poly, fill=fill)
    d.line(poly, fill=fill, width=max(1, round(0.52 * k)), joint="curve")
    # the page's SVG clips at its bottom edge, which hides half of the baseline stroke
    d.rectangle([SVG_X * k, SVG_H * k, W * k, 138 * k], fill=t["bg"])

    # time labels: four labels an hour apart, spread over the graph width (flex space-between)
    labels = [datetime.fromisoformat(fc[i]["dateTime"]).strftime("%H:%M") for i in range(0, n, 12)]
    f = font(16)
    widths = [d.textlength(s, font=f) / k for s in labels]
    gap = (SVG_W - sum(widths)) / max(1, len(labels) - 1)
    x = SVG_X
    for s, w in zip(labels, widths):
        d.text(((x + 0.5) * k, 150 * k), s, font=f, fill=t["text"], anchor="lm")
        x += w + gap

    graph = img.resize((W * SCALE, H * SCALE), Image.LANCZOS)
    out = Image.new("RGB", ((W + 2 * PAD) * SCALE, (H + 2 * PAD) * SCALE), t["bg"])
    out.paste(graph, (PAD * SCALE, PAD * SCALE))
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


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
            self.send(200, "image/png", render(name, theme), {"Cache-Control": "max-age=60"})
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
