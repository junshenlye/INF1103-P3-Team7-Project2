"""ASGI application factory for the container runtime."""

from contextlib import asynccontextmanager

from src.config.settings import load_settings
from src.managers import DataManager, LogicManager
from src.managers.io_manager import IOManager
from src.storage.postgres_pool import open_postgres_pool


def create_app(settings=None, data=None):
    """Build the application and bind the database pool to its lifespan."""
    settings = settings or load_settings()
    manager = IOManager(data, LogicManager())
    if data is not None:
        return manager.get_application()

    @asynccontextmanager
    async def lifespan(_app):
        with open_postgres_pool(settings) as pool:
            manager.data = DataManager(pool, document_directory=settings.document_directory)
            try:
                yield
            finally:
                manager.data = None

    return manager.get_application(lifespan=lifespan)
