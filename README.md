# Land Map

A map of the property boundary with GPS place pinning. The map and the
boundary are public to anyone with the URL. Pins are private: seeing and
editing them takes the access key, entered once from the menu or carried
in a `?key=` link saved to the phone's home screen. Open it while walking
the land, tap **Pin here**, give the spot a label, and it's on the map.

## What it does

- Draws the boundary from `landmap/boundary.kml` (Google Earth export) over
  satellite imagery, with a streets layer as an alternative.
- **Locate** shows your live position and GPS accuracy ring; tap again to
  stop following.
- **Pin here** listens to the GPS for a few seconds, keeps the most accurate
  reading, and saves it with a label and optional note. Pins render as
  labeled markers; tap one to edit or delete it.
- Right-click or long-press anywhere on the map to pin a spot by hand.
- **Offline map** (in the menu) pre-downloads the imagery tiles around the
  boundary so the map still renders without cell signal; pins made offline
  queue in the browser and sync when a connection returns.
- The menu also holds Sign in / Sign out and the Satellite / Streets switch.
- Installable as a home-screen app (web manifest + service worker).

## Run locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
LANDMAP_ACCESS_KEY=dev uvicorn landmap.server:app --reload
```

Open http://127.0.0.1:8000/?key=dev (or sign in from the menu with `dev`).
Pins are written to `./data/pins.json`.

Tests: `pytest`.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `LANDMAP_DATA_PATH` | Directory holding `pins.json` | `./data` |
| `LANDMAP_ACCESS_KEY` | Key required to read or change pins (header `X-Access-Key` or `?key=`); the boundary is always public | unset = open |
| `LANDMAP_KML` | Alternate boundary KML | bundled `boundary.kml` |

## API

| Method | Path | Body |
|---|---|---|
| GET | `/api/boundary` | GeoJSON FeatureCollection plus bounding box (public) |
| GET | `/api/session` | 200 with a valid key, else 401 |
| GET | `/api/pins` | list of pins |
| POST | `/api/pins` | `{label, lat, lng, accuracy?, note?}` |
| PATCH | `/api/pins/{id}` | any of `label, note, lat, lng` |
| DELETE | `/api/pins/{id}` | |
| GET | `/health`, `/healthz` | liveness |

## Deploy

`gapp.yaml` describes the service for [gapp](https://github.com/echomodel/gapp):
a public Cloud Run service, pins stored on the solution's data volume, and the
access key generated into Secret Manager on first deploy. Read the key back
with `gapp secrets get access-key --plaintext`; the map itself needs no key.

## Legacy files

`legacy/` holds the KML files from the first version of this repo:
`map-poly.kml` is a hand-drawn boundary estimate (coordinates in lat,lng
order, not valid KML) and `gen2.kml` duplicates the Google Earth export now
at `landmap/boundary.kml`.
