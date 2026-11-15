from __future__ import annotations
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.managers.data_manager import DataManager
from src.managers.logic_manager import LogicManager
from src.config.settings import Settings


@pytest.fixture(scope='session')
def test_database_url():
    url = os.getenv('STACKPLAN_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set STACKPLAN_TEST_DATABASE_URL to a disposable database ending in _test.')
    from urllib.parse import urlparse
    if not urlparse(url).path.endswith('_test'):
        pytest.fail('Test safety guard: database name must end in _test.')
    return url


@pytest.fixture
def settings(test_database_url,tmp_path):
    return Settings(test_database_url,tmp_path/'documents',lease_seconds=3)


@pytest.fixture
def data(settings):
    pool = DataManager.create_pool(settings.database_url)
    # This reset is permitted only by the explicit disposable-database guard.
    with pool.connection() as conn:
        conn.execute('DROP SCHEMA IF EXISTS stackplan CASCADE')
    manager = DataManager(pool,settings.document_directory,lease_seconds=settings.lease_seconds, logic_manager=LogicManager())
    manager.create_schema()
    yield manager
    for request_id in {d['request_id'] for d,_,_ in list(manager._staging.values())}:
        manager.discard_staged_documents(request_id)
    pool.close()
