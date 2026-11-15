"""Build safe issue data without transport, persistence or provider behaviour."""

from src.errors.processing_error import ProcessingError


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
    return ProcessingError(code, message, scope).to_issue(
        severity=severity, job_id=job_id, module_id=module_id, document_id=document_id)


def issue_from_error(error, *, module_id=None, document_id=None):
    return error.to_issue(module_id=module_id, document_id=document_id)
