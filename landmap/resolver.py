"""Turn a declarative property definition into GeoJSON layers.

The definition (see properties/<slug>/property.yaml) names reference points
and describes features as traverses of bearings and distances, squares of
acreage, rectangles, labels, image overlays, or KML files. This module knows
how to resolve those shapes; it knows nothing about any particular property.

Distances are in feet, bearings in degrees clockwise from north, as surveys
give them. Any number may be written as a string expression over the
definition's `constants` (e.g. "north_len * 4", "sqrt(2) * 330 / 8",
"side(2.5) / 2" where side() is the side of a square of that many acres).
"""

from __future__ import annotations

import ast
import math
from pathlib import Path

import yaml

EARTH_RADIUS_M = 6378137.0
FEET_PER_METER = 3.28084
SQFT_PER_ACRE = 43560


# ---- geodesy ------------------------------------------------------------------

def offset(point: tuple[float, float], bearing_deg: float, feet: float) -> tuple[float, float]:
    """Destination (lat, lng) from `point` along `bearing_deg` for `feet` on a sphere."""
    lat1, lng1 = math.radians(point[0]), math.radians(point[1])
    d = feet / FEET_PER_METER / EARTH_RADIUS_M
    br = math.radians(bearing_deg)
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(br))
    lng2 = lng1 + math.atan2(math.sin(br) * math.sin(d) * math.cos(lat1),
                             math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lat2), math.degrees(lng2)


def bounds(pts):
    lats = [p[0] for p in pts]; lngs = [p[1] for p in pts]
    return (min(lats), min(lngs)), (max(lats), max(lngs))


def center(pts):
    (s, w), (n, e) = bounds(pts)
    return (s + n) / 2, (w + e) / 2


def corner(pts, which: str):
    """Corner of a roughly axis-aligned shape: nw, ne, sw, or se."""
    key = {"nw": lambda p: p[0] - p[1], "ne": lambda p: p[0] + p[1],
           "sw": lambda p: -(p[0] + p[1]), "se": lambda p: -(p[0] - p[1])}[which]
    return max(pts, key=key)


# ---- expressions ---------------------------------------------------------------

_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Call, ast.Load,
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd)


class Evaluator:
    FUNCTIONS = {"sqrt": math.sqrt, "side": lambda acres: math.sqrt(acres * SQFT_PER_ACRE)}

    def __init__(self, constants: dict):
        clash = set(constants or {}) & set(self.FUNCTIONS)
        if clash:
            raise ValueError(f"constants may not shadow functions: {sorted(clash)}")
        self.env = {**self.FUNCTIONS, **(constants or {})}

    def __call__(self, value):
        if isinstance(value, (int, float)):
            return float(value)
        tree = ast.parse(str(value), mode="eval")
        for node in ast.walk(tree):
            if not isinstance(node, _ALLOWED):
                raise ValueError(f"unsupported expression: {value!r}")
            if isinstance(node, ast.Name) and node.id not in self.env:
                raise ValueError(f"unknown name {node.id!r} in {value!r}")
        return float(eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, self.env))


# ---- resolver ------------------------------------------------------------------

class Property:
    def __init__(self, definition: dict, base_dir: Path | None = None):
        self.definition = definition
        self.base_dir = Path(base_dir) if base_dir else None
        self.ev = Evaluator(definition.get("constants", {}))
        self._points: dict[str, tuple[float, float]] = {}
        self._shapes: dict[str, list[tuple[float, float]]] = {}
        self._specs = {}
        for layer in definition.get("layers", []):
            for feat in layer.get("features", []):
                if "id" in feat:
                    self._specs[feat["id"]] = feat

    @classmethod
    def load(cls, path: Path) -> "Property":
        path = Path(path)
        with path.open() as fh:
            return cls(yaml.safe_load(fh), path.parent)

    # -- points --
    def point(self, spec) -> tuple[float, float]:
        if isinstance(spec, str):
            if spec not in self._points:
                if spec not in self.definition.get("points", {}):
                    raise KeyError(f"unknown point {spec!r}")
                self._points[spec] = self.point(self.definition["points"][spec])
            return self._points[spec]
        if "lat" in spec:
            return float(spec["lat"]), float(spec["lng"])
        if "midpoint" in spec:
            a, b = (self.point(p) for p in spec["midpoint"])
            return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        if "corner" in spec:
            base = corner(self.shape(spec["corner"]), spec["which"])
        elif "center" in spec:
            base = center(self.shape(spec["center"]))
        elif "vertex" in spec:
            base = self.shape(spec["vertex"])[int(spec["index"])]
        elif "from" in spec:
            base = self.point(spec["from"])
        else:
            raise ValueError(f"cannot resolve point {spec!r}")
        return self.walk(base, spec.get("moves", []))[-1]

    def walk(self, start, legs):
        pts = [start]
        for bearing, dist in legs:
            pts.append(offset(pts[-1], self.ev(bearing), self.ev(dist)))
        return pts

    # -- shapes (vertex lists) --
    def shape(self, feature_id: str):
        if feature_id not in self._shapes:
            if feature_id not in self._specs:
                raise KeyError(f"unknown feature {feature_id!r}")
            self._shapes[feature_id] = self._vertices(self._specs[feature_id])
        return self._shapes[feature_id]

    def _vertices(self, feat) -> list[tuple[float, float]]:
        kind = feat["type"]
        if kind == "traverse":
            return self.walk(self.point(feat["start"]), feat.get("legs", []))
        if kind == "points":
            return [self.point(p) for p in feat["points"]]
        if kind == "square":
            side = math.sqrt(self.ev(feat["acres"]) * SQFT_PER_ACRE)
            pts = self.walk(self.point(feat["nw"]), [(90, side), (180, side), (-90, side), (0, side)])[:4]
            for bearing, dist in feat.get("shift", []):
                pts = [offset(p, self.ev(bearing), self.ev(dist)) for p in pts]
            return pts
        if kind == "rect":
            c = self.point(feat["center"]); w = self.ev(feat["width"]); h = self.ev(feat["height"])
            sw = offset(offset(c, -90, w / 2), 180, h / 2); ne = offset(offset(c, 90, w / 2), 0, h / 2)
            return [sw, (sw[0], ne[1]), ne, (ne[0], sw[1])]
        raise ValueError(f"feature type {kind!r} has no vertices")

    # -- GeoJSON --
    def _style(self, feat):
        s = dict(feat.get("style", {}))
        return s

    def feature_geojson(self, feat) -> list[dict]:
        kind = feat["type"]
        props = {"kind": kind, **self._style(feat)}
        if "id" in feat:
            props["id"] = feat["id"]
        if kind == "label":
            at = self.point(feat["at"])
            props.update({"kind": "label", "text": feat["text"], "legalText": feat.get("legal_text")})
            return [{"type": "Feature", "properties": props,
                     "geometry": {"type": "Point", "coordinates": [at[1], at[0]]}}]
        if kind == "quadrants":
            sw, ne = bounds(self.shape(feat["of"]))
            out = []
            for seg in _quadrant_lines(sw, ne, int(feat.get("depth", 1))):
                out.append({"type": "Feature", "properties": {**props, "kind": "line"},
                            "geometry": {"type": "LineString", "coordinates": [[p[1], p[0]] for p in seg]}})
            return out
        if kind == "image":
            sw = self.point(feat["sw"]); ne = self.point(feat["ne"])
            props.update({"image": feat["file"], "opacity": feat.get("opacity", 0.5),
                          "bounds": {"south": sw[0], "west": sw[1], "north": ne[0], "east": ne[1]}})
            return [{"type": "Feature", "properties": props, "geometry": None}]
        if kind == "kml":
            from .boundary import load_kml
            path = (self.base_dir or Path(".")) / feat["file"]
            if not path.exists():
                return [{"type": "Feature", "properties": {**props, "missing": feat["file"]}, "geometry": None}]
            feats = load_kml(path)["features"]
            for f in feats:
                f["properties"] = {**props, **f.get("properties", {}), "kind": "kml"}
            return feats
        pts = self.shape(feat["id"]) if "id" in feat else self._vertices(feat)
        if feat.get("close") or feat.get("style", {}).get("fill"):
            ring = pts + ([pts[0]] if pts[0] != pts[-1] else [])
            props["kind"] = "polygon"
            return [{"type": "Feature", "properties": props,
                     "geometry": {"type": "Polygon", "coordinates": [[[p[1], p[0]] for p in ring]]}}]
        props["kind"] = "line"
        return [{"type": "Feature", "properties": props,
                 "geometry": {"type": "LineString", "coordinates": [[p[1], p[0]] for p in pts]}}]

    def layers(self) -> list[dict]:
        out = []
        for layer in self.definition.get("layers", []):
            feats = []
            for feat in layer.get("features", []):
                feats.extend(self.feature_geojson(feat))
            out.append({"id": layer["id"], "name": layer["name"], "default": bool(layer.get("default", False)),
                        "features": {"type": "FeatureCollection", "features": feats}})
        return out

    def info(self) -> dict:
        d = self.definition
        c = self.point(d["center"]) if "center" in d else None
        return {"name": d.get("name", "Land Map"), "center": c and {"lat": c[0], "lng": c[1]},
                "zoom": d.get("zoom", 16)}


def _quadrant_lines(sw, ne, depth):
    c = ((sw[0] + ne[0]) / 2, (sw[1] + ne[1]) / 2)
    out = [[c, (c[0], sw[1])], [c, (ne[0], c[1])], [c, (c[0], ne[1])], [c, (sw[0], c[1])]]
    if depth > 1:
        for qsw, qne in [(sw, c), ((c[0], sw[1]), (ne[0], c[1])), (c, ne), ((sw[0], c[1]), (c[0], ne[1]))]:
            out.extend(_quadrant_lines(qsw, qne, depth - 1))
    return out
