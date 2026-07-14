from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
LEGACY_CASES = ROOT / "tests" / "fixtures" / "legacy_ptx"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aec_c1.analysis import AnalysisManager
from aec_c1.compiler import compile_ptx, compile_ptx_detailed, main
from aec_c1.ir import module_from_program
from aec_c1.isa import TRACK_B_V1, instructions_to_bytes
from aec_c1.legacy_lowering import Lowerer
from aec_c1.passes import PassManager, PassResult
from aec_c1.ptx import parse_ptx


def _load_ptx(name: str) -> str:
    return (LEGACY_CASES / name).read_text(encoding="utf-8")


def _load_o0_golden_hashes() -> dict[str, dict[str, str]]:
    path = ROOT / "tests" / "fixtures" / "o0_binary_sha256.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_analysis_manager_caches_and_invalidates() -> None:
    text = _load_ptx("PTX-01_vector_add.ptx")
    module = module_from_program(text, parse_ptx(text))
    calls = 0

    def provider(current_module):
        nonlocal calls
        assert current_module is module
        calls += 1
        return object()

    manager = AnalysisManager(module, {"probe": provider})
    first = manager.get("probe")
    second = manager.get("probe")

    assert first is second
    assert calls == 1
    assert manager.cached_names == ("probe",)

    manager.invalidate(["probe"])
    third = manager.get("probe")

    assert third is not first
    assert calls == 2

    manager.invalidate()
    assert manager.cached_names == ()


def test_pass_manager_preserves_order_and_records_invalidation() -> None:
    text = _load_ptx("PTX-01_vector_add.ptx")
    module = module_from_program(text, parse_ptx(text))
    analysis_calls = 0
    events: list[str] = []

    def provider(_module):
        nonlocal analysis_calls
        analysis_calls += 1
        return analysis_calls

    manager = AnalysisManager(module, {"probe": provider})
    assert manager.get("probe") == 1

    class RecordingPass:
        def __init__(self, name: str, *, invalidates: bool = False) -> None:
            self.name = name
            self.invalidates = invalidates

        def run(self, current_module, analyses):
            assert current_module is module
            events.append(self.name)
            return PassResult(
                changed=self.invalidates,
                details={"position": len(events)},
                invalidated_analyses=frozenset({"probe"}) if self.invalidates else frozenset(),
            )

    pipeline = PassManager(
        "test-pipeline",
        [RecordingPass("first", invalidates=True), RecordingPass("second")],
    )
    records = pipeline.run(module, manager)

    assert events == ["first", "second"]
    assert [record.name for record in records] == ["first", "second"]
    assert records[0].changed is True
    assert records[0].invalidated_analyses == ("probe",)
    assert records[1].details == {"position": 2}
    assert manager.cached_names == ()
    assert manager.get("probe") == 2


def test_compilation_report_json_is_deterministic_and_truthful() -> None:
    text = _load_ptx("PTX-02_invariant_poly.ptx")
    kwargs = {
        "opt_level": "2",
        "input_name": "tests/fixtures/legacy_ptx/PTX-02_invariant_poly.ptx",
    }

    first = compile_ptx_detailed(text, **kwargs).report.to_json()
    second = compile_ptx_detailed(text, **kwargs).report.to_json()

    assert first == second
    payload = json.loads(first)
    assert payload["optimization"] == "O2"
    assert payload["performance_target"] == "aec_slide_constraints"
    assert payload["pipeline"] == "O2-conservative-scalar"
    assert payload["passes"]["dce"] is True
    assert payload["passes"]["cse"] is True
    assert payload["passes"]["licm"] is True
    dead_result_record = payload["pass_records"][1]
    assert dead_result_record["changed"] is True
    assert dead_result_record["details"]["removed_instruction_count"] == 1
    assert dead_result_record["details"]["removed_destinations"] == ["%f15"]
    cse_record = payload["pass_records"][2]
    assert cse_record["changed"] is True
    assert cse_record["details"]["removed_instruction_count"] == 1
    assert cse_record["details"]["replaced_destination_count"] == 1
    assert cse_record["details"]["replacements"] == ["%f6 -> %f5"]
    constant_fold_record = payload["pass_records"][3]
    assert constant_fold_record["changed"] is False
    assert constant_fold_record["details"]["folded_instruction_count"] == 0
    assert constant_fold_record["details"]["transforms_applied"] == 0
    assert payload["metrics"]["optimization_transforms_applied"] >= 2
    assert payload["validation"]["official_golden_model"] == "available_not_integrated_not_run"
    assert payload["validation"]["official_cycle_model"] == "not_available_not_run"
    assert first.endswith("\n")


def test_report_contains_model_facing_static_metrics_without_official_cycle_claims() -> None:
    text = _load_ptx("PTX-02_invariant_poly.ptx")
    payload = compile_ptx_detailed(
        text,
        opt_level="3",
        input_name="tests/fixtures/legacy_ptx/PTX-02_invariant_poly.ptx",
        performance_target="track_c_hint_platform_a",
    ).report.to_dict()

    assert payload["schema_version"] == 1
    assert payload["optimization"] == "O3"
    assert payload["performance_target"] == "track_c_hint_platform_a"
    assert set(payload["static_metrics"]) == {
        "assumed_warp_lanes",
        "branch_count",
        "estimated_arithmetic_intensity",
        "estimated_dependency_depth",
        "estimated_gmem_128b_services_per_warp",
        "estimated_gmem_bytes_per_warp",
        "estimated_lmem_bytes_per_thread",
        "estimated_register_pressure",
        "estimated_smem_bytes_per_cta",
        "gmem_loads",
        "gmem_stores",
        "instruction_count",
        "instruction_mix",
        "memory_service_bytes",
        "memory_space_ops",
        "smem_ops",
    }
    assert payload["static_metrics"]["instruction_count"] == payload["metrics"]["machine_instruction_count"]
    assert payload["static_metrics"]["branch_count"] == payload["metrics"]["branch_count"]
    assert payload["static_metrics"]["assumed_warp_lanes"] == 32
    assert payload["static_metrics"]["memory_service_bytes"] == 128
    assert payload["static_metrics"]["gmem_loads"] == 1
    assert payload["static_metrics"]["gmem_stores"] == 1
    assert payload["static_metrics"]["estimated_gmem_bytes_per_warp"] == 256
    assert payload["static_metrics"]["estimated_gmem_128b_services_per_warp"] == 2
    assert payload["static_metrics"]["memory_space_ops"] == {"gmem": 2, "pmem": 7}
    assert payload["static_metrics"]["instruction_mix"]["BRX"] == 1
    assert payload["static_metrics"]["estimated_arithmetic_intensity"] is None
    assert payload["static_metrics"]["estimated_dependency_depth"] is None
    assert payload["static_metrics"]["estimated_lmem_bytes_per_thread"] is None
    assert payload["static_metrics"]["estimated_register_pressure"] is None
    assert payload["static_metrics"]["estimated_smem_bytes_per_cta"] is None
    assert payload["cycle_model_metrics"] == {
        "dual_issue_rate": None,
        "memory_transactions": None,
        "spill_count": None,
        "stall_cycles": None,
        "total_cycles": None,
    }


def test_compile_rejects_unknown_performance_target() -> None:
    with pytest.raises(ValueError, match="unsupported performance target"):
        compile_ptx_detailed(
            _load_ptx("PTX-01_vector_add.ptx"),
            performance_target="track_c_hint_platform_typo",
        )


def test_cli_report_is_written_and_repeatable(tmp_path: Path) -> None:
    input_path = LEGACY_CASES / "PTX-02_invariant_poly.ptx"
    first_binary = tmp_path / "first.aecbin"
    first_report = tmp_path / "first.json"
    second_binary = tmp_path / "second.aecbin"
    second_report = tmp_path / "second.json"

    first_rc = main(
        [
            str(input_path),
            "-O",
            "2",
            "-o",
            str(first_binary),
            "--performance-target",
            "track_c_hint_platform_b",
            "--report",
            str(first_report),
        ]
    )
    second_rc = main(
        [
            str(input_path),
            "-O",
            "2",
            "-o",
            str(second_binary),
            "--performance-target",
            "track_c_hint_platform_b",
            "--report",
            str(second_report),
        ]
    )

    assert first_rc == 0
    assert second_rc == 0
    assert first_binary.read_bytes() == second_binary.read_bytes()
    # Reports are identical except for the output field (different paths)
    first_payload = json.loads(first_report.read_text(encoding="utf-8"))
    second_payload = json.loads(second_report.read_text(encoding="utf-8"))
    first_payload.pop("output", None)
    second_payload.pop("output", None)
    assert first_payload == second_payload, "reports must be identical (modulo output path)"
    payload = first_payload
    assert payload["input"] == input_path.as_posix()
    assert payload["profile"] == TRACK_B_V1.name
    assert payload["performance_target"] == "track_c_hint_platform_b"
    assert payload["metrics"]["optimization_transforms_applied"] >= 2
    assert "static_metrics" in payload
    assert "cycle_model_metrics" in payload


def test_o0_facade_matches_quarantined_lowering_for_public_control_cases() -> None:
    golden = _load_o0_golden_hashes()
    for name in ("PTX-01_vector_add.ptx", "PTX-02_invariant_poly.ptx"):
        text = _load_ptx(name)
        legacy = Lowerer(parse_ptx(text), profile=TRACK_B_V1).lower()
        current = compile_ptx(text, profile=TRACK_B_V1, opt_level="0")

        legacy_blob = instructions_to_bytes(legacy.instructions, TRACK_B_V1)
        current_blob = instructions_to_bytes(current.instructions, TRACK_B_V1)
        current_hash = sha256(current_blob).hexdigest()

        assert current_blob == legacy_blob, name
        assert current_hash == sha256(legacy_blob).hexdigest(), name
        assert current_hash == golden[name]["sha256"], name
        assert current.parameter_offsets == legacy.parameter_offsets, name
