"""Validated runtime settings loaded from the process environment."""

from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    database_url: str
    document_directory: Path = Path("/data/documents")
    database_pool_size: int = 4
    gpt_api_key: str = ""
    gpt_base_url: str = "https://api.openai.com/v1"
    gpt_model: str = ""
    gpt_concurrency: int = 2
    document_workers: int = 3
    docling_url: str = "http://docling:5001"

    def __post_init__(self):
        if urlparse(self.database_url).scheme not in {"postgres", "postgresql"}:
            raise ValueError("DATABASE_URL must identify PostgreSQL.")
        if not self.document_directory.is_absolute():
            raise ValueError("DOCUMENT_DIRECTORY must be an absolute path.")
        if not 1 <= self.database_pool_size <= 16:
            raise ValueError("DATABASE_POOL_SIZE must be between 1 and 16.")
        if not 1 <= self.gpt_concurrency <= 8:
            raise ValueError("GPT_CONCURRENCY must be between 1 and 8.")
        if not 1 <= self.document_workers <= 8:
            raise ValueError("DOCUMENT_WORKERS must be between 1 and 8.")
        for name, value in (("GPT_BASE_URL", self.gpt_base_url), ("DOCLING_URL", self.docling_url)):
            if urlparse(value).scheme not in {"http", "https"} or not urlparse(value).netloc:
                raise ValueError(f"{name} must be an absolute HTTP(S) URL.")


def load_settings(environ=None):
    """Build settings from an environment mapping (or os.environ by default)."""
    env = os.environ if environ is None else environ
    return Settings(
        database_url=env["DATABASE_URL"],
        document_directory=Path(env.get("DOCUMENT_DIRECTORY", "/data/documents")),
        database_pool_size=int(env.get("DATABASE_POOL_SIZE", "4")),
        gpt_api_key=env.get("GPT_API_KEY") or env.get("OPENAI_API_KEY", ""),
        gpt_base_url=env.get("GPT_BASE_URL", "https://api.openai.com/v1"),
        gpt_model=env.get("GPT_MODEL") or env.get("OPENAI_MODEL", ""),
        gpt_concurrency=int(env.get("GPT_CONCURRENCY", "2")),
        document_workers=int(env.get("DOCUMENT_WORKERS", "3")),
        docling_url=env.get("DOCLING_URL", "http://docling:5001"),
    )
