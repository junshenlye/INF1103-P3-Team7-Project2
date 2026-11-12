"""Response body for a rejected request."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorResponse:
    """One or more structured issues explaining why a request failed."""

    issues: list
