"""One-worker container entry point for the isolated document trial."""

import os
from .demo import create_demo

app = create_demo(
    os.environ.get("STACKPLAN_DOCUMENT_DIRECTORY", "/tmp/stackplan-document-trial"),
    os.environ.get("DOCLING_URL", "http://127.0.0.1:15001"),
)
