"""Safe domain exception that does not expose provider or transport details."""

from src.errors.error_codes import CODES, PROVIDER_FAILURE_MESSAGE, PROVIDER_UNAVAILABLE


class ProcessingError(Exception):
    """A stable processing failure with optional related domain identifiers."""

    def __init__(self, code, message, scope="request", **related_ids):
        if code not in CODES:
            raise ValueError("Unknown processing issue code.")
        super().__init__(message)
        self.code = code
        self.message = message
        self.scope = scope
        self.related_ids = related_ids


def safe_processing_error(error):
    """Return ``error`` if it is a ProcessingError, otherwise a generic system failure.

    Unexpected exceptions from providers, parsers or transports can carry
    internal details such as URLs, response bodies or file paths. Those
    details are never copied: the replacement only says that a processing
    service did not complete the task. Callers should chain the original
    exception (``raise ... from error``) to keep it available for logs.
    """
    if isinstance(error, ProcessingError):
        return error
    return ProcessingError(PROVIDER_UNAVAILABLE, PROVIDER_FAILURE_MESSAGE, "system")
