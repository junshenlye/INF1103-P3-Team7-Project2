"""Safe domain exception that does not expose provider or transport details."""

from src.errors.error_codes import CODES


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
