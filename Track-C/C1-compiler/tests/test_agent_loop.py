from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aec_c1.agent import decision_log_json, main, run_optimization_loop
from aec_c1.agent.candidates import CandidateConfig
from aec_c1.agent.controller import CorrectnessResult


PTX02 = ROOT / "testcases" / "PTX-02_invariant_poly.ptx"


def test_baseline_candidate_runs_with_static_metrics() -> None:
    decision = run_optimization_loop(PTX02.read_text(encoding="utf-8"), input_name=PTX02.as_posix())

    baseline = decision["baseline"]
    assert baseline["name"] == "baseline"
    assert baseline["passes"] == []
    assert baseline["correct"] is True
    assert baseline["metrics"] == {
        "machine_instruction_count": 32,
        "branch_count": 1,
        "estimated_gmem_128b_services_per_warp": 2,
    }


def test_optimized_candidates_run_and_best_is_selected_deterministically() -> None:
    decision = run_optimization_loop(PTX02.read_text(encoding="utf-8"), input_name=PTX02.as_posix())
    candidates = {candidate["name"]: candidate for candidate in decision["candidates"]}

    assert list(candidates) == ["dre", "dre_cse", "dre_cse_cf"]
    assert candidates["dre"]["correct"] is True
    assert candidates["dre"]["metrics"]["machine_instruction_count"] == 31
    assert candidates["dre_cse"]["correct"] is True
    assert candidates["dre_cse"]["metrics"]["machine_instruction_count"] == 30
    assert candidates["dre_cse_cf"]["correct"] is True
    assert candidates["dre_cse_cf"]["metrics"]["machine_instruction_count"] == 30
    assert decision["selected_candidate"] == "dre_cse_cf"
    assert candidates["dre_cse_cf"]["accepted"] is True
    assert candidates["dre_cse"]["accepted"] is False


def test_correctness_failed_candidate_is_rejected() -> None:
    candidates = (
        CandidateConfig("baseline", ()),
        CandidateConfig("bad", ("conservative-dead-result-elimination",)),
    )

    def gate(_baseline, candidate):
        if candidate.candidate.name == "bad":
            return CorrectnessResult(False, "correctness_failed")
        return CorrectnessResult(True, "correct")

    decision = run_optimization_loop(
        PTX02.read_text(encoding="utf-8"),
        input_name=PTX02.as_posix(),
        candidates=candidates,
        correctness_gate=gate,
    )

    assert decision["selected_candidate"] == "baseline"
    assert decision["candidates"] == [
        {
            "name": "bad",
            "passes": ["conservative-dead-result-elimination"],
            "correct": False,
            "reason": "correctness_failed",
            "metrics": {
                "machine_instruction_count": 31,
                "branch_count": 1,
                "estimated_gmem_128b_services_per_warp": 2,
            },
            "accepted": False,
        }
    ]


def test_decision_log_is_reproducible() -> None:
    text = PTX02.read_text(encoding="utf-8")
    first = decision_log_json(run_optimization_loop(text, input_name=PTX02.as_posix()))
    second = decision_log_json(run_optimization_loop(text, input_name=PTX02.as_posix()))

    assert first == second
    payload = json.loads(first)
    assert payload["schema_version"] == 1
    assert payload["selected_candidate"] == "dre_cse_cf"


def test_agent_cli_writes_decision_log(tmp_path: Path) -> None:
    output = tmp_path / "optimization_decision.json"
    rc = main([str(PTX02), "-o", str(output)])

    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["input"] == PTX02.as_posix()
    assert payload["selected_candidate"] == "dre_cse_cf"


def test_agent_entry_keeps_config_probe_truthful(capsys) -> None:
    rc = main([])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["controller"] == "deterministic-optimization-loop"
    assert payload["candidate_count"] == 4
    assert payload["enabled_services"] == []


def test_agent_code_has_no_external_ai_service_terms() -> None:
    blocked = (
        "op" + "enai",
        "anth" + "ropic",
        "l" + "lm",
        "model " + "inference",
        "api " + "key",
    )
    paths = sorted((SRC / "aec_c1" / "agent").glob("*.py")) + [Path(__file__)]

    for path in paths:
        text = path.read_text(encoding="utf-8").lower()
        assert not any(term in text for term in blocked), path
