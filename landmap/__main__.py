"""`python -m landmap check [<property dir>]`: resolve a definition and report."""

import sys
from pathlib import Path

from .data import DEFINITION, EXAMPLE
from .resolver import Property, bounds


def check(directory: Path) -> int:
    path = directory / DEFINITION
    if not path.is_file():
        print(f"no {DEFINITION} in {directory}")
        return 1
    prop = Property.load(path)
    info = prop.info()
    c = info["center"]
    where = f"center {c['lat']:.6f}, {c['lng']:.6f}" if c else "no center (the map opens on the layers' extent)"
    print(f"{info['name']}: {where}, zoom {info['zoom']}")
    problems = 0
    pts = []
    for layer in prop.layers():
        feats = layer["features"]["features"]
        missing = [f["properties"]["missing"] for f in feats if f["properties"].get("missing")]
        images = [f["properties"]["image"] for f in feats if f["properties"].get("image")]
        for rel in images:
            if not (directory / rel).is_file():
                missing.append(rel)
        for f in feats:
            g = f["geometry"]
            if g is None:
                continue
            if g["type"] == "Point":
                pts.append(g["coordinates"])
            elif g["type"] == "Polygon":
                pts.extend(g["coordinates"][0])
            else:
                pts.extend(g["coordinates"])
        flag = "on " if layer["default"] else "off"
        note = f"  MISSING {', '.join(missing)}" if missing else ""
        problems += len(missing)
        print(f"  [{flag}] {layer['id']:<14} {layer['name']:<24} {len(feats):>3} feature(s){note}")
    if pts:
        sw, ne = bounds([(lat, lng) for lng, lat in pts])
        print(f"extent: {sw[0]:.6f},{sw[1]:.6f} to {ne[0]:.6f},{ne[1]:.6f}")
    return 1 if problems else 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] != "check" or len(argv) > 2:
        print("usage: python -m landmap check [<property dir>]  (default: the bundled example)")
        return 2
    return check(Path(argv[1]) if len(argv) == 2 else EXAMPLE)


if __name__ == "__main__":
    sys.exit(main())
