"""CModel integration tests — require aec-precise binary (Linux/macOS only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cmodel_harness import run_with_cmodel

ROOT = Path(__file__).resolve().parents[1]
TESTCASES = ROOT / "testcases"


@pytest.mark.parametrize("case_name", ["T1_basic_lowering", "T2_scalar_optimization"])
def test_cmodel_t1_t2_smoke(case_name: str) -> None:
    """Verify CModel executes T1/T2 without error."""
    kernel = TESTCASES / case_name / "kernel.ptx"
    manifest = TESTCASES / case_name / "manifest.json"
    if not kernel.exists():
        pytest.skip(f"{case_name} not found")
    result = run_with_cmodel(kernel, manifest, opt_level="2")
    if result["status"] == "skipped":
        pytest.skip(result.get("error", "CModel not available"))
    assert result["status"] != "error", result.get("error", "unknown CModel error")
    assert result.get("cmodel_ok"), f"CModel returned status={result.get('status')}"
