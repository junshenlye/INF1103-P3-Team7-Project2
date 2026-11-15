from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True, eq=False)
class Document:
    id: str
    module_id: str
    filename: str
    media_type: str
    size: int
    checksum: str
    _storage_key: str
    _sources: tuple["SourceElement", ...] = field(default=(), repr=False, compare=False)

    @property
    def storage_key(self):
        return self._storage_key

    def get_sources(self):
        """Return references wired and ownership-checked by DataManager."""
        return self._sources
