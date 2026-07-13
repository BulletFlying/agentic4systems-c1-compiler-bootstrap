"""Correctness-gated deterministic optimization controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any

from ..analysis import build_default_analysis_manager
from ..ir import IRModule, module_from_program
from ..isa import TRACK_B_V1, ISAProfile
from ..legacy_lowering import LoweredProgram, Lowerer
from ..passes import (
    BasicBlockLocalCSEPass,
    ConservativeDeadResultEliminationPass,
    LocalConstantFoldingPass,
    PassManager,
    PassRecord,
)
from ..passes.foundation import MaterializeCFGPass, RecordUniformityPass, ValidateProgramPass
from ..ptx import PTXProgram, parse_ptx
from ..reports import PERFORMANCE_TARGETS, build_metrics
from ..sim import SimulationError, TrackBSimulator, f32_to_bits
from .candidates import DEFAULT_CANDIDATES, CandidateConfig
from .scoring import metric_summary, score_from_metrics


PASS_FACTORIES = {
    "conservative-dead-result-elimination": ConservativeDeadResultEliminationPass,
    "basic-block-local-cse": BasicBlockLocalCSEPass,
    "local-constant-folding": LocalConstantFoldingPass,
}


@dataclass(frozen=True)
class CompiledCandidate:
    candidate: CandidateConfig
    module: IRModule
    lowered: LoweredProgram
    pass_records: tuple[PassRecord, ...]
    metrics: dict[str, Any]


@dataclass(frozen=True)
class CorrectnessResult:
    correct: bool
    reason: str


CorrectnessGate = Callable[[CompiledCandidate, CompiledCandidate], CorrectnessResult]


def run_optimization_loop(
    source_text: str,
    *,
    input_name: str = "<memory>",
    profile: ISAProfile = TRACK_B_V1,
    performance_target: str = "aec_slide_constraints",
    candidates: tuple[CandidateConfig, ...] = DEFAULT_CANDIDATES,
    correctness_gate: CorrectnessGate | None = None,
) -> dict[str, Any]:
    if performance_target not in PERFORMANCE_TARGETS:
        raise ValueError(f"unsupported performance target: {performance_target}")
    if not candidates or candidates[0].passes:
        raise ValueError("first optimization candidate must be the baseline with no scalar passes")

    correctness_gate = correctness_gate or default_correctness_gate
    baseline = _compile_candidate(
        source_text,
        profile=profile,
        candidate=candidates[0],
    )
    baseline_correctness = correctness_gate(baseline, baseline)

    evaluations: list[tuple[CandidateConfig, CorrectnessResult, dict[str, int]]] = []
    selected_name = "baseline"
    selected_score = score_from_metrics(baseline.metrics)
    selected_order = 0 if baseline_correctness.correct else -1

    for order, candidate in enumerate(candidates[1:], start=1):
        compiled = _compile_candidate(
            source_text,
            profile=profile,
            candidate=candidate,
        )
        correctness = correctness_gate(baseline, compiled)
        metrics = metric_summary(compiled.metrics)
        score = score_from_metrics(compiled.metrics)
        if correctness.correct and (
            selected_order < 0
            or score < selected_score
            or (score == selected_score and order > selected_order)
        ):
            selected_name = candidate.name
            selected_score = score
            selected_order = order
        evaluations.append((candidate, correctness, metrics))

    candidate_entries = []
    for candidate, correctness, metrics in evaluations:
        accepted = correctness.correct and candidate.name == selected_name
        reason = correctness.reason if not correctness.correct else ("selected" if accepted else "not_selected")
        candidate_entries.append(
            {
                "name": candidate.name,
                "passes": list(candidate.passes),
                "correct": correctness.correct,
                "reason": reason,
                "metrics": metrics,
                "accepted": accepted,
            }
        )

    baseline_entry = _baseline_entry(
        baseline,
        baseline_correctness,
        accepted=baseline_correctness.correct and selected_name == "baseline",
    )
    return {
        "schema_version": 1,
        "input": input_name,
        "performance_target": performance_target,
        "baseline": baseline_entry,
        "candidates": candidate_entries,
        "selected_candidate": selected_name,
    }


def choose_config(request: dict[str, Any] | None = None) -> dict[str, Any]:
    request = request or {}
    return {
        "compiler": "aec-cc",
        "profile": request.get("profile", TRACK_B_V1.name),
        "controller": "deterministic-optimization-loop",
        "candidate_count": len(DEFAULT_CANDIDATES),
        "enabled_services": [],
        "status": "offline-deterministic-controller",
    }


def _compile_candidate(
    source_text: str,
    *,
    profile: ISAProfile,
    candidate: CandidateConfig,
) -> CompiledCandidate:
    program = parse_ptx(source_text)
    module = module_from_program(source_text, program)
    analyses = build_default_analysis_manager(module)
    pipeline = PassManager(
        f"agent-{candidate.name}",
        [
            ValidateProgramPass(),
            *[_pass_from_name(name) for name in candidate.passes],
            MaterializeCFGPass(),
            RecordUniformityPass(),
        ],
    )
    pass_records = pipeline.run(module, analyses)
    lowered = Lowerer(module.function.program, profile=profile).lower()
    metrics = build_metrics(module, lowered, pass_records)
    return CompiledCandidate(
        candidate=candidate,
        module=module,
        lowered=lowered,
        pass_records=pass_records,
        metrics=metrics,
    )


def _pass_from_name(name: str):
    try:
        return PASS_FACTORIES[name]()
    except KeyError as exc:
        raise ValueError(f"unsupported optimization pass candidate: {name}") from exc


def _baseline_entry(
    compiled: CompiledCandidate,
    correctness: CorrectnessResult,
    *,
    accepted: bool,
) -> dict[str, Any]:
    return {
        "name": compiled.candidate.name,
        "passes": [],
        "correct": correctness.correct,
        "reason": correctness.reason,
        "metrics": metric_summary(compiled.metrics),
        "accepted": accepted,
    }


def default_correctness_gate(
    baseline: CompiledCandidate,
    candidate: CompiledCandidate,
) -> CorrectnessResult:
    try:
        cases = _simulation_cases(baseline.module.function.program, baseline.lowered)
        if not cases:
            return CorrectnessResult(False, "correctness_unsupported_signature")
        for case in cases:
            baseline_result = _simulate(baseline.lowered, case)
            candidate_result = _simulate(candidate.lowered, case)
            if candidate_result.gmem != baseline_result.gmem:
                return CorrectnessResult(False, "correctness_gmem_mismatch")
            if candidate_result.accesses != baseline_result.accesses:
                return CorrectnessResult(False, "correctness_access_mismatch")
            if candidate_result.non_uniform_branch_failures or baseline_result.non_uniform_branch_failures:
                return CorrectnessResult(False, "correctness_branch_failure")
    except (KeyError, SimulationError, ValueError) as exc:
        return CorrectnessResult(False, f"correctness_failed:{exc}")
    return CorrectnessResult(True, "correct")


@dataclass(frozen=True)
class SimulationCase:
    pmem: bytearray
    gmem: bytearray
    block_dim: int
    grid_dim: int


def _simulation_cases(program: PTXProgram, lowered: LoweredProgram) -> tuple[SimulationCase, ...]:
    names = {parameter.name for parameter in program.parameters}
    if {"param_x", "param_y", "param_n", "param_a", "param_b"} <= names:
        return tuple(_invariant_poly_case(lowered, n) for n in (0, 17, 33))
    if {"param_a", "param_b", "param_c", "param_n"} <= names:
        return tuple(_vector_add_case(lowered, n) for n in (0, 17, 33))
    return ()


def _simulate(lowered: LoweredProgram, case: SimulationCase):
    return TrackBSimulator(
        lowered.instructions,
        bytearray(case.pmem),
        bytearray(case.gmem),
        block_dim=case.block_dim,
        grid_dim=case.grid_dim,
    ).run()


def _invariant_poly_case(lowered: LoweredProgram, n: int) -> SimulationCase:
    block_dim = 64
    base_x = 0
    base_y = block_dim * 4
    gmem = bytearray(block_dim * 8)
    for index in range(block_dim):
        _write_u32(gmem, base_x + index * 4, f32_to_bits(index * 0.25 - 2.0))
        _write_u32(gmem, base_y + index * 4, 0xDEADBEEF)

    pmem = bytearray(28)
    _write_u64(pmem, lowered.parameter_offsets["param_x"], base_x)
    _write_u64(pmem, lowered.parameter_offsets["param_y"], base_y)
    _write_u32(pmem, lowered.parameter_offsets["param_n"], n)
    _write_u32(pmem, lowered.parameter_offsets["param_a"], f32_to_bits(1.25))
    _write_u32(pmem, lowered.parameter_offsets["param_b"], f32_to_bits(-0.75))
    return SimulationCase(pmem=pmem, gmem=gmem, block_dim=block_dim, grid_dim=1)


def _vector_add_case(lowered: LoweredProgram, n: int) -> SimulationCase:
    block_dim = 64
    base_a = 0
    base_b = block_dim * 4
    base_c = block_dim * 8
    gmem = bytearray(block_dim * 12)
    for index in range(block_dim):
        _write_u32(gmem, base_a + index * 4, f32_to_bits(index * 0.5))
        _write_u32(gmem, base_b + index * 4, f32_to_bits(10.0 - index * 0.25))
        _write_u32(gmem, base_c + index * 4, 0xDEADBEEF)

    pmem = bytearray(32)
    _write_u64(pmem, lowered.parameter_offsets["param_a"], base_a)
    _write_u64(pmem, lowered.parameter_offsets["param_b"], base_b)
    _write_u64(pmem, lowered.parameter_offsets["param_c"], base_c)
    _write_u32(pmem, lowered.parameter_offsets["param_n"], n)
    return SimulationCase(pmem=pmem, gmem=gmem, block_dim=block_dim, grid_dim=1)


def _write_u32(memory: bytearray, offset: int, value: int) -> None:
    memory[offset : offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")


def _write_u64(memory: bytearray, offset: int, value: int) -> None:
    memory[offset : offset + 8] = (value & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
