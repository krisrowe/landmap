"""The resolver is generic: these tests use a tiny synthetic property, not a real one."""

import math

import pytest

from landmap.resolver import Evaluator, Property, corner, offset

SQUARE = {
    "name": "Test",
    "center": "nw",
    "constants": {"edge": 1000, "brg": 90},
    "points": {
        "nw": {"lat": 45.0, "lng": -100.0},
        "ne": {"from": "nw", "moves": [["brg", "edge"]]},
        "lot_center": {"center": "lot"},
        "lot_se": {"corner": "lot", "which": "se"},
    },
    "layers": [
        {"id": "lot", "name": "Lot", "default": True, "features": [
            {"id": "lot", "type": "traverse", "start": "nw",
             "legs": [["brg", "edge"], [180, "edge"], [270, "edge"], [0, "edge"]],
             "style": {"color": "red"}},
            {"type": "quadrants", "of": "lot", "depth": 1, "style": {"color": "red", "opacity": 0.4}},
            {"type": "label", "at": "lot_center", "text": "Lot", "legal_text": "Lot 1, Block 2", "style": {"color": "red"}},
        ]},
        {"id": "shed", "name": "Shed", "default": False, "features": [
            {"type": "rect", "center": "lot_se", "width": 20, "height": 10, "close": True, "style": {"color": "gray", "fill": "gray", "fillOpacity": 0.5}},
            {"type": "square", "nw": "nw", "acres": 1, "shift": [[0, "side(1) / 2"]], "style": {"color": "green"}},
        ]},
        {"id": "photo", "name": "Photo", "default": False, "features": [
            {"type": "image", "file": "overlays/x.jpg", "sw": {"from": "nw", "moves": [[180, 500]]}, "ne": "ne", "opacity": 0.3},
            {"type": "kml", "file": "overlays/missing.kml", "style": {"color": "orange"}},
        ]},
    ],
}


def _m(a, b):
    return math.hypot((a[0] - b[0]) * 111_320, (a[1] - b[1]) * 111_320 * math.cos(math.radians(a[0])))


def test_offset_distance_and_direction():
    start = (45.0, -100.0)
    east = offset(start, 90, 1000)
    assert abs(_m(start, east) - 1000 / 3.28084) < 0.5
    assert abs(east[0] - start[0]) < 1e-6 and east[1] > start[1]
    north = offset(start, 0, 1000)
    assert north[0] > start[0] and abs(north[1] - start[1]) < 1e-9


def test_evaluator_accepts_arithmetic_and_rejects_everything_else():
    ev = Evaluator({"a": 10})
    assert ev(5) == 5.0 and ev("a * 2 + 1") == 21.0 and ev("sqrt(16)") == 4.0
    assert abs(ev("side(1)") - math.sqrt(43560)) < 1e-9
    with pytest.raises(ValueError):
        ev("__import__('os')")
    with pytest.raises(ValueError):
        ev("b + 1")
    with pytest.raises(ValueError):
        Evaluator({"side": 1})


def test_points_resolve_through_references_and_corners():
    p = Property(SQUARE)
    nw = p.point("nw"); ne = p.point("ne"); se = p.point("lot_se"); c = p.point("lot_center")
    assert abs(_m(nw, ne) - 1000 / 3.28084) < 0.5
    assert se[0] < nw[0] and se[1] > nw[1]
    assert nw[0] > c[0] > se[0] and nw[1] < c[1] < se[1]
    assert corner([nw, ne, se, (se[0], nw[1])], "sw") == (se[0], nw[1])


def test_layers_render_every_feature_kind():
    layers = {l["id"]: l for l in Property(SQUARE).layers()}
    assert [l for l in layers if layers[l]["default"]] == ["lot"]
    kinds = [f["properties"]["kind"] for f in layers["lot"]["features"]["features"]]
    assert kinds[0] == "line" and kinds.count("line") == 5 and kinds[-1] == "label"
    label = layers["lot"]["features"]["features"][-1]["properties"]
    assert label["text"] == "Lot" and label["legalText"] == "Lot 1, Block 2"
    shed = layers["shed"]["features"]["features"]
    assert shed[0]["properties"]["kind"] == "polygon" and len(shed[0]["geometry"]["coordinates"][0]) == 5
    assert shed[1]["properties"]["kind"] == "line" and len(shed[1]["geometry"]["coordinates"]) == 4
    photo = layers["photo"]["features"]["features"]
    assert photo[0]["properties"]["bounds"]["north"] > photo[0]["properties"]["bounds"]["south"]
    assert photo[1]["properties"]["missing"] == "overlays/missing.kml" and photo[1]["geometry"] is None


def test_unknown_reference_is_an_error():
    with pytest.raises(KeyError):
        Property({"points": {}, "layers": []}).point("nope")
