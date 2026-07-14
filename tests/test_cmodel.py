"""CModel integration tests — require aec-precise binary (Linux x86-64 / macOS ARM64 only).

These tests compile each public T1-T5 kernel, execute via the official
aec-precise CModel, and compare dumped output buffers against reference
computations.  On platforms where the CModel binary cannot run (e.g.
Windows), every test is skipped with a clear reason.

To run on Linux x86-64:

    python -m pytest -q tests/test_cmodel.py -v

"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from tests.cmodel_harness import cmodel_available, cmodel_skip_reason, run_with_cmodel

ROOT = Path(__file__).resolve().parents[1]
TESTCASES = ROOT / "testcases"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CMODEL_CASES = [
    ("T1_basic_lowering", "vector_add", "c", 1e-5, 1e-5),
    ("T2_scalar_optimization", "repeated_expression", "out", 1e-5, 1e-5),
    ("T3_memory_reuse", "repeated_global_load", "out", 1e-5, 1e-5),
    ("T4_register_scheduling", "mixed_load_compute", "out", 1e-5, 1e-5),
    ("T5_scalar_gemm", "scalar_gemm", "C", 1e-4, 1e-4),
]


def _needs_cmodel(func):
    """Decorator: skip test if CModel binary is unavailable."""
    return pytest.mark.skipif(
        not cmodel_available(),
        reason=cmodel_skip_reason() or "CModel binary not available",
    )(func)


# ---------------------------------------------------------------------------
# Smoke test — CModel runs without error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case_name, _kernel, _output_buf, _atol, _rtol",
    _CMODEL_CASES,
    ids=[c[0] for c in _CMODEL_CASES],
)
@_needs_cmodel
def test_cmodel_executes_without_error(case_name, _kernel, _output_buf, _atol, _rtol):
    """CModel must return status='done' for every public testcase."""
    kernel = TESTCASES / case_name / "kernel.ptx"
    manifest = TESTCASES / case_name / "manifest.json"
    result = run_with_cmodel(kernel, manifest, opt_level="2")
    assert result["status"] != "error", f"CModel error: {result.get('error')}"
    assert result.get("cmodel_ok"), f"CModel returned status={result.get('status')}, steps={result.get('steps')}"


# ---------------------------------------------------------------------------
# Output comparison — compare CModel dump against reference
# ---------------------------------------------------------------------------


def _compute_reference(manifest_path: Path) -> list[float]:
    """Compute reference output for the public testcases."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    buffers = manifest.get("buffers", {})
    check = manifest.get("check", {})

    # Reconstruct input buffers from seed / init
    import random as _random
    import struct as _struct

    def _load_buf(name: str) -> list[float]:
        buf = buffers[name]
        numel = buf.get("numel", math.prod(buf.get("shape", [1])))
        seed = buf.get("seed", 0)
        init = buf.get("init", "zero")
        if init == "rand_uniform":
            rng = _random.Random(seed)
            return [rng.uniform(-1.0, 1.0) for _ in range(numel)]
        elif init == "ones":
            return [1.0] * numel
        return [0.0] * numel

    ctype = check.get("type", "elementwise")
    formula = check.get("formula", "")

    if ctype == "matmul":
        A = _load_buf("A")
        B = _load_buf("B")
        A_buf = buffers.get("A", {})
        B_buf = buffers.get("B", {})
        Ashape = A_buf.get("shape", [len(A), len(A)])
        Bshape = B_buf.get("shape", [len(B), len(B)])
        M, K1 = Ashape
        K2, N = Bshape
        C = [0.0] * (M * N)
        for i in range(M):
            for j in range(N):
                acc = 0.0
                for k in range(K1):
                    acc += A[i * K1 + k] * B[k * N + j]
                C[i * N + j] = acc
        return C

    # Elementwise
    if formula == "c[i] = a[i] + b[i]":
        a, b = _load_buf("a"), _load_buf("b")
        return [x + y for x, y in zip(a, b)]
    elif formula == "out[i] = (x[i] + y[i]) * (x[i] + y[i]) + x[i]":
        x, y = _load_buf("x"), _load_buf("y")
        return [(xv + yv) * (xv + yv) + xv for xv, yv in zip(x, y)]
    elif formula == "out[i] = x[i] * y[i] + x[i] * z[i]":
        x, y, z = _load_buf("x"), _load_buf("y"), _load_buf("z")
        return [xv * yv + xv * zv for xv, yv, zv in zip(x, y, z)]
    elif formula == "out[i] = (a[i] + b[i]) * (c[i] - d[i]) + (a[i] * c[i]) * (b[i] + d[i])":
        a, b, c, d = _load_buf("a"), _load_buf("b"), _load_buf("c"), _load_buf("d")
        return [
            (av + bv) * (cv - dv) + (av * cv) * (bv + dv)
            for av, bv, cv, dv in zip(a, b, c, d)
        ]
    raise ValueError(f"unsupported reference formula: {formula}")


@pytest.mark.parametrize(
    "case_name, _kernel, output_buf, atol, rtol",
    _CMODEL_CASES,
    ids=[c[0] for c in _CMODEL_CASES],
)
@_needs_cmodel
def test_cmodel_output_matches_reference(case_name, _kernel, output_buf, atol, rtol):
    """CModel dumped output must match reference within tolerance."""
    kernel = TESTCASES / case_name / "kernel.ptx"
    manifest = TESTCASES / case_name / "manifest.json"
    result = run_with_cmodel(kernel, manifest, opt_level="2")

    if result["status"] == "skipped":
        pytest.skip(result.get("error", "CModel skipped"))
    assert result.get("cmodel_ok"), f"CModel failed: {result.get('error')}"

    outputs = result.get("outputs", {})
    assert output_buf in outputs, (
        f"output buffer '{output_buf}' not in CModel outputs: {list(outputs)}"
    )

    actual = outputs[output_buf]
    reference = _compute_reference(manifest)

    assert len(actual) == len(reference), (
        f"output length mismatch: {len(actual)} vs reference {len(reference)}"
    )

    mismatches = 0
    max_abs = 0.0
    max_rel = 0.0
    for i, (a, r) in enumerate(zip(actual, reference)):
        err = abs(a - r)
        max_abs = max(max_abs, err)
        if err > atol and abs(r) > 1e-30:
            rel = err / abs(r)
            max_rel = max(max_rel, rel)
            if rel > rtol:
                mismatches += 1
        elif err > atol:
            mismatches += 1

    assert mismatches == 0, (
        f"CModel output mismatch: {mismatches}/{len(reference)} elements "
        f"(max_abs={max_abs:.2e}, max_rel={max_rel:.2e})"
    )
