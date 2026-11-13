"""Validated runtime settings loaded from the process environment."""

from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse

from src.config import limits


@dataclass(frozen=True)
class Settings:
    """Immutable application settings with validation at construction time."""

    database_url: str
    document_directory: Path = Path("/data/documents")
    pool_size: int = limits.POOL_SIZE
    provider_timeout: float = limits.PROVIDER_TIMEOUT
    lease_seconds: int = limits.LEASE_SECONDS
    chunk_bytes: int = limits.CHUNK_BYTES
    max_chunks: int = limits.CHUNK_COUNT
    gpt_api_key: str = ""
    gpt_base_url: str = "https://api.openai.com/v1"
    gpt_model: str = ""
    gpt_concurrency: int = 2
    document_workers: int = 3
    docling_url: str = "http://docling:5001"

    def __post_init__(self):
        if urlparse(self.database_url).scheme not in {"postgres", "postgresql"}:
            raise ValueError("DATABASE_URL must identify PostgreSQL.")
        if not isinstance(self.document_directory, Path) or not self.document_directory.is_absolute():
            raise ValueError("DOCUMENT_DIRECTORY must be an absolute path.")
        if not 1 <= self.pool_size <= limits.MAX_POOL_SIZE:
            raise ValueError("DATABASE_POOL_SIZE is outside the supported range.")
        if self.lease_seconds < limits.MIN_LEASE_SECONDS:
            raise ValueError("JOB_LEASE_SECONDS is below the supported minimum.")
        if not limits.MIN_CHUNK_BYTES <= self.chunk_bytes <= limits.MAX_CHUNK_BYTES:
            raise ValueError("CHUNK_BYTES is outside the supported range.")
        if not 1 <= self.max_chunks <= limits.MAX_CHUNK_COUNT:
            raise ValueError("MAX_CHUNKS is outside the supported range.")
        if not 0 < self.provider_timeout <= limits.MAX_PROVIDER_TIMEOUT:
            raise ValueError("PROVIDER_TIMEOUT is outside the supported range.")
        if not 1 <= self.gpt_concurrency <= 8:
            raise ValueError("GPT_CONCURRENCY must be between 1 and 8.")
        if not 1 <= self.document_workers <= 8:
            raise ValueError("DOCUMENT_WORKERS must be between 1 and 8.")
        for name, value in (("GPT_BASE_URL", self.gpt_base_url), ("DOCLING_URL", self.docling_url)):
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"{name} must be an absolute HTTP(S) URL.")


def load_settings(environ=None):
    """Build validated settings from an environment mapping or os.environ."""
    env = os.environ if environ is None else environ
    return Settings(
        database_url=env["DATABASE_URL"],
        document_directory=Path(env.get("DOCUMENT_DIRECTORY", "/data/documents")),
        pool_size=int(env.get("DATABASE_POOL_SIZE", str(limits.POOL_SIZE))),
        provider_timeout=float(env.get("PROVIDER_TIMEOUT", str(limits.PROVIDER_TIMEOUT))),
        lease_seconds=int(env.get("JOB_LEASE_SECONDS", str(limits.LEASE_SECONDS))),
        chunk_bytes=int(env.get("CHUNK_BYTES", str(limits.CHUNK_BYTES))),
        max_chunks=int(env.get("MAX_CHUNKS", str(limits.CHUNK_COUNT))),
        gpt_api_key=env.get("GPT_API_KEY") or env.get("OPENAI_API_KEY", ""),
        gpt_base_url=env.get("GPT_BASE_URL", "https://api.openai.com/v1"),
        gpt_model=env.get("GPT_MODEL") or env.get("OPENAI_MODEL", ""),
        gpt_concurrency=int(env.get("GPT_CONCURRENCY", "2")),
        document_workers=int(env.get("DOCUMENT_WORKERS", "3")),
        docling_url=env.get("DOCLING_URL", "http://docling:5001"),
    )
