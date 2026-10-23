from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from landmap.boundary import DEFAULT_KML, bounds, load_boundary
from landmap.server import create_app

KEY = "test-" + "k" * 12


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(data_path=tmp_path / "data", access_key=KEY)
    return TestClient(app)


def h():
    return {"x-access-key": KEY}


def test_boundary_parses_bundled_kml():
    fc = load_boundary(DEFAULT_KML)
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1
    ring = fc["features"][0]["geometry"]["coordinates"][0]
    assert len(ring) == 5 and ring[0] == ring[-1]
    lng, lat = ring[0]
    assert -180 <= lng <= 180 and -90 <= lat <= 90
    box = bounds(fc)
    assert box["south"] < box["north"] and box["west"] < box["east"]


def test_boundary_is_public_and_pins_are_keyed(client):
    assert client.get("/api/boundary").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/healthz").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/api/session").status_code == 401
    assert client.get("/api/pins").status_code == 401
    assert client.get("/api/pins", headers={"x-access-key": "wrong"}).status_code == 401
    assert client.post("/api/pins", json={"label": "x", "lat": 1, "lng": 1}).status_code == 401
    assert client.get("/api/session", headers=h()).status_code == 200
    assert client.get("/api/pins", params={"key": KEY}).status_code == 200


def test_open_mode_when_no_key(tmp_path):
    app = create_app(data_path=tmp_path, access_key="")
    assert TestClient(app).get("/api/pins").status_code == 200


def test_pin_crud_roundtrip(client, tmp_path):
    r = client.post("/api/pins", headers=h(), json={
        "label": "  NE corner post ", "lat": 45.1234, "lng": -100.5678, "accuracy": 4.2})
    assert r.status_code == 201
    pin = r.json()
    assert pin["label"] == "NE corner post" and pin["accuracy"] == 4.2 and pin["id"]

    assert [t["id"] for t in client.get("/api/pins", headers=h()).json()] == [pin["id"]]

    r = client.patch(f"/api/pins/{pin['id']}", headers=h(), json={"label": "NE corner", "note": "found pin"})
    assert r.status_code == 200
    assert r.json()["label"] == "NE corner" and r.json()["note"] == "found pin"
    assert r.json()["lat"] == 45.1234

    assert (tmp_path / "data" / "pins.json").exists()

    assert client.delete(f"/api/pins/{pin['id']}", headers=h()).status_code == 204
    assert client.get("/api/pins", headers=h()).json() == []
    assert client.delete(f"/api/pins/{pin['id']}", headers=h()).status_code == 404


def test_pin_validation(client):
    assert client.post("/api/pins", headers=h(), json={"label": "", "lat": 0, "lng": 0}).status_code == 422
    assert client.post("/api/pins", headers=h(), json={"label": "x", "lat": 91, "lng": 0}).status_code == 422
    assert client.patch("/api/pins/nope", headers=h(), json={"label": "y"}).status_code == 404


def test_store_survives_new_app_instance(tmp_path):
    first = TestClient(create_app(data_path=tmp_path, access_key=""))
    first.post("/api/pins", json={"label": "pond inlet", "lat": 45.2, "lng": -100.6})
    second = TestClient(create_app(data_path=tmp_path, access_key=""))
    assert [t["label"] for t in second.get("/api/pins").json()] == ["pond inlet"]
