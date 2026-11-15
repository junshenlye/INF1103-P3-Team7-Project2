from src.managers.data_manager import DataManager
from src.managers.io_manager import IOManager
from src.managers.logic_manager import LogicManager
from src.config.settings import load_settings


def create_app(settings=None, data=None):
    settings = settings or load_settings()
    owns_pool = data is None
    logic = data.logic_manager if data is not None else LogicManager()
    if data is None:
        pool = DataManager.create_pool(settings.database_url, settings.pool_size)
        data = DataManager(
            pool,
            settings.document_directory,
            settings.document_bytes,
            settings.lease_seconds,
            logic_manager=logic,
        )
    io = IOManager(
        data, logic, settings.request_bytes, settings.document_bytes
    )
    return io.get_application(data.pool.close if owns_pool else None)
