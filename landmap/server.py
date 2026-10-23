"""HTTP API and static front end for Land Map.

Configuration comes from the environment:
  LANDMAP_DATA_PATH   the data directory (default ./data); see landmap/data.py
  LANDMAP_PROPERTY    property definition directory, overriding <data>/property
  LANDMAP_ACCESS_KEY  key required to read or change pins; unset = open
"""

import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .data import PropertySource
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
               property_dir: Path | None = None) -> FastAPI:
    data_path = Path(data_path or os.environ.get("LANDMAP_DATA_PATH", "data"))
    access_key = access_key if access_key is not None else os.environ.get("LANDMAP_ACCESS_KEY", "")
    override = property_dir or os.environ.get("LANDMAP_PROPERTY")

    store = PinStore(data_path)
    source = PropertySource(data_path, Path(override) if override else None)
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

    @app.get("/api/session", dependencies=guarded)
    def session():
        """Succeeds only with a valid key; the page uses it to decide whether to show pins."""
        return {"ok": True}

    @app.get("/api/property")
    def get_property():
        """Name, center, and every layer as GeoJSON with its default visibility. Public.

        Re-read when the definition file changes, so a property dropped onto the
        data directory of a running server shows up on the next load."""
        return source.document()

    @app.get("/overlays/{name:path}")
    def overlay(name: str):
        """The current property's image and KML files. Public."""
        path = source.overlay(name)
        if path is None:
            raise HTTPException(status_code=404, detail="no such overlay")
        return FileResponse(path)

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

    @app.get("/sw.js")
    def service_worker():
        # Served from the root so the worker may control the whole site.
        return FileResponse(STATIC / "sw.js", media_type="application/javascript")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
