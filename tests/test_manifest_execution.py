"""Slow end-to-end manifest execution tests (local simulator only).

These tests run the full T1-T5 compile → simulate → compare pipeline and
are marked 'slow'.  Default pytest runs should skip them.

Run: python -m pytest tests/test_manifest_execution.py -v -m slow
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.official_harness import run_case

OFFICIAL_CASE_ROOT = Path(__file__).resolve().parents[1] / "testcases"


def _official_cases() -> list[Path]:
    return sorted(
        path
        for path in OFFICIAL_CASE_ROOT.iterdir()
        if path.is_dir() and (path / "manifest.json").exists()
    )


@pytest.mark.slow
@pytest.mark.parametrize("case_dir", _official_cases(), ids=lambda path: path.name)
def test_official_case_executes_correctly(case_dir: Path) -> None:
    """Compile-and-execute each official public testcase via local simulator."""
    result = run_case(case_dir)
    if not result.passed:
        errors = []
        if result.compilation_error:
            errors.append(f"compilation: {result.compilation_error}")
        if result.simulation_error:
            errors.append(f"simulation: {result.simulation_error}")
        if not result.output_matches:
            errors.append(
                f"output mismatch: {result.num_mismatches}/{result.total_elements} "
                f"(max_abs={result.max_abs_error:.2e}, max_rel={result.max_rel_error:.2e})"
            )
        pytest.fail("; ".join(errors))
    assert result.passed
