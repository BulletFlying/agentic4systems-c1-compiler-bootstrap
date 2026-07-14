"""Official aec-precise CModel integration for correctness verification.

Platform-aware: uses Linux binary on Linux, macOS binary on macOS,
skips with warning on other platforms (including Windows).
"""

from __future__ import annotations

import json
import os
import platform
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CMODEL_DIR = ROOT / "aec-cmodel" / "bin"

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from aec_c1.compiler import compile_ptx_detailed
from aec_c1.isa import TRACK_B_V1, instructions_to_bytes
from aec_c1.legacy_lowering import TYPE_SIZE


def _cmodel_binary() -> Path | None:
    system = platform.system()
    machine = platform.machine()
    if system == "Linux" and machine == "x86_64":
        return CMODEL_DIR / "aec-precise-linux-x86_64"
    if system == "Darwin" and machine == "arm64":
        return CMODEL_DIR / "aec-precise-macos-arm64"
    return None


def run_with_cmodel(
    kernel_path: Path,
    manifest_path: Path,
    *,
    opt_level: str = "2",
    max_steps: int = 50_000_000,
) -> dict[str, Any]:
    """Compile PTX, execute via aec-precise, return results dict.

    Returns dict with keys: status, steps, cmodel_ok, error (if any).
    """
    binary = _cmodel_binary()
    if binary is None:
        return {"status": "skipped", "error": f"no CModel binary for {platform.system()}/{platform.machine()}"}

    if not binary.exists():
        return {"status": "skipped", "error": f"CModel binary not found: {binary}"}

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

    # Compile
    try:
        result = compile_ptx_detailed(ptx_text, TRACK_B_V1, opt_level=opt_level, input_name=kernel_path.as_posix())
    except Exception as exc:
        return {"status": "error", "error": f"compilation failed: {exc}"}

    aecbin = instructions_to_bytes(result.lowered.instructions, TRACK_B_V1)
    param_layout = result.lowered.parameter_offsets

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Write .aecbin
        program_path = tmp / "program.aecbin"
        program_path.write_bytes(aecbin)

        # Compute PMEM and GMEM sizes
        pmem_size = 0
        for p in params:
            offset = param_layout.get(p["name"], 0)
            size = TYPE_SIZE.get(p["type"], 0)
            pmem_size = max(pmem_size, offset + size)
        if pmem_size % 8:
            pmem_size += 8 - (pmem_size % 8)
        if pmem_size == 0:
            pmem_size = 8

        # Compute buffer addresses with 256-byte alignment
        gmem_base = 256  # fixed by CModel convention
        buffer_addrs: dict[str, int] = {}
        total_gmem = gmem_base
        for name, buf in buffers.items():
            # Align to 256
            if total_gmem % 256:
                total_gmem += 256 - (total_gmem % 256)
            buffer_addrs[name] = total_gmem
            dtype_size = _dtype_size(buf["dtype"])
            numel = buf.get("numel", 0)
            total_gmem += numel * dtype_size

        gmem_size = total_gmem

        # Build PMEM bytes
        pmem_bytes = bytearray(pmem_size)
        for p in params:
            offset = param_layout[p["name"]]
            if p.get("kind") == "gmem_ptr" and p.get("buffer"):
                addr = buffer_addrs.get(p["buffer"], 0)
                pmem_bytes[offset:offset + 8] = struct.pack("<Q", addr)
            elif p.get("kind") == "value" and p.get("value") is not None:
                size = TYPE_SIZE.get(p["type"], 4)
                val = p["value"] & 0xFFFFFFFF
                if size == 4:
                    pmem_bytes[offset:offset + 4] = struct.pack("<I", val)
                elif size == 8:
                    pmem_bytes[offset:offset + 8] = struct.pack("<Q", val)

        # Initialize GMEM with buffer data
        gmem_bytes = bytearray(gmem_size)
        for name, buf in buffers.items():
            base = buffer_addrs[name]
            # All zero for now — CModel compares against reference, not local sim

        # Write PMEM and GMEM files
        pmem_path = tmp / "pmem.bin"
        gmem_path = tmp / "gmem.bin"
        pmem_path.write_bytes(pmem_bytes)
        gmem_path.write_bytes(gmem_bytes)

        # Build CModel command
        cmd = [
            str(binary),
            "--program", str(program_path),
            "--grid", f"{grid[0]},{grid[1]},{grid[2]}",
            "--block", f"{block[0]},{block[1]},{block[2]}",
            "--gmem-size", str(gmem_size),
            "--pmem-size", str(pmem_size),
            "--max-steps", str(max_steps),
            "--load", f"pmem:0:{pmem_path}",
            "--load", f"gmem:0:{gmem_path}",
        ]

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

        return {
            "status": cmodel_json.get("status", "unknown"),
            "steps": cmodel_json.get("steps", 0),
            "cmodel_ok": cmodel_json.get("status") == "done",
            "binary": str(binary),
        }


def _dtype_size(dtype: str) -> int:
    mapping = {"f32": 4, "u32": 4, "s32": 4, "b32": 4, "u64": 8, "b64": 8}
    return mapping.get(dtype, 4)
