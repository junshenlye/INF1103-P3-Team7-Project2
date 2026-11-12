"""Stable issue-code vocabulary shared by processing components."""

DOCUMENT_PARSE_FAILED = "document_parse_failed"
DUPLICATE_DOCUMENT = "duplicate_document"
DUPLICATE_MODULE = "duplicate_module"
INVALID_DOCUMENT = "invalid_document"
INVALID_EXTRACTION = "invalid_extraction"
INVALID_REQUEST = "invalid_request"
INVALID_STORAGE_KEY = "invalid_storage_key"
NO_ASSESSMENTS = "no_assessments"
NOT_FOUND = "not_found"
PROCESSING_INTERRUPTED = "processing_interrupted"
PROJECT_FROZEN = "project_frozen"
PROVIDER_UNAVAILABLE = "provider_unavailable"
REQUEST_TOO_LARGE = "request_too_large"
REVISION_CONFLICT = "revision_conflict"
SERVICE_UNAVAILABLE = "service_unavailable"
SOURCE_MISSING = "source_missing"

CODES = frozenset(
    {
        DOCUMENT_PARSE_FAILED,
        DUPLICATE_DOCUMENT,
        DUPLICATE_MODULE,
        INVALID_DOCUMENT,
        INVALID_EXTRACTION,
        INVALID_REQUEST,
        INVALID_STORAGE_KEY,
        NO_ASSESSMENTS,
        NOT_FOUND,
        PROCESSING_INTERRUPTED,
        PROJECT_FROZEN,
        PROVIDER_UNAVAILABLE,
        REQUEST_TOO_LARGE,
        REVISION_CONFLICT,
        SERVICE_UNAVAILABLE,
        SOURCE_MISSING,
    }
)

INTERRUPTION_MESSAGE = "Processing stopped before the complete schedule was published."
PROVIDER_FAILURE_MESSAGE = "A processing service did not complete the task."
