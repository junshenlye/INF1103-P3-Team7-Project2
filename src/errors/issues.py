"""Build safe issue dictionaries from validated domain errors."""

from dataclasses import asdict

from src.errors import error_codes
from src.errors.processing_issue import ProcessingIssue


def make_issue(
    code,
    message,
    scope="system",
    *,
    severity="error",
    job_id=None,
    module_id=None,
    document_id=None,
):
    """Return a serialisable issue, rejecting codes outside the shared vocabulary."""
    if code not in error_codes.CODES:
        raise ValueError("Unknown processing issue code.")
    issue = ProcessingIssue(
        code, message, scope, severity, job_id, module_id, document_id
    )
    return asdict(issue)


def issue_from_error(error, *, module_id=None, document_id=None):
    """Convert a ProcessingError while preserving its related identifiers."""
    related = {"module_id": module_id, "document_id": document_id, **error.related_ids}
    return make_issue(error.code, error.message, error.scope, **related)
