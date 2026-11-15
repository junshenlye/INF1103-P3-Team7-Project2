from __future__ import annotations


from src.errors.error_codes import CODES


class ProcessingError(Exception):
    """A safe domain failure, without transport or provider details."""

    def __init__(self, code, message, scope="request", **related_ids):
        if code not in CODES:
            raise ValueError("Unknown processing issue code.")
        super().__init__(message)
        self.code = code
        self.message = message
        self.scope = scope
        self.related_ids = related_ids

    def to_issue(self, *, severity='error', job_id=None, module_id=None, document_id=None):
        """Return safe primitive issue data; never expose rejected provider payloads."""
        related = {'job_id': job_id, 'module_id': module_id,
                   'document_id': document_id, **self.related_ids}
        return {'code': self.code, 'message': self.message, 'scope': self.scope,
                'severity': severity, 'job_id': related.get('job_id'),
                'module_id': related.get('module_id'), 'document_id': related.get('document_id')}
