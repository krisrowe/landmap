from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from landmap.server import create_app

KEY = "test-" + "k" * 12


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(data_path=tmp_path / "data", access_key=KEY)
    return TestClient(app)


def h():
    return {"x-access-key": KEY}


def test_property_is_public_and_complete(client):
    doc = client.get("/api/property").json()
    assert doc["name"] == "Example 40" and doc["example"] is True and doc["zoom"] >= 14
    ids = [l["id"] for l in doc["layers"]]
    assert "forty" in ids and all(l["features"]["type"] == "FeatureCollection" for l in doc["layers"])
    assert client.get("/overlays/traced-boundary.kml").status_code == 200
    assert client.get("/overlays/../property.yaml").status_code in (404, 400)
    assert client.get("/overlays/nope.kml").status_code == 404


def test_boundary_is_public_and_pins_are_keyed(client):
    assert client.get("/api/property").status_code == 200
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


def test_property_comes_from_the_data_directory_and_reloads(tmp_path: Path):
    """A definition dropped into <data>/property replaces the example without a restart."""
    import shutil, time
    from landmap.data import EXAMPLE
    data = tmp_path / "data"
    client = TestClient(create_app(data_path=data, access_key=KEY))
    assert client.get("/api/property").json()["example"] is True
    shutil.copytree(EXAMPLE, data / "property")
    spec = data / "property" / "property.yaml"
    spec.write_text(spec.read_text().replace("name: Example 40", "name: Mine"))
    doc = client.get("/api/property").json()
    assert doc["name"] == "Mine" and doc["example"] is False
    assert client.get("/overlays/traced-boundary.kml").status_code == 200
    time.sleep(0.01)
    spec.write_text(spec.read_text().replace("name: Mine", "name: Renamed"))
    assert client.get("/api/property").json()["name"] == "Renamed"


def test_property_override_wins(tmp_path: Path):
    import shutil
    from landmap.data import EXAMPLE
    mine = tmp_path / "elsewhere"
    shutil.copytree(EXAMPLE, mine)
    (mine / "property.yaml").write_text((mine / "property.yaml").read_text().replace("name: Example 40", "name: Elsewhere"))
    client = TestClient(create_app(data_path=tmp_path / "data", access_key=KEY, property_dir=mine))
    assert client.get("/api/property").json()["name"] == "Elsewhere"
