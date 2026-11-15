import ast
from dataclasses import asdict
from pathlib import Path

import pytest

from src.config.settings import Settings
from src.managers.logic_manager import LogicManager


def test_four_manager_responsibilities_remain_identifiable():
    managers = {
        node.name
        for path in Path("src/managers").glob("*.py")
        for node in ast.parse(path.read_text()).body
        if isinstance(node, ast.ClassDef)
    }
    assert managers == {"DataManager", "LogicManager", "IOManager", "AIManager"}


def test_settings_reject_unsafe_values(tmp_path):
    with pytest.raises(ValueError):
        Settings("sqlite:///fake", tmp_path)
    with pytest.raises(ValueError):
        Settings("postgresql://local/test", Path("relative"))
    with pytest.raises(ValueError):
        Settings("postgresql://local/test", tmp_path, pool_size=100)


def test_migrations_project_and_restart(data, settings):
    project = data.create_project("Trimester", 14)
    data.create_schema()
    assert asdict(data.get_project(project.id)) == asdict(project)
    from src.managers.data_manager import DataManager

    with DataManager.create_pool(settings.database_url) as pool:
        restarted = DataManager(pool, settings.document_directory, logic_manager=LogicManager())
        assert asdict(restarted.get_project(project.id)) == asdict(project)
    with data.pool.connection() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"]
            == 7
        )


def test_manager_boundaries_and_constructor_composition():
    manager_dir = Path("src/managers")
    for path in manager_dir.glob("*.py"):
        tree = ast.parse(path.read_text())
        imports = {
            n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
        }
        imports |= {
            alias.name
            for n in ast.walk(tree)
            if isinstance(n, ast.Import)
            for alias in n.names
        }
        if path.stem != "io_manager":
            assert not any(
                n.startswith(("fastapi", "starlette", "flask")) for n in imports
            )
        if path.stem != "data_manager":
            assert not any(
                isinstance(n, ast.Attribute) and n.attr == "storage_key"
                for n in ast.walk(tree)
            )
            assert not any(
                n.startswith(("psycopg", "pathlib", "shutil", "PIL", "pypdf"))
                for n in imports
            )
        if path.stem in ("logic_manager", "data_manager"):
            assert not any(n.startswith("src.managers.") for n in imports)
        if path.stem == "logic_manager":
            assert not any(
                n.startswith(("asyncio", "httpx", "os", "openai")) for n in imports
            )
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                target = node.func.value
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and target.attr in {"_data", "_logic"}
                ):
                    assert not node.func.attr.startswith("_"), (path, node.func.attr)
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        for cls in classes:
            if cls.name not in ("IOManager", "AIManager"):
                continue
            init = next(
                n
                for n in cls.body
                if isinstance(n, ast.FunctionDef) and n.name == "__init__"
            )
            args = {a.arg for a in init.args.args}
            if cls.name in ("IOManager", "AIManager"):
                assert {"data_manager", "logic_manager"} <= args
