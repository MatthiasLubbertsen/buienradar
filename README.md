# Buienradar rain graph PNGs

Serves a screenshot of the rain graph on buienradar.nl as a PNG, for Putten and Barneveld.
It opens the real weather page in headless Chromium (Playwright) and captures the `.area-graph`
element, in dark mode, with the hover pointer/tooltip hidden. The dashed "Nu" line is kept.

## Docker

```
docker compose up --build
```

## Without Docker

```
pip install -r requirements.txt
playwright install --with-deps chromium
python app.py 8000
```

## Endpoints

- http://localhost:8000/putten.png
- http://localhost:8000/barneveld.png
- http://localhost:8000/ shows both
- add `?theme=light` for the light version

Screenshots take a few seconds and are cached for 2 minutes. Add places in `PLACES` in `app.py`
(slug and Buienradar location id, found via `https://location.buienradar.nl/1.1/location/search?query=<name>`).

Set `BR_MOCK_RAIN=1` to inject fake rain into the graph, to check the rendering on a dry day.
