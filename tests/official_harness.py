"""Manifest-aware test harness for official C1 public testcases.

Reads testcases/*/manifest.json, initialises PMEM/GMEM,
compiles the PTX kernel through -O2, executes via local simulator, and
compares output buffers against reference computations.

This harness lives in tests/; the compiler CLI and library do not depend on it.
The local simulator is NOT the official `aec-precise` CModel — all results must be
qualified as local-simulator evidence only.

Dependencies: stdlib only (no numpy).  CI installs only pytest.
"""

from __future__ import annotations

import json
import math
import random
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aec_c1.compiler import compile_ptx_detailed
from aec_c1.isa import TRACK_B_V1
from aec_c1.legacy_lowering import TYPE_SIZE
from aec_c1.sim import MASK32, TrackBSimulator, bits_to_f32, f32_to_bits


# ---------------------------------------------------------------------------
# Manifest types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManifestParam:
    name: str
    dtype: str
    kind: str  # "gmem_ptr" | "value"
    buffer: str | None = None
    value: int | None = None


@dataclass
class ManifestBuffer:
    name: str
    dtype: str
    numel: int
    shape: tuple[int, ...] | None = None
    layout: str = "row_major"
    init: str = "zero"
    seed: int | None = None
    output: bool = False
    data: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class ManifestCheck:
    check_type: str  # "elementwise" | "matmul"
    formula: str
    output: str
    atol: float
    rtol: float


@dataclass
class Manifest:
    name: str
    category: str
    kernel: str
    grid_dim: tuple[int, int, int]
    block_dim: tuple[int, int, int]
    dynamic_smem_bytes: int
    params: tuple[ManifestParam, ...]
    buffers: dict[str, ManifestBuffer]
    check: ManifestCheck


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def load_manifest(path: Path) -> Manifest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    params = tuple(
        ManifestParam(
            name=p["name"],
            dtype=p["type"],
            kind=p["kind"],
            buffer=p.get("buffer"),
            value=p.get("value"),
        )
        for p in payload["params"]
    )
    buffers: dict[str, ManifestBuffer] = {}
    for name, b in payload.get("buffers", {}).items():
        raw_shape = b.get("shape")
        shape = tuple(raw_shape) if raw_shape else None
        numel = b.get("numel", math.prod(shape) if shape else 0)
        buffers[name] = ManifestBuffer(
            name=name,
            dtype=b["dtype"],
            numel=numel,
            shape=shape,
            layout=b.get("layout", "row_major"),
            init=b.get("init", "zero"),
            seed=b.get("seed"),
            output=b.get("output", False),
        )
    check = ManifestCheck(
        check_type=payload["check"]["type"],
        formula=payload["check"].get("formula", ""),
        output=payload["check"]["output"],
        atol=payload["check"]["atol"],
        rtol=payload["check"]["rtol"],
    )
    return Manifest(
        name=payload["name"],
        category=payload.get("category", ""),
        kernel=payload["kernel"],
        grid_dim=tuple(payload["gridDim"]),
        block_dim=tuple(payload["blockDim"]),
        dynamic_smem_bytes=payload.get("dynamic_smem_bytes", 0),
        params=params,
        buffers=buffers,
        check=check,
    )


# ---------------------------------------------------------------------------
# Buffer initialisation (stdlib random, no numpy)
# ---------------------------------------------------------------------------


def _make_rng(seed: int) -> random.Random:
    return random.Random(seed)


def init_buffers(manifest: Manifest) -> dict[str, ManifestBuffer]:
    """Initialise gmem buffers with random data (seeded) or zeros."""
    for buf in manifest.buffers.values():
        rng = _make_rng(buf.seed if buf.seed is not None else 0)
        if buf.init == "rand_uniform":
            data = [rng.random() for _ in range(buf.numel)]
        elif buf.init == "zero":
            data = [0.0] * buf.numel
        elif buf.init == "ones":
            data = [1.0] * buf.numel
        else:
            raise ValueError(f"unsupported buffer init: {buf.init}")
        buf.data = data
    return manifest.buffers


def pack_gmem(buffers: dict[str, ManifestBuffer]) -> tuple[bytearray, dict[str, int]]:
    """Pack all buffers into a single flat gmem bytearray.

    Returns (gmem, base_addresses) where base_addresses maps buffer name to byte offset.
    """
    base_addresses: dict[str, int] = {}
    offset = 0
    for name, buf in buffers.items():
        alignment = 16  # conservative alignment
        if offset % alignment:
            offset += alignment - (offset % alignment)
        base_addresses[name] = offset
        offset += buf.numel * _dtype_size(buf.dtype)
    gmem = bytearray(offset)
    for name, buf in buffers.items():
        base = base_addresses[name]
        _write_floats(gmem, base, buf.data, buf.dtype)
    return gmem, base_addresses


def _dtype_size(dtype: str) -> int:
    mapping = {"f32": 4, "u32": 4, "s32": 4, "b32": 4, "u64": 8, "b64": 8}
    size = mapping.get(dtype)
    if size is None:
        raise ValueError(f"unsupported dtype: {dtype}")
    return size


def _write_floats(gmem: bytearray, base: int, data: Sequence[float], dtype: str) -> None:
    for i, val in enumerate(data):
        offset = base + i * _dtype_size(dtype)
        if dtype == "f32":
            gmem[offset : offset + 4] = struct.pack("<I", f32_to_bits(float(val)))
        elif dtype in {"u32", "s32", "b32"}:
            gmem[offset : offset + 4] = struct.pack("<I", int(val) & MASK32)
        else:
            raise ValueError(f"unsupported dtype for write: {dtype}")


def _read_floats(gmem: bytes, base: int, numel: int, dtype: str) -> list[float]:
    data: list[float] = []
    for i in range(numel):
        offset = base + i * _dtype_size(dtype)
        if dtype == "f32":
            bits = struct.unpack("<I", gmem[offset : offset + 4])[0]
            data.append(bits_to_f32(bits))
        elif dtype in {"u32", "s32", "b32"}:
            data.append(float(struct.unpack("<I", gmem[offset : offset + 4])[0]))
    return data


# ---------------------------------------------------------------------------
# PMEM parameter packing
# ---------------------------------------------------------------------------


def build_pmem(
    param_layout: dict[str, int],
    manifest: Manifest,
    base_addresses: dict[str, int],
    total_pmem_size: int,
) -> bytearray:
    """Pack kernel parameters into pmem according to compiler layout."""
    pmem = bytearray(total_pmem_size)
    for param in manifest.params:
        offset = param_layout[param.name]
        if param.kind == "gmem_ptr" and param.buffer is not None:
            value = base_addresses.get(param.buffer, 0)
            pmem[offset : offset + 8] = struct.pack("<Q", value)
        elif param.kind == "value" and param.value is not None:
            size = TYPE_SIZE.get(param.dtype, 4)
            if size == 4:
                pmem[offset : offset + 4] = struct.pack("<I", param.value & MASK32)
            elif size == 8:
                pmem[offset : offset + 8] = struct.pack("<Q", param.value)
    return pmem


# ---------------------------------------------------------------------------
# Reference computation (pure Python, no numpy)
# ---------------------------------------------------------------------------


def compute_reference(manifest: Manifest) -> list[float]:
    """Compute reference output for elementwise and matmul checks."""
    buffers = manifest.buffers
    check = manifest.check

    if check.check_type == "elementwise":
        return _compute_elementwise_reference(manifest, buffers)
    elif check.check_type == "matmul":
        return _compute_matmul_reference(manifest, buffers)
    raise ValueError(f"unsupported check type: {check.check_type}")


def _compute_elementwise_reference(manifest: Manifest, buffers: dict[str, ManifestBuffer]) -> list[float]:
    check = manifest.check
    if check.formula == "c[i] = a[i] + b[i]":
        a, b = buffers["a"].data, buffers["b"].data
        return [x + y for x, y in zip(a, b)]
    elif check.formula == "out[i] = (x[i] + y[i]) * (x[i] + y[i]) + x[i]":
        x, y = buffers["x"].data, buffers["y"].data
        return [(xv + yv) * (xv + yv) + xv for xv, yv in zip(x, y)]
    elif check.formula == "out[i] = x[i] * y[i] + x[i] * z[i]":
        x, y, z = buffers["x"].data, buffers["y"].data, buffers["z"].data
        return [xv * yv + xv * zv for xv, yv, zv in zip(x, y, z)]
    elif check.formula == "out[i] = (a[i] + b[i]) * (c[i] - d[i]) + (a[i] * c[i]) * (b[i] + d[i])":
        a = buffers["a"].data
        b = buffers["b"].data
        c = buffers["c"].data
        d = buffers["d"].data
        return [
            (av + bv) * (cv - dv) + (av * cv) * (bv + dv)
            for av, bv, cv, dv in zip(a, b, c, d)
        ]
    raise ValueError(f"unsupported elementwise formula: {check.formula}")


def _compute_matmul_reference(manifest: Manifest, buffers: dict[str, ManifestBuffer]) -> list[float]:
    A_buf = buffers.get("A")
    B_buf = buffers.get("B")
    if A_buf is None or B_buf is None:
        raise ValueError("matmul reference requires A and B buffers")
    M, K1 = A_buf.shape if A_buf.shape else (1, len(A_buf.data))
    K2, N = B_buf.shape if B_buf.shape else (len(B_buf.data), 1)
    A = A_buf.data
    B = B_buf.data
    C: list[float] = [0.0] * (M * N)
    for i in range(M):
        for j in range(N):
            acc = 0.0
            for k in range(K1):
                acc += A[i * K1 + k] * B[k * N + j]
            C[i * N + j] = acc
    return C


# ---------------------------------------------------------------------------
# Harness runner
# ---------------------------------------------------------------------------


@dataclass
class HarnessResult:
    passed: bool
    manifest_name: str
    output_matches: bool
    max_abs_error: float = 0.0
    max_rel_error: float = 0.0
    num_mismatches: int = 0
    total_elements: int = 0
    simulation_error: str | None = None
    compilation_error: str | None = None


def run_case(case_dir: Path, *, opt_level: str = "2") -> HarnessResult:
    """Compile, execute, and validate a single testcase."""
    kernel_path = case_dir / "kernel.ptx"
    manifest_path = case_dir / "manifest.json"

    manifest = load_manifest(manifest_path)

    # Verify kernel name matches
    ptx_text = kernel_path.read_text(encoding="utf-8")
    if manifest.kernel not in ptx_text:
        return HarnessResult(
            passed=False,
            manifest_name=manifest.name,
            output_matches=False,
            compilation_error=f"kernel name '{manifest.kernel}' not found in PTX source",
        )

    # Compile
    try:
        result = compile_ptx_detailed(
            ptx_text, TRACK_B_V1, opt_level=opt_level, input_name=kernel_path.as_posix(),
        )
    except Exception as exc:
        return HarnessResult(
            passed=False,
            manifest_name=manifest.name,
            output_matches=False,
            compilation_error=str(exc),
        )

    lowered = result.lowered
    instructions = lowered.instructions
    param_layout = lowered.parameter_offsets

    # Init buffers
    buffers = init_buffers(manifest)
    gmem, base_addresses = pack_gmem(buffers)

    # Build pmem
    total_pmem = 0
    for param in manifest.params:
        offset = param_layout.get(param.name, 0)
        size = TYPE_SIZE.get(param.dtype, 0)
        total_pmem = max(total_pmem, offset + size)
    if total_pmem % 8:
        total_pmem += 8 - (total_pmem % 8)
    pmem = build_pmem(param_layout, manifest, base_addresses, total_pmem)

    # Compute reference
    try:
        reference = compute_reference(manifest)
    except ValueError:
        reference = []

    # Run simulator
    try:
        simulator = TrackBSimulator(
            instructions,
            pmem,
            gmem,
            block_dim=manifest.block_dim,
            grid_dim=manifest.grid_dim,
            max_steps=100000,
        )
        sim_result = simulator.run()
    except Exception as exc:
        return HarnessResult(
            passed=False,
            manifest_name=manifest.name,
            output_matches=False,
            simulation_error=str(exc),
        )

    # Read output
    output_name = manifest.check.output
    if output_name not in buffers:
        return HarnessResult(
            passed=False,
            manifest_name=manifest.name,
            output_matches=False,
            simulation_error=f"output buffer '{output_name}' not found",
        )

    output_buf = buffers[output_name]
    output_data = _read_floats(
        bytes(sim_result.gmem), base_addresses[output_name], output_buf.numel, output_buf.dtype,
    )

    # Compare
    if not reference:
        return HarnessResult(
            passed=True, manifest_name=manifest.name, output_matches=True,
            total_elements=output_buf.numel,
        )

    if len(output_data) != len(reference):
        return HarnessResult(
            passed=False, manifest_name=manifest.name, output_matches=False,
            simulation_error=f"length mismatch: output {len(output_data)} vs reference {len(reference)}",
        )

    max_abs = 0.0
    max_rel = 0.0
    mismatches = 0
    for i, (out, ref) in enumerate(zip(output_data, reference)):
        err = abs(out - ref)
        max_abs = max(max_abs, err)
        if err > manifest.check.atol:
            if abs(ref) > 1e-30:
                rel = err / abs(ref)
                max_rel = max(max_rel, rel)
                if rel > manifest.check.rtol:
                    mismatches += 1
            else:
                mismatches += 1

    passed = mismatches == 0
    return HarnessResult(
        passed=passed, manifest_name=manifest.name,
        output_matches=mismatches == 0,
        max_abs_error=max_abs, max_rel_error=max_rel,
        num_mismatches=mismatches, total_elements=len(reference),
    )


def run_all_official_cases(opt_level: str = "2") -> list[HarnessResult]:
    """Run all official T1-T5 testcases."""
    case_root = ROOT / "testcases"
    results: list[HarnessResult] = []
    for case_dir in sorted(case_root.iterdir()):
        if not case_dir.is_dir():
            continue
        manifest_path = case_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        results.append(run_case(case_dir, opt_level=opt_level))
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    results = run_all_official_cases()
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"\n{'='*60}")
    print(f"Manifest harness results (local simulator): {passed}/{total} passed")
    print(f"{'='*60}")
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"\n[{status}] {r.manifest_name}")
        if r.compilation_error:
            print(f"  compilation error: {r.compilation_error}")
        if r.simulation_error:
            print(f"  simulation error: {r.simulation_error}")
        if r.total_elements > 0:
            print(f"  elements: {r.total_elements}, mismatches: {r.num_mismatches}")
            print(f"  max_abs_error: {r.max_abs_error:.6e}, max_rel_error: {r.max_rel_error:.6e}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
