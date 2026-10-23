"""HTTP API and static front end for Land Map.

Configuration comes from the environment:
  LANDMAP_DATA_PATH   directory for pins.json (default ./data)
  LANDMAP_ACCESS_KEY  shared key required on every /api call; unset = open
  LANDMAP_KML         boundary KML to serve (default the bundled one)
"""

import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .boundary import bounds, load_boundary
from .store import PinStore

STATIC = Path(__file__).with_name("static")


class PinIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0)
    note: str = Field(default="", max_length=2000)


class PinPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=2000)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


def create_app(data_path: Path | None = None, access_key: str | None = None,
               kml_path: Path | None = None) -> FastAPI:
    data_path = Path(data_path or os.environ.get("LANDMAP_DATA_PATH", "data"))
    access_key = access_key if access_key is not None else os.environ.get("LANDMAP_ACCESS_KEY", "")
    kml_path = kml_path or (Path(os.environ["LANDMAP_KML"]) if os.environ.get("LANDMAP_KML") else None)

    store = PinStore(data_path)
    boundary = load_boundary(kml_path)
    app = FastAPI(title="Land Map", docs_url=None, redoc_url=None)

    def require_key(request: Request) -> None:
        if not access_key:
            return
        supplied = request.headers.get("x-access-key") or request.query_params.get("key", "")
        if not secrets.compare_digest(supplied, access_key):
            raise HTTPException(status_code=401, detail="access key required")

    guarded = [Depends(require_key)]

    @app.get("/health")
    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/api/boundary", dependencies=guarded)
    def get_boundary():
        return {"boundary": boundary, "bounds": bounds(boundary)}

    @app.get("/api/pins", dependencies=guarded)
    def list_pins():
        return store.list()

    @app.post("/api/pins", dependencies=guarded, status_code=201)
    def add_pin(pin: PinIn):
        return store.add(pin.label.strip(), pin.lat, pin.lng, pin.accuracy, pin.note.strip())

    @app.patch("/api/pins/{pin_id}", dependencies=guarded)
    def patch_pin(pin_id: str, patch: PinPatch):
        fields = patch.model_dump()
        if fields.get("label") is not None:
            fields["label"] = fields["label"].strip()
        updated = store.update(pin_id, **fields)
        if updated is None:
            raise HTTPException(status_code=404, detail="no such pin")
        return updated

    @app.delete("/api/pins/{pin_id}", dependencies=guarded, status_code=204)
    def delete_pin(pin_id: str):
        if not store.delete(pin_id):
            raise HTTPException(status_code=404, detail="no such pin")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
