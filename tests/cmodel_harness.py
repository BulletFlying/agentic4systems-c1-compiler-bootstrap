"""Official aec-precise CModel integration for correctness verification.

Implements the fixed-address buffer layout and input initialisation rules
documented in aec-cmodel/PUBLIC_AEC_PRECISE_COMMANDS.md.

Platform-aware: uses the Linux x86-64 binary on Linux, macOS ARM64 binary
on macOS, and skips with a clear message on other platforms (including
Windows where neither binary can execute).
"""

from __future__ import annotations

import json
import math
import os
import platform
import random
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CMODEL_DIR = ROOT / "aec-cmodel" / "bin"

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from aec_compiler.compiler import compile_ptx_detailed
from aec_compiler.isa import C1_DEFAULT, instructions_to_bytes
from aec_compiler.legacy_lowering import TYPE_SIZE

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

_CMODEL_BINARY: Path | None = None


def _detect_cmodel_binary() -> Path | None:
    global _CMODEL_BINARY
    if _CMODEL_BINARY is not None:
        return _CMODEL_BINARY

    system = platform.system()
    machine = platform.machine()
    if system == "Windows":
        _CMODEL_BINARY = False
        return None
    if system == "Linux" and (machine in ("x86_64", "AMD64")):
        candidate = CMODEL_DIR / "aec-precise-linux-x86_64"
    elif system == "Darwin" and machine == "arm64":
        candidate = CMODEL_DIR / "aec-precise-macos-arm64"
    else:
        _CMODEL_BINARY = False  # sentinel: unavailable
        return None

    if candidate.exists():
        _CMODEL_BINARY = candidate
    else:
        _CMODEL_BINARY = False
    return _CMODEL_BINARY if _CMODEL_BINARY is not False else None


def cmodel_available() -> bool:
    """Check if aec-precise binary is available AND runnable on this platform."""
    if platform.system() == "Windows":
        return False  # CModel binaries are Linux x86-64 / macOS ARM64 only
    return _detect_cmodel_binary() is not None


def cmodel_skip_reason() -> str | None:
    if _detect_cmodel_binary() is not None:
        return None
    return f"aec-precise not available on {platform.system()}/{platform.machine()}"


# ---------------------------------------------------------------------------
# Buffer initialisation (matches PUBLIC_AEC_PRECISE_COMMANDS.md)
# ---------------------------------------------------------------------------


def _dtype_size(dtype: str) -> int:
    mapping = {"f32": 4, "u32": 4, "s32": 4, "b32": 4, "u64": 8, "b64": 8}
    return mapping.get(dtype, 4)


def _buf_numel(buf: dict) -> int:
    if "numel" in buf:
        return buf["numel"]
    shape = buf.get("shape")
    if shape is not None:
        return math.prod(shape)
    return 0


def _rand_f32_binary(numel: int, seed: int, *, lo: float = -1.0, hi: float = 1.0) -> bytes:
    """Generate numel f32 values in [lo, hi) using the manifest seed."""
    rng = random.Random(seed)
    values = [rng.uniform(lo, hi) for _ in range(numel)]
    return struct.pack("<" + "f" * numel, *values)


def _zero_f32_binary(numel: int) -> bytes:
    return b"\x00" * (numel * 4)


def _pack_u32(value: int) -> bytes:
    return struct.pack("<I", value & 0xFFFFFFFF)


def _pack_u64(value: int) -> bytes:
    return struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF)


# ---------------------------------------------------------------------------
# Fixed-address allocation (PUBLIC_AEC_PRECISE_COMMANDS.md §Fixed address rules)
# ---------------------------------------------------------------------------


@dataclass
class BufferLayout:
    name: str
    address: int
    size_bytes: int
    dtype: str
    init: str
    seed: int | None
    output: bool


def _allocate_buffers(buffers: dict, *, gmem_base: int = 256, alignment: int = 256) -> tuple[list[BufferLayout], int]:
    """Allocate buffer addresses following the official fixed-address rules.

    Returns (layouts, total_gmem_size).
    """
    layouts: list[BufferLayout] = []
    offset = gmem_base
    for name, buf in buffers.items():
        if offset % alignment:
            offset += alignment - (offset % alignment)
        numel = _buf_numel(buf)
        size = numel * _dtype_size(buf["dtype"])
        layouts.append(BufferLayout(
            name=name,
            address=offset,
            size_bytes=size,
            dtype=buf["dtype"],
            init=buf.get("init", "zero"),
            seed=buf.get("seed"),
            output=buf.get("output", False),
        ))
        offset += size
    return layouts, offset


# ---------------------------------------------------------------------------
# PMEM construction
# ---------------------------------------------------------------------------


def _build_pmem(
    params: list[dict],
    param_layout: dict[str, int],
    buffer_addrs: dict[str, int],
    pmem_size: int,
) -> bytes:
    pmem = bytearray(pmem_size)
    for p in params:
        offset = param_layout[p["name"]]
        if p.get("kind") == "gmem_ptr" and p.get("buffer"):
            addr = buffer_addrs.get(p["buffer"], 0)
            pmem[offset:offset + 8] = _pack_u64(addr)
        elif p.get("kind") == "value" and p.get("value") is not None:
            size = TYPE_SIZE.get(p["type"], 4)
            val = p["value"]
            if size == 4:
                pmem[offset:offset + 4] = _pack_u32(val)
            elif size == 8:
                pmem[offset:offset + 8] = _pack_u64(val)
    return bytes(pmem)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def run_with_cmodel(
    kernel_path: Path,
    manifest_path: Path,
    *,
    opt_level: str = "2",
    max_steps: int = 50_000_000,
) -> dict[str, Any]:
    """Compile PTX, execute via aec-precise, return results.

    Returns a dict with:
      status:   'ok' | 'skipped' | 'error'
      steps:    warp-level dynamic step count from CModel (or 0)
      error:    error message (if status != 'ok')
      outputs:  {buffer_name: [float, ...]} of dumped output buffers (if CModel ran)
    """
    binary = _detect_cmodel_binary()
    if binary is None:
        return {"status": "skipped", "error": cmodel_skip_reason()}

    # Load manifest
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    kernel_name = manifest["kernel"]
    grid = manifest["gridDim"]
    block = manifest["blockDim"]
    params = manifest["params"]
    buffers = manifest.get("buffers", {})

    ptx_text = kernel_path.read_text(encoding="utf-8")
    if kernel_name not in ptx_text:
        return {"status": "error", "error": f"kernel '{kernel_name}' not in PTX source"}

    # Compile with C1 scoring profile
    try:
        result = compile_ptx_detailed(
            ptx_text, C1_DEFAULT,
            opt_level=opt_level,
            input_name=kernel_path.as_posix(),
        )
    except Exception as exc:
        return {"status": "error", "error": f"compilation failed: {exc}"}

    aecbin = instructions_to_bytes(result.lowered.instructions, C1_DEFAULT)
    param_layout = result.lowered.parameter_offsets

    # Allocate buffers (fixed-address rules)
    buffer_layouts, total_gmem = _allocate_buffers(buffers)
    buffer_addrs = {bl.name: bl.address for bl in buffer_layouts}

    # Compute PMEM size
    pmem_size = 0
    for p in params:
        offset = param_layout.get(p["name"], 0)
        size = TYPE_SIZE.get(p["type"], 0)
        pmem_size = max(pmem_size, offset + size)
    if pmem_size % 8:
        pmem_size += 8 - (pmem_size % 8)
    if pmem_size == 0:
        pmem_size = 8

    pmem_bytes = _build_pmem(params, param_layout, buffer_addrs, pmem_size)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Write .aecbin
        program_path = tmp / "program.aecbin"
        program_path.write_bytes(aecbin)

        # Write PMEM
        pmem_path = tmp / "pmem.bin"
        pmem_path.write_bytes(pmem_bytes)

        # Write per-buffer GMEM files with correct initialisation
        input_files: list[tuple[int, Path]] = []
        for bl in buffer_layouts:
            if bl.init == "rand_uniform" and bl.seed is not None:
                data = _rand_f32_binary(_buf_numel(buffers[bl.name]), bl.seed)
            elif bl.init == "ones":
                numel = _buf_numel(buffers[bl.name])
                data = struct.pack("<" + "f" * numel, *([1.0] * numel))
            else:
                data = _zero_f32_binary(_buf_numel(buffers[bl.name]))
            buf_path = tmp / f"input_{bl.name}.bin"
            buf_path.write_bytes(data)
            input_files.append((bl.address, buf_path))

        # Build CModel command (matches PUBLIC_AEC_PRECISE_COMMANDS.md format)
        total_gmem_aligned = total_gmem
        if total_gmem_aligned < 65536:
            total_gmem_aligned = 65536

        cmd = [
            str(binary),
            "--program", str(program_path),
            "--grid", f"{grid[0]},{grid[1]},{grid[2]}",
            "--block", f"{block[0]},{block[1]},{block[2]}",
            "--gmem-size", str(total_gmem_aligned),
            "--cmem-size", "65536",
            "--pmem-size", "65536",
            "--smem-size", "65536",
            "--lmem-size", "4096",
            "--max-steps", str(max_steps),
            "--load", f"pmem:0:{pmem_path}",
        ]
        for addr, path in input_files:
            cmd.extend(["--load", f"gmem:{addr}:{path}"])

        # Add --dump for output buffers
        dump_files: dict[str, tuple[int, int, Path]] = {}
        for bl in buffer_layouts:
            if bl.output:
                dump_path = tmp / f"dump_{bl.name}.bin"
                cmd.extend(["--dump", f"{bl.address}:{bl.size_bytes}:{dump_path}"])
                dump_files[bl.name] = (bl.address, bl.size_bytes, dump_path)

        # Run CModel
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "CModel timed out after 180s"}
        except OSError as exc:
            return {"status": "error", "error": f"CModel execution failed: {exc}"}

        if proc.returncode != 0:
            return {"status": "error", "error": f"CModel exit {proc.returncode}: {proc.stderr[:500]}"}

        # Parse JSON output
        try:
            cmodel_json = json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            return {"status": "error", "error": f"CModel invalid JSON: {proc.stdout[:200]}"}

        # Read dumped output buffers
        outputs: dict[str, list[float]] = {}
        for name, (addr, size, path) in dump_files.items():
            if path.exists():
                raw = path.read_bytes()
                count = size // 4
                values = list(struct.unpack("<" + "f" * count, raw))
                outputs[name] = values

        return {
            "status": cmodel_json.get("status", "unknown"),
            "steps": cmodel_json.get("steps", 0),
            "cmodel_ok": cmodel_json.get("status") == "done",
            "binary": str(binary),
            "outputs": outputs,
        }
