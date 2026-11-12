"""Validated input for one module in a submission."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubmitModuleRequest:
    """A module's titles and credit, plus the upload fields holding its documents.

    ``normalized_title`` is used to detect duplicate modules, and
    ``file_fields`` names the multipart fields that carry the module's files.
    """

    module_title: str
    normalized_title: str
    credit: int
    file_fields: tuple
