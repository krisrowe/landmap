"""The data directory: everything about one piece of land, outside the code.

    <data>/
      property/            the definition (property.yaml) and its overlays/
      pins.json            places tagged on the ground
      tracks/              (planned) recorded walks

The server reads the directory given by LANDMAP_DATA_PATH. Point it at a local
folder to run against your own land; when deployed, point it at whatever
persistent path the deployment provides and copy the property folder there.
Nothing in this repo is specific to a real property: when the data directory
has no definition yet, the bundled example property is served instead, so a
fresh checkout and a freshly deployed service both show a working map.
"""

from pathlib import Path

from .resolver import Property

EXAMPLE = Path(__file__).resolve().parent.parent / "properties" / "example"
DEFINITION = "property.yaml"


class PropertySource:
    """Resolves the current property definition lazily and re-reads it when the
    file changes, so updating the data directory needs no restart."""

    def __init__(self, data_path: Path, override: Path | None = None):
        self.data_path = Path(data_path)
        self.override = Path(override) if override else None
        self._stamp = None
        self._doc = None

    def directory(self) -> Path:
        """Where the definition comes from right now, with the example as the fallback."""
        for candidate in (self.override, self.data_path / "property"):
            if candidate and (candidate / DEFINITION).is_file():
                return candidate
        return EXAMPLE

    def document(self) -> dict:
        directory = self.directory()
        path = directory / DEFINITION
        stamp = (str(directory), path.stat().st_mtime_ns)
        if stamp != self._stamp:
            prop = Property.load(path)
            self._doc = {**prop.info(), "layers": prop.layers(), "example": directory == EXAMPLE}
            self._stamp = stamp
        return self._doc

    def overlay(self, name: str) -> Path | None:
        """A file under the current property's overlays/, or None; never a path outside it."""
        root = (self.directory() / "overlays").resolve()
        path = (root / name).resolve()
        if root not in path.parents or not path.is_file():
            return None
        return path
