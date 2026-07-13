from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
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
    return (ROOT / "testcases" / name).read_text(encoding="utf-8")


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
        "input_name": "testcases/PTX-02_invariant_poly.ptx",
    }

    first = compile_ptx_detailed(text, **kwargs).report.to_json()
    second = compile_ptx_detailed(text, **kwargs).report.to_json()

    assert first == second
    payload = json.loads(first)
    assert payload["optimization"] == "O2"
    assert payload["pipeline"] == "O2-analysis-foundation"
    assert [record["name"] for record in payload["passes"]] == [
        "validate-program",
        "materialize-cfg",
        "record-uniformity",
    ]
    assert payload["metrics"]["optimization_transforms_applied"] == 0
    assert payload["validation"]["official_golden_model"] == "not_available_not_run"
    assert payload["validation"]["official_cycle_model"] == "not_available_not_run"
    assert first.endswith("\n")


def test_report_contains_model_facing_static_metrics_without_official_cycle_claims() -> None:
    text = _load_ptx("PTX-02_invariant_poly.ptx")
    payload = compile_ptx_detailed(
        text,
        opt_level="3",
        input_name="testcases/PTX-02_invariant_poly.ptx",
    ).report.to_dict()

    assert payload["schema_version"] == 1
    assert payload["optimization"] == "O3"
    assert set(payload["static_metrics"]) == {
        "branch_count",
        "estimated_dependency_depth",
        "estimated_register_pressure",
        "gmem_loads",
        "gmem_stores",
        "instruction_count",
        "instruction_mix",
        "smem_ops",
    }
    assert payload["static_metrics"]["instruction_count"] == payload["metrics"]["machine_instruction_count"]
    assert payload["static_metrics"]["branch_count"] == payload["metrics"]["branch_count"]
    assert payload["static_metrics"]["gmem_loads"] == 1
    assert payload["static_metrics"]["gmem_stores"] == 1
    assert payload["static_metrics"]["instruction_mix"]["BRX"] == 1
    assert payload["static_metrics"]["estimated_dependency_depth"] is None
    assert payload["static_metrics"]["estimated_register_pressure"] is None
    assert payload["cycle_model_metrics"] == {
        "dual_issue_rate": None,
        "memory_transactions": None,
        "spill_count": None,
        "stall_cycles": None,
        "total_cycles": None,
    }


def test_cli_report_is_written_and_repeatable(tmp_path: Path) -> None:
    input_path = ROOT / "testcases" / "PTX-02_invariant_poly.ptx"
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
            "--report",
            str(second_report),
        ]
    )

    assert first_rc == 0
    assert second_rc == 0
    assert first_binary.read_bytes() == second_binary.read_bytes()
    assert first_report.read_bytes() == second_report.read_bytes()
    payload = json.loads(first_report.read_text(encoding="utf-8"))
    assert payload["input"] == input_path.as_posix()
    assert payload["profile"] == TRACK_B_V1.name
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
