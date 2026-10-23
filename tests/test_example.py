"""The bundled example is data; this checks it resolves, agrees with its traced
overlay, and keeps the conventions a real definition should copy."""

import math
from pathlib import Path

from landmap.__main__ import main
from landmap.boundary import load_boundary
from landmap.data import EXAMPLE
from landmap.resolver import Property


def _m(a, b):
    return math.hypot((a[0] - b[0]) * 111_320, (a[1] - b[1]) * 111_320 * math.cos(math.radians(a[0])))


def test_surveyed_40_matches_the_traced_boundary_within_5m():
    p = Property.load(EXAMPLE / "property.yaml")
    computed = p.shape("forty")[:4]
    kml = load_boundary(EXAMPLE / "overlays" / "traced-boundary.kml")["features"][0]["geometry"]["coordinates"][0][:4]
    traced = [(lat, lng) for lng, lat in kml]
    for c in computed:
        assert min(_m(c, t) for t in traced) < 5


def test_what_is_there_is_on_and_plans_and_overlays_are_off():
    layers = {l["id"]: l["default"] for l in Property.load(EXAMPLE / "property.yaml").layers()}
    assert {k for k, v in layers.items() if v} == {"forty", "section", "legal", "pond", "drive"}
    assert {"house", "plan", "traced", "soil"} <= {k for k, v in layers.items() if not v}


def test_everything_is_near_the_anchor():
    p = Property.load(EXAMPLE / "property.yaml")
    anchor = p.point("section_nw")
    for layer in p.layers():
        for f in layer["features"]["features"]:
            g = f["geometry"]
            if g is None:
                continue
            pts = [g["coordinates"]] if g["type"] == "Point" else g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"]
            for lng, lat in pts:
                assert _m((lat, lng), anchor) < 3000, (layer["id"], f["properties"])


def test_check_command_passes_on_the_example_and_flags_missing_files(tmp_path: Path, capsys):
    assert main(["check"]) == 0
    assert "Example 40" in capsys.readouterr().out
    broken = tmp_path / "p"
    broken.mkdir()
    (broken / "property.yaml").write_text(
        "name: Broken\npoints: {a: {lat: 1, lng: 1}}\nlayers:\n"
        "  - {id: x, name: X, features: [{type: kml, file: overlays/gone.kml}]}\n")
    assert main(["check", str(broken)]) == 1
    assert "MISSING overlays/gone.kml" in capsys.readouterr().out
    assert main(["check", str(tmp_path / "nothing")]) == 1
    assert main([]) == 2
