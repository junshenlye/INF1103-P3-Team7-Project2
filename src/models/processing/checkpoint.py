"""Immutable checkpoints for reusing completed document processing work."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping

from src.models.documents.source_element import SourceElement

from .frozen_data import freeze


@dataclass(frozen=True)
class DocumentCheckpoint:
    """Capture a reusable parse and its accepted extraction chunks.

    Source elements and chunk payloads are detached from caller-owned
    containers so a saved checkpoint cannot change after construction.
    """

    parse_id: str | None
    elements: tuple[SourceElement, ...]
    chunks: Mapping[str, object]
    chunk_bytes: int
    chunk_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "elements",
            tuple(replace(element, regions=freeze(element.regions)) for element in self.elements),
        )
        object.__setattr__(self, "chunks", freeze(self.chunks))
        if self.chunk_bytes < 0:
            raise ValueError("chunk_bytes cannot be negative.")
        if self.chunk_count < 0:
            raise ValueError("chunk_count cannot be negative.")


@dataclass(frozen=True)
class ModuleCheckpoint:
    """Capture everything needed to reconcile one module's extracted records.

    ``records`` and ``uncertainties`` are the accepted candidates from the
    module's documents, in a deterministic order. ``source_ids`` are the
    citable source elements those records may reference. ``manifest``
    identifies the exact set of inputs, and ``unchanged`` reports that it
    matches the module's current published result, so reconciliation can be
    skipped. ``previous_assessments`` are the assessments of that published
    result (used to carry reviewed corrections forward) and
    ``previous_versions`` maps their ids to the review revision seen, so a
    concurrent review can be detected before publishing.

    All nested data is detached from caller-owned containers and frozen.
    """

    records: tuple[Mapping[str, object], ...]
    uncertainties: tuple[str, ...]
    source_ids: frozenset[str]
    manifest: str
    unchanged: bool
    previous_assessments: tuple[Mapping[str, object], ...] = ()
    previous_versions: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(freeze(r) for r in self.records))
        object.__setattr__(self, "uncertainties", tuple(self.uncertainties))
        object.__setattr__(self, "source_ids", frozenset(self.source_ids))
        object.__setattr__(
            self,
            "previous_assessments",
            tuple(freeze(a) for a in self.previous_assessments),
        )
        object.__setattr__(self, "previous_versions", freeze(self.previous_versions))
        if not isinstance(self.manifest, str) or not self.manifest:
            raise ValueError("manifest must be a nonempty string.")
        if any(not isinstance(item, str) for item in self.uncertainties):
            raise ValueError("uncertainties must be strings.")
        if any(not isinstance(item, str) for item in self.source_ids):
            raise ValueError("source_ids must be strings.")
