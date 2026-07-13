from __future__ import annotations

import ast
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "aec_c1"

CORE_SEMANTIC_PATHS = (
    SRC / "compiler.py",
    SRC / "legacy_lowering.py",
)
CORE_SEMANTIC_DIRS = (
    SRC / "lowering",
    SRC / "backend",
    SRC / "passes",
)
FORBIDDEN_ANALYSIS_IMPORTS = {
    "aec_c1.compiler",
    "aec_c1.isa",
    "aec_c1.legacy_lowering",
}
FORBIDDEN_COMPILER_CLASSES = {"ControlPlan", "Lowerer", "RegisterAllocator"}
FORBIDDEN_COMPILER_TRANSFORMS = {
    "constant_propagation",
    "constant_fold",
    "dce",
    "cse",
    "licm",
    "gemm",
    "scheduler",
    "schedule_instructions",
}
SOURCE_IDENTITY_NAMES = {
    "case_id",
    "file_name",
    "filename",
    "input_hash",
    "kernel_hash",
    "source_hash",
    "test_case",
    "testcase",
}
REGISTER_IDENTITY_NAMES = {
    "reg",
    "reg_id",
    "register",
    "register_id",
    "register_name",
}
HASH_CALL_NAMES = {"blake2b", "blake2s", "hash", "md5", "sha1", "sha256"}
DISPATCH_CALL_NAMES = {"dispatch", "lookup", "select"}
PTX_CASE_RE = re.compile(r"^ptx-0[1-5]$", re.IGNORECASE)
REGISTER_LITERAL_RE = re.compile(r"^%?[rR]\d+$")


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _core_paths() -> tuple[Path, ...]:
    paths = [path for path in CORE_SEMANTIC_PATHS if path.exists()]
    for directory in CORE_SEMANTIC_DIRS:
        if directory.exists():
            paths.extend(sorted(directory.rglob("*.py")))
    return tuple(paths)


def _qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id.lower())
        elif isinstance(child, ast.Attribute):
            names.add(child.attr.lower())
    return names


def _constants(node: ast.AST) -> set[object]:
    return {
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, (str, int))
    }


def _contains_case_literal(node: ast.AST) -> bool:
    return any(isinstance(value, str) and PTX_CASE_RE.fullmatch(value.strip()) for value in _constants(node))


def _contains_register_literal(node: ast.AST) -> bool:
    return any(
        isinstance(value, int)
        or (isinstance(value, str) and REGISTER_LITERAL_RE.fullmatch(value.strip()))
        for value in _constants(node)
    )


def _contains_hash_call(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            callee = _qualified_name(child.func).split(".")[-1].lower()
            if callee in HASH_CALL_NAMES:
                return True
    return False


def _compare_is_identity_dispatch(node: ast.Compare) -> bool:
    if not any(isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn, ast.Is, ast.IsNot)) for op in node.ops):
        return False
    names = _names(node)
    constants = _constants(node)
    if names & SOURCE_IDENTITY_NAMES and constants:
        return True
    if names & REGISTER_IDENTITY_NAMES and _contains_register_literal(node):
        return True
    return _contains_case_literal(node) or _contains_hash_call(node)


def _semantic_trigger_reason(node: ast.AST) -> str | None:
    if isinstance(node, ast.If):
        names = _names(node.test)
        if names & SOURCE_IDENTITY_NAMES:
            return "source identity used as an if-dispatch condition"
        if _contains_case_literal(node.test) or _contains_hash_call(node.test):
            return "case/hash-specific if-dispatch condition"
        return None

    if isinstance(node, ast.Match):
        names = _names(node.subject)
        if names & (SOURCE_IDENTITY_NAMES | REGISTER_IDENTITY_NAMES):
            return "source/register identity used as match dispatch"
        if _contains_case_literal(node):
            return "public PTX case literal used as match dispatch"
        return None

    if isinstance(node, ast.Compare):
        return "identity-specific comparison dispatch" if _compare_is_identity_dispatch(node) else None

    if isinstance(node, ast.Subscript):
        names = _names(node)
        if names & (SOURCE_IDENTITY_NAMES | REGISTER_IDENTITY_NAMES):
            return "source/register identity used as lookup key"
        if _contains_case_literal(node):
            return "public PTX case literal used as lookup key"
        return None

    if isinstance(node, ast.Call):
        callee = _qualified_name(node.func).split(".")[-1].lower()
        if _contains_case_literal(node):
            return "public PTX case literal passed to a call"
        if callee in DISPATCH_CALL_NAMES and _names(node) & (SOURCE_IDENTITY_NAMES | REGISTER_IDENTITY_NAMES):
            return "source/register identity passed to a dispatcher"
        return None

    return None


def _resolve_import_from(path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""

    relative_parent = path.relative_to(SRC).parent.parts
    package = ["aec_c1", *relative_parent]
    levels_up = node.level - 1
    if levels_up:
        package = package[:-levels_up]
    if node.module:
        package.extend(node.module.split("."))
    return ".".join(package)


def _imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(_resolve_import_from(path, node))
    return imports


def test_compiler_facade_does_not_expand_into_lowering_owner() -> None:
    path = SRC / "compiler.py"
    tree = parse(path)
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 140

    class_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    assert not class_names & FORBIDDEN_COMPILER_CLASSES

    function_names = {
        node.name.lower()
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    offenders = {
        name
        for name in function_names
        if any(term in name for term in FORBIDDEN_COMPILER_TRANSFORMS)
    }
    assert not offenders, f"optimization transforms must not be implemented in compiler.py: {sorted(offenders)}"


def test_analysis_has_no_backend_dependencies() -> None:
    for path in sorted((SRC / "analysis").glob("*.py")):
        imports = _imports(path)
        offenders = {
            imported
            for imported in imports
            if any(imported == forbidden or imported.startswith(f"{forbidden}.") for forbidden in FORBIDDEN_ANALYSIS_IMPORTS)
        }
        assert not offenders, f"analysis dependency violation in {path}: {sorted(offenders)}"


def test_core_paths_have_no_case_specific_semantic_dispatch() -> None:
    for path in _core_paths():
        tree = parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.If, ast.Match, ast.Compare, ast.Subscript, ast.Call)):
                continue
            reason = _semantic_trigger_reason(node)
            assert reason is None, f"{reason} in {path}:{getattr(node, 'lineno', '?')}"


def test_pass_classes_expose_standard_run_contract() -> None:
    for path in sorted((SRC / "passes").glob("*.py")):
        tree = parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not node.name.endswith("Pass"):
                continue
            run_methods = [
                method
                for method in node.body
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name == "run"
            ]
            assert len(run_methods) == 1, f"{node.name} must define exactly one run method in {path}"
            positional = [argument.arg for argument in run_methods[0].args.posonlyargs + run_methods[0].args.args]
            assert positional[:3] == ["self", "module", "analyses"], (
                f"{node.name}.run must begin with (self, module, analyses), got {positional} in {path}"
            )
