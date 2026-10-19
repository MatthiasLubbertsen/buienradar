# Buienradar rain graph PNGs

Serves the Buienradar rain graph (last ~10 min + next ~2 hours) as a PNG, for Putten and Barneveld.

It fetches the same data the graph on buienradar.nl uses (`graphdata.buienradar.nl`) and draws the graph
with Pillow, following the page's own SVG: same layout, scale (gridlines at 25/50/75 %), curve, colours,
"Nu" line and midnight marker. The hover pointer/tooltip is left out. No browser involved: about 45 MB RAM,
a small Python image.

## Docker

```
docker compose up --build
```

## Without Docker

```
pip install -r requirements.txt
python app.py 8000
```

## Endpoints

- http://localhost:8000/putten.png
- http://localhost:8000/barneveld.png
- http://localhost:8000/ shows both
- add `?theme=light` for the light version

Data is cached for 1 minute. The first request downloads Buienradar's typeface from their site into `fonts/`
(not committed); if that fails a system font is used.

To add a place, add its slug and coordinates (rounded to 2 decimals) to `PLACES` in `app.py`. Coordinates come from
`https://location.buienradar.nl/1.1/location/search?query=<name>`.
