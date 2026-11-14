"""Guard responsibility boundaries between domain, processing and infrastructure.

These checks read the source with ``ast`` instead of importing it, so they
describe which code may depend on which libraries rather than how features
are implemented.
"""

import ast
from pathlib import Path
import sys
import unittest

from src.errors import error_codes

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

WEB_FRAMEWORK = {"fastapi", "starlette", "python_multipart", "uvicorn"}
DATABASE_DRIVER = {"psycopg", "psycopg_pool"}
HTTP_CLIENT = {"httpx"}
INFRASTRUCTURE = WEB_FRAMEWORK | DATABASE_DRIVER | HTTP_CLIENT | {"os", "pathlib", "shutil", "subprocess", "socket"}


def parse(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def module_name(path):
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def direct_imports(path):
    """Return absolute module names imported anywhere in ``path``."""
    package = module_name(path).split(".")
    if path.name != "__init__.py":
        package = package[:-1]
    names = set()
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                prefix = package[: len(package) - node.level + 1]
                base = ".".join(prefix + ([base] if base else []))
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def source_file(name):
    candidate = ROOT.joinpath(*name.split("."))
    for path in (candidate.with_suffix(".py"), candidate / "__init__.py"):
        if path.is_file():
            return path
    return None


def transitive_imports(path):
    """Return every module imported by ``path`` or by project modules it imports."""
    seen, pending, names = set(), [path], set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        for name in direct_imports(current):
            names.add(name)
            local = source_file(name) if name.split(".")[0] == "src" else None
            if local is not None:
                pending.append(local)
    return names


def top_level(names):
    return {name.split(".")[0] for name in names if name}


def importers_of(libraries):
    return sorted(
        path.relative_to(ROOT).as_posix()
        for path in SRC.rglob("*.py")
        if top_level(direct_imports(path)) & libraries
    )


class DomainIndependenceTests(unittest.TestCase):
    def test_logic_manager_has_no_transitive_infrastructure_dependency(self):
        used = top_level(transitive_imports(SRC / "managers" / "logic_manager.py"))
        self.assertEqual(used & INFRASTRUCTURE, set())

    def test_domain_models_have_no_infrastructure_dependency(self):
        for path in sorted((SRC / "models").rglob("*.py")):
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertEqual(top_level(transitive_imports(path)) & INFRASTRUCTURE, set())

    def test_domain_code_uses_only_the_standard_library(self):
        for path in [SRC / "managers" / "logic_manager.py", *sorted((SRC / "models").rglob("*.py"))]:
            external = {
                name
                for name in top_level(transitive_imports(path))
                if name != "src" and name not in sys.stdlib_module_names
            }
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertEqual(external, set())


class InfrastructureOwnershipTests(unittest.TestCase):
    def test_only_the_io_manager_uses_the_web_framework(self):
        for path in importers_of(WEB_FRAMEWORK):
            with self.subTest(path=path):
                self.assertEqual(path, "src/managers/io_manager.py")

    def test_only_storage_modules_use_the_database_driver(self):
        for path in importers_of(DATABASE_DRIVER):
            with self.subTest(path=path):
                self.assertTrue(path.startswith("src/storage/"), path)

    def test_only_entry_points_construct_http_clients(self):
        for path in importers_of(HTTP_CLIENT):
            with self.subTest(path=path):
                self.assertIn(path, {"src/main.py", "src/worker.py"})


class ContractTests(unittest.TestCase):
    def test_worker_code_only_calls_declared_worker_data_operations(self):
        contract = next(
            node
            for node in parse(SRC / "contracts" / "worker_data.py").body
            if isinstance(node, ast.ClassDef) and node.name == "WorkerData"
        )
        declared = {
            node.name
            for node in contract.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        used = set()
        for node in ast.walk(parse(SRC / "managers" / "ai_manager.py")):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
                and node.value.attr == "data"
            ):
                used.add(node.attr)
        for path in (SRC / "processing").glob("*.py"):
            for node in ast.walk(parse(path)):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "data":
                    used.add(node.attr)
        self.assertTrue(used, "No worker data operations were found.")
        self.assertEqual(used - declared, set())

    def test_issue_codes_are_written_only_in_the_shared_vocabulary(self):
        for path in sorted(SRC.rglob("*.py")):
            if path.name == "error_codes.py":
                continue
            literals = {
                node.value
                for node in ast.walk(parse(path))
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            }
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertEqual(literals & set(error_codes.CODES), set())


class ImportResolutionTests(unittest.TestCase):
    def test_relative_and_package_imports_are_followed(self):
        names = transitive_imports(SRC / "models" / "processing" / "checkpoint.py")
        self.assertIn("src.models.processing.frozen_data", names)
        self.assertIn("src.models.documents.source_element", names)

    def test_a_forbidden_library_would_be_detected(self):
        tree_imports = top_level({"fastapi.responses", "src.config", "os.path"})
        self.assertEqual(tree_imports & INFRASTRUCTURE, {"fastapi", "os"})


if __name__ == "__main__":
    unittest.main()
