---
name: landmap
description: Run, define, check, and deploy Land Map, the property boundary map with GPS pinning (github.com/krisrowe/landmap). Use when asked to map a piece of land or a property boundary, write or change a property definition (property.yaml with survey traverses, points, layers, overlays), add a KML or image overlay, run the map locally, deploy it, put the property data where a deployed map reads it, find or share the pin access key, or when a Land Map server shows the example property instead of the real one.
compatibility: Needs Python 3.11+ and the repo checkout. Deploying needs a deployment tool (the repo ships a gapp.yaml for gapp); that tool's own skill says how to reach the persistent path.
---

# landmap

Land Map serves one property: layers resolved from a YAML definition over
satellite imagery, public to anyone with the URL, and GPS pins behind a
shared access key. The repo is code plus one fictional example; the real
land is **data outside the repo**.

## Invariants

- The server reads everything about the land from one data directory,
  `LANDMAP_DATA_PATH`: `property/` (the definition and its `overlays/`),
  `pins.json`, later `tracks/`. `LANDMAP_PROPERTY` points at a definition
  folder elsewhere and wins over `<data>/property`.
- No definition in the data directory means the bundled example is served
  and the API reports `"example": true`. A real map showing "Example 40"
  means the property folder has not reached the data directory yet.
- A changed definition shows on the next page load; never restart for it.
- Never copy a real property into the repo tree. `.gitignore` refuses
  everything under `properties/` except the example, and a local image
  build would otherwise ship it.
- The access key is a shared secret, not a credential to a user account.
  Hand it over as a `?key=` link or from the deployment's secret store;
  never paste it into a chat or a file in the repo.

## Test the GPS features from anywhere

Tap a spot on the map and choose Put me here. Every GPS reading is then
shifted so that spot stands for where you really are; walking around moves
you around the land, and Locate and Pin here behave as they would on site.
The toolbar shows a Teleported button while it is on; tap it to end. Pins
saved while teleported are real pins at the shifted position.

## Run locally

```bash
pip install -e ".[dev]"
LANDMAP_DATA_PATH=/path/to/data LANDMAP_ACCESS_KEY=dev uvicorn landmap.server:app --reload
```

Open `http://127.0.0.1:8000/?key=dev`. Omit the data path to see the
example.

## Define a property

Copy `properties/example/property.yaml` into `<data>/property/` and edit.
Everything is survey language: feet and degrees clockwise from north.

1. **Anchor.** One known corner as `lat`/`lng` under `points:`; nudge it
   with `moves` if the recorded corner sits off the road centre line.
2. **Constants.** Side lengths and bearings from the plat. Expressions may
   use them (`"north_len * 4"`, `"side(2.5) / 2"`, `sqrt`).
3. **Points.** Derive the rest: `{from: <point>, moves: [[bearing, feet], ...]}`,
   `{corner: <shape>, which: ne}`, `{center: <shape>}`, `{vertex: <shape>, index: 2}`,
   `{midpoint: [a, b]}`.
4. **Layers.** Each has `id`, `name`, `default` (on or off at first load)
   and `features`. Spec types: `traverse` (start plus legs), `points`,
   `square` (acres from a corner), `rect` (centered), `quadrants` of a shape,
   `label` (at a point, or `in: <shape>` to sit centred inside its top edge
   like a plat; optional `legal_text` shown when the Legal layer is on),
   `image` (file plus `sw`/`ne` corner points), `kml` (file). A feature with
   an `id` can be referenced by other points and shapes.
5. **Overlays.** Files under `<data>/property/overlays/`, referenced as
   `overlays/<file>`. Traced boundaries and GPS tracks as KML; scanned maps
   as images placed by two corners.
6. **Defaults.** What is on the ground is on; plans, cross-checks and
   scanned overlays are off.

Then check it:

```bash
python -m landmap check /path/to/data/property
```

Fix anything it flags (unknown points, missing overlay files) before serving.

## Deploy

The service needs one persistent directory as `LANDMAP_DATA_PATH` and
nothing else about its host. Deploy the repo unchanged, then copy the
property folder into that directory so it holds `property/property.yaml`
and `property/overlays/`. Consult the deployment tool's skill for how to
reach the directory from this machine and how to read the access key back;
for gapp the manifest already maps the data path to the solution's data
volume and generates the key into its secret store.

After a deploy, open the URL: the example showing means the data has not
been copied; your property's name in the title means it has.
