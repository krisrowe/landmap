"""Read KML (polygons, lines, points) and expose it as GeoJSON."""

from pathlib import Path
import xml.etree.ElementTree as ET

KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


def _parse_coords(text: str) -> list[list[float]]:
    """KML coordinates are 'lng,lat[,alt]' tuples separated by whitespace."""
    ring = []
    for token in text.split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        ring.append([float(parts[0]), float(parts[1])])
    return ring


def load_kml(path: Path) -> dict:
    """Return a GeoJSON FeatureCollection of every polygon, line, and point in the KML."""
    root = ET.parse(path).getroot()
    features = []
    for placemark in root.iter(f"{{{KML_NS['kml']}}}Placemark"):
        name_el = placemark.find("kml:name", KML_NS)
        name = (name_el.text or "").strip() if name_el is not None else ""
        for ls in placemark.iter(f"{{{KML_NS['kml']}}}LineString"):
            coords = ls.find("kml:coordinates", KML_NS)
            if coords is not None and coords.text:
                features.append({"type": "Feature", "properties": {"name": name},
                                 "geometry": {"type": "LineString", "coordinates": _parse_coords(coords.text)}})
        for pt in placemark.iter(f"{{{KML_NS['kml']}}}Point"):
            coords = pt.find("kml:coordinates", KML_NS)
            if coords is not None and coords.text:
                parsed = _parse_coords(coords.text)
                if parsed:
                    features.append({"type": "Feature", "properties": {"name": name},
                                     "geometry": {"type": "Point", "coordinates": parsed[0]}})
        for polygon in placemark.iter(f"{{{KML_NS['kml']}}}Polygon"):
            rings = []
            outer = polygon.find("kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", KML_NS)
            if outer is None or not outer.text:
                continue
            rings.append(_parse_coords(outer.text))
            for inner in polygon.findall("kml:innerBoundaryIs/kml:LinearRing/kml:coordinates", KML_NS):
                if inner.text:
                    rings.append(_parse_coords(inner.text))
            features.append({
                "type": "Feature",
                "properties": {"name": name},
                "geometry": {"type": "Polygon", "coordinates": rings},
            })
    return {"type": "FeatureCollection", "features": features}


def load_boundary(path: Path) -> dict:
    """Polygons only, from the given KML."""
    fc = load_kml(Path(path))
    fc["features"] = [f for f in fc["features"] if f["geometry"]["type"] == "Polygon"]
    return fc


def bounds(collection: dict) -> dict | None:
    """Bounding box of every ring, as {south, west, north, east}."""
    lngs, lats = [], []
    for feature in collection["features"]:
        geom = feature["geometry"]
        rings = geom["coordinates"] if geom["type"] == "Polygon" else [geom["coordinates"]] if geom["type"] == "LineString" else [[geom["coordinates"]]]
        for ring in rings:
            for lng, lat in ring:
                lngs.append(lng)
                lats.append(lat)
    if not lats:
        return None
    return {"south": min(lats), "west": min(lngs), "north": max(lats), "east": max(lngs)}
