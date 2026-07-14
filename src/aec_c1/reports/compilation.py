"""Deterministic machine-readable compilation reports."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from ..ir import IRModule
from ..legacy_lowering import LoweredProgram
from ..passes import PassRecord


CYCLE_MODEL_METRIC_KEYS = (
    "total_cycles",
    "spill_count",
    "dual_issue_rate",
    "memory_transactions",
    "stall_cycles",
)

PERFORMANCE_TARGETS = (
    "aec_slide_constraints",
    "track_c_hint_platform_a",
    "track_c_hint_platform_b",
)

WARP_LANES = 32
MEMORY_SERVICE_BYTES = 128

_DATA_TYPE_BYTES = {
    "u8": 1,
    "s8": 1,
    "u16": 2,
    "s16": 2,
    "f16": 2,
    "bf16": 2,
    "b32": 4,
    "u32": 4,
    "s32": 4,
    "f32": 4,
    "b64": 8,
    "u64": 8,
    "s64": 8,
    "f64": 8,
    "none": 0,
}


@dataclass(frozen=True)
class CompilationReport:
    input: str
    optimization: str
    profile: str
    pipeline: str
    passes: tuple[PassRecord, ...]
    metrics: dict[str, Any]
    output: str = ""
    performance_target: str = "aec_slide_constraints"

    def to_dict(self) -> dict[str, Any]:
        metrics = dict(self.metrics)
        static_metrics = metrics.pop("static_metrics", {})
        cycle_model_metrics = metrics.pop("cycle_model_metrics", _null_cycle_model_metrics())

        # spec §12 compliant fields — always include scheduler (even if not implemented)
        spec_passes: dict[str, object] = {
            "scheduler": "none",
        }
        for record in self.passes:
            name = record.name
            if name == "global-dead-code-elimination":
                spec_passes["dce"] = True
            elif name == "conservative-dead-result-elimination":
                spec_passes.setdefault("dce", True)
            elif name == "basic-block-local-cse":
                spec_passes["cse"] = True
            elif name == "local-constant-folding":
                spec_passes.setdefault("constant_folding", True)
            elif name == "global-constant-propagation":
                spec_passes["constant_folding"] = True
            elif name == "loop-invariant-code-motion":
                spec_passes["licm"] = True
            elif name == "repeated-global-load-reuse":
                spec_passes["load_reuse"] = True
            elif name == "load-hoisting":
                spec_passes["load_hoisting"] = True
            elif name == "loop-unrolling":
                spec_passes["loop_unrolling"] = True
            elif name == "block-simplification":
                spec_passes["block_merge"] = True

        return {
            # spec §12 top-level fields
            "status": "ok",
            "input": self.input,
            "output": self.output,
            "optimization": f"O{self.optimization}",
            "opt_level": f"O{self.optimization}",
            "num_ptx_instructions": metrics.get("source_instruction_count", 0),
            "num_aec_instructions": metrics.get("machine_instruction_count", 0),
            "num_basic_blocks": metrics.get("basic_block_count", 0),
            "num_virtual_registers": metrics.get("virtual_register_count", metrics.get("highest_encoded_register_index", 0)),
            "num_physical_registers": metrics.get("physical_register_count", 0),
            "num_predicates": metrics.get("predicate_count", 0),
            "spills": {
                "loads": metrics.get("spill_loads", 0),
                "stores": metrics.get("spill_stores", 0),
            },
            "passes": _sort_mapping(spec_passes),
            "warnings": _report_notes(self.passes),
            # extended diagnostic fields
            "schema_version": 1,
            "profile": self.profile,
            "pipeline": self.pipeline,
            "performance_target": self.performance_target,
            "pass_records": [record.to_dict() for record in self.passes],
            "metrics": dict(sorted(metrics.items())),
            "static_metrics": _sort_mapping(static_metrics),
            "cycle_model_metrics": _sort_mapping(cycle_model_metrics),
            "validation": {
                "local_simulator": "not_run_by_compiler",
                "official_golden_model": "available_not_integrated_not_run",
                "official_cycle_model": "not_available_not_run",
            },
            "notes": _report_notes(self.passes),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")


def build_metrics(
    module: IRModule,
    lowered: LoweredProgram,
    pass_records: tuple[PassRecord, ...] = (),
) -> dict[str, Any]:
    instructions = lowered.instructions
    source_instruction_count = sum(
        1 for item in module.function.program.items if not isinstance(item, str)
    )
    branch_count = sum(inst.opcode in {"BR", "BRX", "CALL", "RET"} for inst in instructions)
    memory_instruction_count = sum(inst.opcode in {"LD", "ST", "ATOM"} for inst in instructions)
    registers = [
        value
        for inst in instructions
        for value in (inst.dest, inst.src1, inst.src2, inst.src3)
        if isinstance(value, int) and 0 <= value <= 255
    ]
    static_metrics = _build_static_metrics(lowered)
    transforms_applied = sum(
        int(record.details.get("transforms_applied", 0)) for record in pass_records
    )
    # Count PTX virtual registers from source program (all unique %r / %rd / %f / %p operands)
    virtual_regs: set[str] = set()
    for item in module.function.program.items:
        if isinstance(item, str):
            continue
        for op in item.operands:
            op_s = op.strip().lstrip("[")
            if op_s.startswith("%") and not op_s.startswith("%p"):
                virtual_regs.add(op_s.split("[")[0].strip())
    # Count physical (AEC) registers from encoded instructions
    physical_regs: set[int] = set()
    preds: set[int] = set()
    for inst in instructions:
        for val in (inst.dest, inst.src1, inst.src2, inst.src3):
            if isinstance(val, int) and 0 <= val <= 255:
                physical_regs.add(val)
        if inst.predicate is not None:
            preds.add(inst.predicate)
    return {
        "basic_block_count": len(module.function.blocks),
        "branch_count": branch_count,
        "code_size_bytes": len(instructions) * 16,
        "highest_encoded_register_index": max(registers, default=0),
        "machine_instruction_count": len(instructions),
        "memory_instruction_count": memory_instruction_count,
        "optimization_transforms_applied": transforms_applied,
        "source_instruction_count": source_instruction_count,
        "virtual_register_count": len(virtual_regs),
        "physical_register_count": len(physical_regs),
        "predicate_count": len(preds),
        "spill_loads": 0,
        "spill_stores": 0,
        "static_metrics": static_metrics,
        "cycle_model_metrics": _null_cycle_model_metrics(),
    }


def _report_notes(pass_records: tuple[PassRecord, ...]) -> list[str]:
    pass_names = {record.name for record in pass_records}
    notes: list[str] = []
    scalar_notes: list[str] = []
    missing: list[str] = []

    if "conservative-dead-result-elimination" in pass_names:
        scalar_notes.append(
            "Conservative dead-result elimination (read-set based) is enabled."
        )
    if "global-dead-code-elimination" in pass_names:
        scalar_notes.append(
            "Worklist-based global dead-code elimination is enabled. "
            "It preserves memory, control, predicate, carry, and predicated instructions."
        )
    if "basic-block-local-cse" in pass_names:
        scalar_notes.append(
            "Basic-block-local CSE is enabled."
        )
    if "local-constant-folding" in pass_names:
        scalar_notes.append(
            "Basic-block-local constant folding is enabled."
        )
    if "global-constant-propagation" in pass_names:
        scalar_notes.append(
            "Global constant propagation is enabled (O2 proven-safe). "
            "Resets constants at every block boundary (labeled and unlabeled)."
        )
    if "loop-invariant-code-motion" in pass_names:
        scalar_notes.append(
            "Loop-invariant code motion is enabled (O2 proven-safe). "
            "Verifies domination and single-definition safety before hoisting."
        )
    if "repeated-global-load-reuse" in pass_names:
        scalar_notes.append(
            "Repeated global load reuse is enabled. "
            "Uses conservative alias model: any store invalidates all cached loads."
        )
    if "block-simplification" in pass_names:
        scalar_notes.append(
            "Block simplification is enabled (O2 proven-safe). "
            "Merges empty/jump blocks, removes unreachable blocks, preserves side-effecting blocks."
        )
    if "load-hoisting" in pass_names:
        scalar_notes.append(
            "Load hoisting is enabled (O2 proven-safe). "
            "Hoists loop-invariant global loads with domination, single-def, and alias checks."
        )
    if "loop-unrolling" in pass_names:
        scalar_notes.append(
            "Loop unrolling is enabled (O3 experimental). "
            "Unrolls counted loops with even trip counts and register renaming. "
            "Needs complex-loop-body hardening for O2."
        )
    if "linear-scan-register-allocation" in pass_names:
        scalar_notes.append(
            "Linear-scan register allocation is enabled (O3 experimental). "
            "Allocates GPRs and predicate registers with live-interval analysis. "
            "Needs CFG-aware liveness integration for O2."
        )
    if "list-scheduler" in pass_names:
        scalar_notes.append(
            "DDG list scheduler is enabled (O3 experimental). "
            "Reorders AEC instructions within basic blocks to hide latency. "
            "Needs alias-aware memory ordering for O2."
        )

    if scalar_notes:
        notes.extend(scalar_notes)
    else:
        notes.append("O0 contains validation and analysis foundation passes only.")

    missing.append("global CSE")
    if "loop-invariant-code-motion" not in pass_names:
        missing.append("LICM")
    if "record-loop-analysis" not in pass_names:
        pass  # loop analysis is not an optimization, just a fact recorder
    missing.extend(["scheduling", "register-allocation", "GEMM optimization"])
    notes.append(
        f"Not enabled: {', '.join(sorted(missing))}."
    )
    notes.append(
        "Cycle Model metrics remain null because the reduced official C1 package does not provide a Cycle Model."
    )
    return notes


def _build_static_metrics(lowered: LoweredProgram) -> dict[str, Any]:
    instructions = lowered.instructions
    instruction_mix = Counter(inst.opcode for inst in instructions)
    memory_space_ops = Counter(
        inst.memory_space for inst in instructions if inst.memory_space is not None
    )
    gmem_instructions = [
        inst
        for inst in instructions
        if inst.memory_space == "gmem" and inst.opcode in {"LD", "ST", "ATOM"}
    ]
    gmem_bytes_per_warp = sum(
        _memory_instruction_bytes(inst) * WARP_LANES for inst in gmem_instructions
    )
    gmem_services_per_warp = sum(
        _ceil_div(_memory_instruction_bytes(inst) * WARP_LANES, MEMORY_SERVICE_BYTES)
        for inst in gmem_instructions
    )
    return {
        "assumed_warp_lanes": WARP_LANES,
        "branch_count": sum(inst.opcode in {"BR", "BRX", "CALL", "RET"} for inst in instructions),
        "estimated_arithmetic_intensity": None,
        "estimated_dependency_depth": None,
        "estimated_gmem_128b_services_per_warp": gmem_services_per_warp,
        "estimated_gmem_bytes_per_warp": gmem_bytes_per_warp,
        "estimated_lmem_bytes_per_thread": None,
        "estimated_register_pressure": None,
        "estimated_smem_bytes_per_cta": None,
        "gmem_loads": sum(inst.opcode == "LD" and inst.memory_space == "gmem" for inst in instructions),
        "gmem_stores": sum(inst.opcode == "ST" and inst.memory_space == "gmem" for inst in instructions),
        "instruction_count": len(instructions),
        "instruction_mix": dict(sorted(instruction_mix.items())),
        "memory_service_bytes": MEMORY_SERVICE_BYTES,
        "memory_space_ops": dict(sorted(memory_space_ops.items())),
        "smem_ops": sum(inst.memory_space == "smem" for inst in instructions),
    }


def _memory_instruction_bytes(inst: Any) -> int:
    if inst.opcode not in {"LD", "ST", "ATOM"}:
        return 0
    return _DATA_TYPE_BYTES.get(inst.dtype, 0)


def _ceil_div(value: int, divisor: int) -> int:
    if value <= 0:
        return 0
    return (value + divisor - 1) // divisor


def _null_cycle_model_metrics() -> dict[str, None]:
    return {key: None for key in CYCLE_MODEL_METRIC_KEYS}


def _sort_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    sorted_mapping: dict[str, Any] = {}
    for key, value in sorted(mapping.items()):
        if isinstance(value, dict):
            sorted_mapping[key] = _sort_mapping(value)
        else:
            sorted_mapping[key] = value
    return sorted_mapping
