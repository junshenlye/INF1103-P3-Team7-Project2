"""Immutable checkpoints for reusing completed document processing work."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
