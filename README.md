# Land Map

A map of the property boundary with GPS place pinning. The map and the
boundary are public to anyone with the URL. Pins are private: seeing and
editing them takes the access key, entered once from the menu or carried
in a `?key=` link saved to the phone's home screen. Open it while walking
the land, tap **Pin here**, give the spot a label, and it's on the map.

## How it's organized

Code and data are separate. The repo holds the code and one fictional example
property; your land lives in a **data directory** outside the repo.

| Path | Holds |
|---|---|
| `<data>/property/property.yaml` | **Data.** One property: anchor point, survey constants, named reference points, and every map layer with its default visibility, style, and geometry spec. No code. |
| `<data>/property/overlays/` | Image overlays and KML files the definition refers to. |
| `<data>/pins.json` | Pins tagged on the ground. |
| `properties/example/` | A complete fictional definition to copy from. Served when the data directory has no property yet. |
| `landmap/resolver.py` | **Code.** Turns a definition into GeoJSON layers; knows nothing about any property. |
| `landmap/data.py`, `landmap/server.py`, `landmap/store.py` | The data directory, the API, and the pin store. |
| `landmap/static/` | The page. Renders whatever layers the API serves. |

A geometry spec is one of: `traverse` (a start point and legs of bearing and
distance, as a survey gives them), `points`, `square` (N acres from a corner),
`rect` (centered), `quadrants` of another shape, `label`, `image` (with
corner points), or `kml`. Points are named and derived from each other
(`{from: section_nw, moves: [[90, 330]]}`, `{corner: clearing, which: ne}`,
`{center: clearing}`), and any number may be an expression over the
definition's constants (`"north_len * 4"`, `"side(2.5) / 2"`).

Check a definition before serving it:

```bash
python -m landmap check /path/to/property
```

It resolves every layer, lists each with its default, flags overlay files
the definition names but the folder lacks, and prints the extent.

## What it does

- Draws every layer of the property definition over satellite imagery: surveyed tracts, section lines, water, drives, structures,
  plans, traced boundaries, scanned maps. Each is a checkbox under Layers in
  the menu, on or off as the definition says, and choices stick on the device.
- The map stays on the land: you can pull back for regional perspective and
  pan the region, not beyond, and the Home button lights up whenever the
  property is out of view or too small to read. Far from the property, Locate
  reports how far and which direction you are instead of flying there.
- **Locate** shows your live position and GPS accuracy ring; tap again to
  stop following.
- **Pin here** listens to the GPS for a few seconds, keeps the most accurate
  reading, and saves it with a label and optional note. Pins render as
  labeled markers; tap one to edit or delete it.
- Tap anywhere on the map (click or right-click on a desktop) and it asks what you want there: **Pin here** (by
  hand, no GPS) or **Put me here**. Put me here anchors your real position to
  that spot: from then on every GPS reading is shifted by the same ground
  distance, so walking around your own neighborhood moves you around the land.
  Locate, Pin here, and everything else see the shifted position, which makes
  it a real test of the GPS features from anywhere. It survives a reload and
  ends from the toolbar. The coordinates shown in that sheet, and a Copy
  button on every pin, put the lat/long on the clipboard.
- **Offline map** (in the menu) pre-downloads the imagery tiles around the
  boundary so the map still renders without cell signal; pins made offline
  queue in the browser and sync when a connection returns.
- The menu opens on the layer list; Offline map and Sign in / Sign out sit below it.
- Installable as a home-screen app (web manifest + service worker).

## Run locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
LANDMAP_ACCESS_KEY=dev uvicorn landmap.server:app --reload
```

Open http://127.0.0.1:8000/?key=dev (or sign in from the menu with `dev`).
With no data directory yet this serves the example property; to see your
own, copy a definition to `./data/property/` or point `LANDMAP_PROPERTY` at
its folder. A changed definition is picked up on the next page load, no
restart. Pins are written to `./data/pins.json`.

Tests: `pytest` (unit) and `pytest tests/browser` (Playwright, needs
`pip install -e ".[browser]"` and a Chromium).

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `LANDMAP_DATA_PATH` | The data directory: `property/`, `pins.json` | `./data` |
| `LANDMAP_PROPERTY` | A property definition directory, overriding `<data>/property` | unset |
| `LANDMAP_ACCESS_KEY` | Key required to read or change pins (header `X-Access-Key` or `?key=`); the map is always public | unset = open |

## API

| Method | Path | Body |
|---|---|---|
| GET | `/api/property` | name, center, zoom, and every layer as GeoJSON with its default (public) |
| GET | `/overlays/<file>` | the property's image and KML files (public) |
| GET | `/api/session` | 200 with a valid key, else 401 |
| GET | `/api/pins` | list of pins |
| POST | `/api/pins` | `{label, lat, lng, accuracy?, note?}` |
| PATCH | `/api/pins/{id}` | any of `label, note, lat, lng` |
| DELETE | `/api/pins/{id}` | |
| GET | `/health`, `/healthz` | liveness |

## Deploy

The service needs one persistent directory, given as `LANDMAP_DATA_PATH`, and
nothing else about where it runs. Deploy the repo as it is, then copy your
property folder into that directory; the map switches from the example to
your land on the next load. How to reach the directory from your machine is
your deployment tool's business, not this repo's.

`gapp.yaml` describes the service for [gapp](https://github.com/echomodel/gapp):
a public Cloud Run service with the data directory on the solution's data
volume and the access key generated into Secret Manager on first deploy.
Read the key back with `gapp secrets get access-key --plaintext`; the map
itself needs no key.
