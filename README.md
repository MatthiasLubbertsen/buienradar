# Buienradar rain graph PNGs

Serves the Buienradar rain graph (recent past + next ~2 hours) as a PNG, without the hover tooltip.
Data comes from Buienradar's public graph API; the image is drawn locally with Pillow.

```
pip install -r requirements.txt
python app.py 8000
```

- http://localhost:8000/putten.png
- http://localhost:8000/barneveld.png
- http://localhost:8000/ shows both

Responses are cached for 2 minutes. Add places in `PLACES` in `app.py`.
