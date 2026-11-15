"""Check README's single UML class diagram against source declarations."""
import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    classes = {}
    for path in (ROOT / 'src').rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ClassDef):
                continue
            assert node.name not in classes, node.name
            fields, methods = set(), set()
            for member in node.body:
                if isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name):
                    fields.add(member.target.id)
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.add(member.name)
                    if member.name == '__init__':
                        for assignment in ast.walk(member):
                            if isinstance(assignment, ast.Assign):
                                for target in assignment.targets:
                                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
                                        fields.add(target.attr)
            classes[node.name] = {'fields': fields, 'methods': methods, 'node': node}
    diagrams = re.findall(r'```mermaid\s*\n(.*?)```', (ROOT / 'README.md').read_text(), re.S)
    assert len(diagrams) == 1, 'README must contain one overall UML diagram.'
    mermaid = diagrams[0]
    declared = dict(re.findall(r'^\s*class (\w+) \{(.*?)^\s*\}', mermaid, re.M | re.S))
    assert set(declared) == set(classes) and len(classes) == 17
    for name, body in declared.items():
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith(('+', '-')):
                continue
            if '(' in line:
                method = re.match(r'[+-](\w+)\(', line).group(1)
                assert method in classes[name]['methods'], (name, method)
                implementation = next(member for member in classes[name]['node'].body
                                      if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == method)
                decorators = {ast.unparse(item) for item in implementation.decorator_list}
                assert line.endswith('$') == bool(decorators & {'staticmethod', 'classmethod'}), (name, method, 'static notation')
                assert line.endswith('*') == ('abstractmethod' in decorators), (name, method, 'abstract notation')
            else:
                field = line.split()[-1]
                assert field in classes[name]['fields'], (name, field)
    relationships = []
    for line in mermaid.splitlines():
        match = re.match(r'^\s*(\w+)(?:\s+"[^"]+")?\s+(-->|\.\.>|\.\.\|>|<\|--|o--|\*--)\s+(?:"[^"]+"\s+)?(\w+)(?:\s*:\s*(.*))?$', line)
        if not match:
            continue
        first, kind, last, label = match.groups()
        if kind == '<|--':
            first, last, kind = last, first, '--|>'
        assert first in classes and last in classes
        if kind in ('-->', '..>'):
            assert first.endswith('Manager'), (first, kind, last)
        if kind in ('--|>', '..|>'):
            assert last in {ast.unparse(base) for base in classes[first]['node'].bases}
        relationships.append((first, kind, last))
    assert len(relationships) == 20
    assert {first for first, _, last in relationships if last == 'LogicManager'} == {'IOManager', 'AIManager', 'DataManager'}
    assert ('Module', 'o--', 'Assessment') in relationships
    assert ('Document', '*--', 'SourceElement') in relationships
    print('PASS: README UML matches all 17 application classes, displayed members and 20 relationships, including inheritance/interface directions.')


if __name__ == '__main__':
    main()
