from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "aec_c1"

FORBIDDEN_CORE_TERMS = {
    "PTX-01",
    "PTX-02",
    "PTX-03",
    "PTX-04",
    "PTX-05",
    "testcase",
    "filename",
    "constant_propagation",
    "dce",
    "cse",
    "licm",
    "scheduler",
}


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_compiler_facade_does_not_expand_into_lowering_owner() -> None:
    path = SRC / "compiler.py"
    tree = parse(path)
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 140
    forbidden_classes = {"Lowerer", "RegisterAllocator", "ControlPlan"}
    assert not ({node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)} & forbidden_classes)


def test_analysis_has_no_backend_dependencies() -> None:
    forbidden = {"aec_c1.isa", "aec_c1.compiler", "aec_c1.legacy_lowering"}
    for path in (SRC / "analysis").glob("*.py"):
        tree = parse(path)
        imports = ast.walk(tree)
        names = []
        for node in imports:
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.append(node.module or "")
        assert not forbidden.intersection(names), path


def test_core_sources_have_no_case_specific_dispatch_terms() -> None:
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "tests" in path.parts:
            continue
        for term in FORBIDDEN_CORE_TERMS:
            assert term not in text, f"{term} found in {path}"


def test_pass_classes_expose_run_method() -> None:
    for path in (SRC / "passes").glob("*.py"):
        tree = parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Pass"):
                methods = {m.name for m in node.body if isinstance(m, ast.FunctionDef)}
                assert "run" in methods, path
