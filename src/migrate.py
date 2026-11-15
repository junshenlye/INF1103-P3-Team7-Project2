from src.managers.data_manager import DataManager
from src.managers.logic_manager import LogicManager
from src.config.settings import load_settings


def main():
    settings = load_settings()
    with DataManager.create_pool(settings.database_url, settings.pool_size) as pool:
        data = DataManager(pool, settings.document_directory, logic_manager=LogicManager())
        data.create_schema()
        data.repair_completed_outcomes()


if __name__ == "__main__":
    main()
