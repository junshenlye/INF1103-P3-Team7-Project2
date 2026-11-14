"""ASGI application factory for the container runtime."""

from src.config.settings import load_settings
from src.managers import DataManager, IOManager, LogicManager
from src.storage.postgres_pool import open_postgres_pool


def create_app(settings=None, data=None):
    settings = settings or load_settings()
    if data is not None:
        return IOManager(data, LogicManager()).get_application()
    pool_context = open_postgres_pool(settings)
    pool = pool_context.__enter__()
    app = IOManager(DataManager(pool), LogicManager()).get_application()
    app.add_event_handler("shutdown", lambda: pool_context.__exit__(None, None, None))
    return app
