"""Immutable, transport-neutral details for a processing issue."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProcessingIssue:
    code: str
    message: str
    scope: str
    severity: str = "error"
    job_id: Optional[str] = None
    module_id: Optional[str] = None
    document_id: Optional[str] = None
