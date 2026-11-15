"""Review gates guard responsibility boundaries, not specific implementations."""

import ast
from pathlib import Path

from src.config import limits
from src.errors import error_codes


def tree(name):
    return ast.parse(Path(name).read_text())


def imported_modules(path, seen=None):
    seen = set() if seen is None else seen
    if path in seen:
        return set()
    seen.add(path)
    result = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.Import):
            result.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            result.add(node.module or "")
            if node.module and (node.module == "src" or node.module.startswith("src.")):
                result.update(node.module + "." + a.name for a in node.names)
    for name in tuple(result):
        local = Path(name.replace(".", "/")).with_suffix(".py")
        if not local.is_file():
            local = Path(name.replace(".", "/")) / "__init__.py"
        if name.startswith("src.") and local.is_file():
            result.update(imported_modules(local, seen))
    return result


def test_logic_has_no_transitive_infrastructure_dependency():
    imports = imported_modules(Path("src/managers/logic_manager.py"))
    forbidden = (
        "fastapi",
        "starlette",
        "flask",
        "httpx",
        "psycopg",
        "pathlib",
        "os",
        "shutil",
        "docling",
        "openai",
    )
    assert not any(
        name == prefix or name.startswith(prefix + ".")
        for name in imports
        for prefix in forbidden
    )


def test_infrastructure_and_domain_implementations_have_single_owners():
    for path in Path("src/managers").glob("*.py"):
        for node in ast.walk(tree(path)):
            if isinstance(node, ast.Call):
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if name in {
                    "execute",
                    "transaction",
                    "cursor",
                    "open",
                    "mkdir",
                    "unlink",
                    "resolve",
                    "read_text",
                    "write_text",
                    "rmtree",
                }:
                    assert path.stem == "data_manager", (path, name)
                if name == "build_schedule":
                    assert (
                        path.stem == "logic_manager"
                        or (
                            path.stem == "io_manager"
                            and isinstance(node.func.value, ast.Attribute)
                            and node.func.value.attr == "_logic"
                        )
                    )
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "build_schedule"
            ):
                assert path.stem == "logic_manager"
        classes = [n for n in tree(path).body if isinstance(n, ast.ClassDef)]
        for cls in classes:
            for method in cls.body:
                if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for call in (n for n in ast.walk(method) if isinstance(n, ast.Call)):
                    name = (
                        call.func.id
                        if isinstance(call.func, ast.Name)
                        else call.func.attr
                        if isinstance(call.func, ast.Attribute)
                        else ""
                    )
                    if name in {
                        "ConnectionPool",
                        "create_pool",
                        "AsyncClient",
                        "DataManager",
                        "LogicManager",
                        "AIManager",
                        "IOManager",
                    }:
                        assert (
                            path.stem == "data_manager" and method.name == "create_pool"
                        ), (path, method.name, name)
    assert not any(
        p.name.startswith(("base_manager", "repository", "event_bus"))
        for p in Path("src").rglob("*.py")
    )


def test_injected_contracts_contain_only_operations_their_consumer_uses():
    ai = tree("src/managers/ai_manager.py")
    for attribute, contract in [
        ("_data", "worker_data"),
        ("_docling", "provider_client"),
        ("_gpt", "provider_client"),
    ]:
        used = set()
        for node in ast.walk(ai):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
                and node.value.attr == attribute
            ):
                used.add(node.attr)
        protocol = next(
            n
            for n in tree(f"src/contracts/{contract}.py").body
            if isinstance(n, ast.ClassDef)
        )
        declared = {
            n.name
            for n in protocol.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert used == declared, (attribute, used, declared)


def test_issue_codes_are_defined_once_and_only_io_maps_them_to_http():
    for path in Path("src").rglob("*.py"):
        if path.name == "error_codes.py":
            continue
        assert not any(
            isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and n.value in error_codes.CODES
            for n in ast.walk(tree(path))
        ), path
    assert len(error_codes.CODES) == 16
    assert not Path("frontend/app.py").exists()  # The app has one HTTP boundary.


def test_sql_terminal_writes_have_one_persistence_implementation():
    manager = next(
        n
        for n in tree("src/managers/data_manager.py").body
        if isinstance(n, ast.ClassDef)
    )
    owners = []
    for method in manager.body:
        if not isinstance(method, ast.FunctionDef):
            continue
        for value in (
            n.value
            for n in ast.walk(method)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ):
            if (
                value.startswith("UPDATE processing_jobs SET status=%s")
                and "lease_token=NULL" in value
            ):
                owners.append(method.name)
    assert owners == ["_finish_job"]
    assert (
        limits.MULTIPART_PART_COUNT
        == limits.MODULE_COUNT * limits.DOCUMENTS_PER_MODULE + 1
    )


def test_exact_uml_inventory_and_explicit_worker_interface():
    from inspect import isabstract
    from src.contracts.worker_data import WorkerData
    from src.managers.data_manager import DataManager

    names = [node.name for path in Path('src').rglob('*.py')
             for node in ast.walk(tree(path)) if isinstance(node, ast.ClassDef)]
    expected = {
        'IOManager', 'AIManager', 'LogicManager', 'DataManager',
        'Project', 'Module', 'Document', 'SourceElement', 'ProcessingJob',
        'Assessment', 'IndividualAssessment', 'AssessmentGroup', 'Schedule',
        'Settings', 'ProcessingError', 'WorkerData', 'ProviderClient',
    }
    assert len(names) == 17 and set(names) == expected
    assert isabstract(WorkerData) and not isabstract(DataManager)
    assert WorkerData in DataManager.__bases__


def test_entities_never_construct_inspect_or_call_another_entity():
    entity_names = {
        'Project', 'Module', 'Document', 'SourceElement', 'ProcessingJob',
        'Assessment', 'IndividualAssessment', 'AssessmentGroup', 'Schedule',
    }
    for path in Path('src/models').rglob('*.py'):
        module = tree(path)
        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith(('src.managers', 'src.processing', 'src.contracts'))
                if (node.module or '').startswith('src.models.') and node.module not in {'src.models.processing', 'src.models.processing.lifecycle'}:
                    # The only runtime peer imports establish the declared is-a relationship.
                    assert path.name in ('individual_assessment.py', 'assessment_group.py')
                    assert node.module == 'src.models.assessments.assessment'
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in entity_names | {'getattr', 'setattr', 'eval', 'exec'}, (path, node.lineno)
            if isinstance(node, ast.Attribute):
                root = node
                while isinstance(root, (ast.Attribute, ast.Subscript)):
                    root = root.value
                # Only own state, own primitive containers and standard object assignment.
                assert isinstance(root, ast.Name) and root.id in {'self', 'object'}, (path, node.lineno, ast.unparse(node))
            if isinstance(node, ast.Attribute) and node.attr in {'_assessments', '_sources'}:
                parents = {child: parent for parent in ast.walk(module) for child in ast.iter_child_nodes(parent)}
                assert isinstance(parents[node], ast.Return), (path, node.lineno)


def test_business_rules_are_injected_instead_of_constructed_inside_managers():
    manager = next(node for node in tree('src/managers/data_manager.py').body
                   if isinstance(node, ast.ClassDef))
    constructor = next(node for node in manager.body if isinstance(node, ast.FunctionDef) and node.name == '__init__')
    assert 'logic_manager' in {arg.arg for arg in constructor.args.kwonlyargs}
    names = {node.attr for node in ast.walk(manager) if isinstance(node, ast.Attribute)
             and isinstance(node.value, ast.Attribute) and node.value.attr == '_logic'}
    assert {'can_retry_document', 'settled_status', 'build_document_outcome'} <= names
