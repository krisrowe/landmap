"""Pin storage: one JSON file on disk, safe for a single process.

The file lives under the data path, which on Cloud Run is a GCS-backed
mount, so pins survive restarts and redeploys.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PinStore:
    def __init__(self, data_path: Path):
        self.path = Path(data_path) / "pins.json"
        self._lock = threading.Lock()

    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open() as fh:
            return json.load(fh)

    def _write(self, pins: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with tmp.open("w") as fh:
            json.dump(pins, fh, indent=1)
        os.replace(tmp, self.path)

    def list(self) -> list[dict]:
        with self._lock:
            return self._read()

    def get(self, pin_id: str) -> dict | None:
        return next((t for t in self.list() if t["id"] == pin_id), None)

    def add(self, label: str, lat: float, lng: float,
            accuracy: float | None = None, note: str = "") -> dict:
        pin = {
            "id": uuid.uuid4().hex[:10],
            "label": label,
            "lat": lat,
            "lng": lng,
            "accuracy": accuracy,
            "note": note,
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._lock:
            pins = self._read()
            pins.append(pin)
            self._write(pins)
        return pin

    def update(self, pin_id: str, **fields) -> dict | None:
        with self._lock:
            pins = self._read()
            for pin in pins:
                if pin["id"] == pin_id:
                    pin.update({k: v for k, v in fields.items() if v is not None})
                    pin["updated_at"] = _now()
                    self._write(pins)
                    return pin
        return None

    def delete(self, pin_id: str) -> bool:
        with self._lock:
            pins = self._read()
            kept = [t for t in pins if t["id"] != pin_id]
            if len(kept) == len(pins):
                return False
            self._write(kept)
        return True
