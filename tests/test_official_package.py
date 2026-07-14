from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aec_c1.compiler import main


OFFICIAL_CASE_ROOT = ROOT / "testcases"
# Git blob SHA-1 of local aec-cmodel/ files (LF-normalized text, raw binary).
# These verify local repo integrity, not byte-identical match to official upstream
# (official markdown files may differ in line endings due to .gitattributes LF enforcement).
OFFICIAL_CMODEL_BLOBS = {
    "aec-cmodel/PUBLIC_AEC_PRECISE_COMMANDS.md": "cd54c3bdac738c1ed9232d08b2cd490e20380201",
    "aec-cmodel/USAGE.md": "369f4d5b826699a60d54397b8af1ba6a6229f192",
    "aec-cmodel/bin/aec-precise-linux-x86_64": "4ac048c7818f09294c81314c462e38196e13cec6",
    "aec-cmodel/bin/aec-precise-macos-arm64": "9a5ab318f00e09b5939624403bc882b31ca1f629",
}


def _git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


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
    assert _git_blob_sha1(path) == expected_blob


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
