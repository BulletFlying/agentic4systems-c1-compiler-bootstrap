from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aec_compiler.compiler import main


OFFICIAL_CASE_ROOT = ROOT / "testcases"
# Git blob SHA-1 of local aec-cmodel/ files (computed via git hash-object so
# .gitattributes LF normalization is applied consistently across platforms).
OFFICIAL_CMODEL_BLOBS = {
    "aec-cmodel/PUBLIC_AEC_PRECISE_COMMANDS.md": "cd54c3bdac738c1ed9232d08b2cd490e20380201",
    "aec-cmodel/USAGE.md": "369f4d5b826699a60d54397b8af1ba6a6229f192",
    "aec-cmodel/bin/aec-precise-linux-x86_64": "4ac048c7818f09294c81314c462e38196e13cec6",
    "aec-cmodel/bin/aec-precise-macos-arm64": "9a5ab318f00e09b5939624403bc882b31ca1f629",
}


def _git_blob_sha1(path: Path) -> str | None:
    """Return the Git blob SHA-1 for *path*, respecting .gitattributes rules.

    Returns None when git is unavailable — callers should skip the check.
    """
    try:
        result = subprocess.run(
            ["git", "hash-object", "--path=" + str(path.relative_to(ROOT).as_posix()), str(path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        return None  # git not installed — cannot compute blob SHA-1
    return result.stdout.strip()


def _official_cases() -> list[Path]:
    return sorted(path for path in OFFICIAL_CASE_ROOT.iterdir() if path.is_dir())


@pytest.mark.parametrize(
    ("relative_path", "expected_blob"),
    sorted(OFFICIAL_CMODEL_BLOBS.items()),
    ids=lambda item: item if isinstance(item, str) else str(item),
)
def test_official_aec_cmodel_release_files_match_current_package(
    relative_path: str, expected_blob: str
) -> None:
    path = ROOT / relative_path
    assert path.exists()
    actual = _git_blob_sha1(path)
    if actual is None:
        pytest.skip("git not available — cannot compute blob SHA-1")
    assert actual == expected_blob


@pytest.mark.parametrize("case_dir", _official_cases(), ids=lambda path: path.name)
def test_reduced_official_public_kernels_compile_with_o2_report(
    case_dir: Path, tmp_path: Path
) -> None:
    kernel = case_dir / "kernel.ptx"
    manifest = case_dir / "manifest.json"
    output = tmp_path / f"{case_dir.name}.aecbin"
    report = tmp_path / f"{case_dir.name}.json"

    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    rc = main(
        [
            str(kernel),
            "-O",
            "2",
            "-o",
            str(output),
            "--report",
            str(report),
        ]
    )

    assert rc == 0
    assert output.exists()
    assert output.stat().st_size > 0
    assert output.stat().st_size % 16 == 0
    assert report.exists()

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["input"] == kernel.as_posix()
    assert payload["optimization"] == "O2"
    assert payload["pipeline"] == "O2-conservative-scalar"
    assert payload["metrics"]["machine_instruction_count"] == output.stat().st_size // 16
    assert payload["validation"]["local_simulator"] == "not_run_by_compiler"
    assert manifest_payload["kernel"]


def test_entry_point_shebang_is_valid() -> None:
    """compiler/aec-cc must have a #! shebang and resolve its own src/ directory."""
    entry = ROOT / "compiler" / "aec-cc"
    first_line = entry.read_text(encoding="utf-8").split("\n")[0]
    assert first_line.startswith("#!/"), f"missing shebang in {entry}"
    assert "python3" in first_line, f"shebang must reference python3: {first_line}"


def test_cli_defaults_to_o2(tmp_path: Path) -> None:
    """Invoking aec-cc without -O should default to O2."""
    kernel = OFFICIAL_CASE_ROOT / "T1_basic_lowering" / "kernel.ptx"
    output = tmp_path / "default_o2.aecbin"
    report = tmp_path / "default_o2.json"
    rc = main([str(kernel), "-o", str(output), "--report", str(report)])
    assert rc == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["optimization"] == "O2"
