from src.config import limits
from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    database_url: str
    document_directory: Path
    pool_size: int = limits.POOL_SIZE
    request_bytes: int = limits.REQUEST_BYTES
    document_bytes: int = limits.DOCUMENT_BYTES
    chunk_bytes: int = limits.CHUNK_BYTES
    max_chunks: int = limits.CHUNK_COUNT
    provider_timeout: float = limits.PROVIDER_TIMEOUT
    lease_seconds: int = limits.LEASE_SECONDS
    gpt_api_key: str = ""
    gpt_base_url: str = "https://api.openai.com/v1"
    gpt_model: str = ""
    gpt_concurrency: int = 2
    document_workers: int = 3
    docling_url: str = "http://docling:5001"

    def __post_init__(self):
        self.validate()

    def validate(self):
        if not 1 <= self.gpt_concurrency <= 8 or not 1 <= self.document_workers <= 8:
            raise ValueError("Worker concurrency must be between 1 and 8.")
        if urlparse(self.database_url).scheme not in {"postgresql", "postgres"}:
            raise ValueError("DATABASE_URL must identify PostgreSQL.")
        if not Path(self.document_directory).is_absolute():
            raise ValueError("DOCUMENT_DIRECTORY must be absolute.")
        if (
            not 1 <= self.pool_size <= limits.MAX_POOL_SIZE
            or self.lease_seconds < limits.MIN_LEASE_SECONDS
        ):
            raise ValueError("Invalid connection pool or lease bounds.")
        if (
            not limits.MIN_CHUNK_BYTES <= self.chunk_bytes <= limits.MAX_CHUNK_BYTES
            or not 1 <= self.max_chunks <= limits.MAX_CHUNK_COUNT
        ):
            raise ValueError("Invalid parse bounds.")
        if not 0 < self.document_bytes <= self.request_bytes <= limits.REQUEST_BYTES:
            raise ValueError("Invalid upload bounds.")
        if not 0 < self.provider_timeout <= limits.MAX_PROVIDER_TIMEOUT:
            raise ValueError("Invalid provider timeout.")
        if urlparse(self.docling_url).scheme not in {"http", "https"}:
            raise ValueError("Invalid Docling URL.")
        if urlparse(self.gpt_base_url).scheme not in {"http", "https"}:
            raise ValueError("Invalid GPT URL.")


def load_settings():
    return Settings(
        database_url=os.environ["DATABASE_URL"],
        document_directory=Path(os.getenv("DOCUMENT_DIRECTORY", "/data/documents")),
        pool_size=int(os.getenv("DATABASE_POOL_SIZE", str(limits.POOL_SIZE))),
        lease_seconds=int(os.getenv("JOB_LEASE_SECONDS", str(limits.LEASE_SECONDS))),
        gpt_api_key=os.getenv("GPT_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
        gpt_base_url=os.getenv("GPT_BASE_URL", "https://api.openai.com/v1"),
        gpt_model=os.getenv("GPT_MODEL") or os.getenv("OPENAI_MODEL", ""),
        gpt_concurrency=int(os.getenv("GPT_CONCURRENCY", "2")),
        document_workers=int(os.getenv("DOCUMENT_WORKERS", "3")),
        docling_url=os.getenv("DOCLING_URL", "http://docling:5001"),
    )
