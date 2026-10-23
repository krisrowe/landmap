# Contributing

## Design

**Data is not code.** A property is a YAML definition plus overlay files, read
from a data directory at runtime (`landmap/data.py`). The repo carries one
fictional example and no real land. The resolver (`landmap/resolver.py`)
turns a definition into GeoJSON and knows nothing about any property; the
page renders whatever layers the API serves. If a change needs the code to
know something about a particular property, the change is wrong.

**The definition is survey language.** Traverses of bearing and distance,
named points derived from each other, constants with expressions. A plat or
a county description transcribes into it directly; nothing is pre-computed
into coordinates by hand. The example property shows every spec type.

**Lazy, not startup.** The property source re-reads the definition when its
file changes, so data can land after the service is up (a fresh deploy with
an empty volume serves the example until the folder is copied in) and edits
show on the next load.

**Public map, private pins.** Layers and overlays are public. Pins need the
access key, which is a shared secret compared in constant time, nothing
more. There is no user model and none is planned.

**The map is about the land.** The viewport cannot leave the region around
the property; Locate far away reports distance and direction instead of
flying there; Home always returns. Keep that contract when adding features.

**Nothing built lands in the tree.** No bundlers, no generated files; the
page is plain files under `landmap/static/` with Leaflet vendored.

## Layout

| Path | What |
|---|---|
| `landmap/resolver.py` | Definition → GeoJSON. Pure; unit-tested with a synthetic spec. |
| `landmap/data.py` | The data directory contract and the lazily reloaded property source. |
| `landmap/server.py` | FastAPI app: property, overlays, pins, static page. |
| `landmap/store.py` | Pin store (`pins.json`, atomic writes). |
| `landmap/__main__.py` | `python -m landmap check <dir>`. |
| `landmap/static/` | The page, the service worker, vendored Leaflet. |
| `properties/example/` | The fictional example property. The only property in the repo, by `.gitignore`. |
| `skills/landmap/` | The agent skill for running, defining, and deploying. |
| `tests/` | Unit tests; `tests/browser/` drives the page with Playwright and a faked GPS. |

## Testing

`pytest` runs the unit suite. `pytest tests/browser` runs the Playwright
suite against a real server with a faked geolocation; it needs the
`browser` extra and a Chromium. Both must pass before a push.

## Roadmap

### Walk tracking

Record a walk on the ground and keep it as a named overlay.

- **Controls.** A Go / Stop pair next to Locate. While recording, the page
  keeps the GPS watch alive, appends fixes (with accuracy) to an in-memory
  track, draws the trail live, and queues fixes offline the way pins queue.
- **Saving.** Stop asks for a name, defaulting to the date and time in the
  property's time zone; the definition gains an optional `timezone` field
  (IANA name) for this. The track is written to `<data>/tracks/<id>.json`
  through a keyed `/api/tracks` endpoint, same access rule as pins.
- **Showing.** Tracks appear in the Layers menu under their own heading,
  off by default, togglable like any layer, with the recorded date in the
  label. The server turns a track into a GeoJSON LineString; the page
  renders it with the existing layer code.
- **Export.** A GPX download per track, so a walk can go into other tools
  or be traced into a KML overlay for the definition.
- **Not planned.** Editing a track's points, or merging tracks. Re-record.

### Property data elsewhere

The data directory is a plain folder so a deployment can provide it any
way it likes (a mounted volume, a synced folder). Pulling the definition
from a remote store inside the service is deliberately not on the roadmap;
copying a folder is simpler and keeps the code free of any provider.
