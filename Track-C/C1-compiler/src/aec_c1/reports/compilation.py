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
    performance_target: str = "aec_slide_constraints"

    def to_dict(self) -> dict[str, Any]:
        metrics = dict(self.metrics)
        static_metrics = metrics.pop("static_metrics", {})
        cycle_model_metrics = metrics.pop("cycle_model_metrics", _null_cycle_model_metrics())
        return {
            "schema_version": 1,
            "input": self.input,
            "optimization": f"O{self.optimization}",
            "profile": self.profile,
            "pipeline": self.pipeline,
            "performance_target": self.performance_target,
            "passes": [record.to_dict() for record in self.passes],
            "metrics": dict(sorted(metrics.items())),
            "static_metrics": _sort_mapping(static_metrics),
            "cycle_model_metrics": _sort_mapping(cycle_model_metrics),
            "validation": {
                "local_simulator": "not_run_by_compiler",
                "official_golden_model": "not_available_not_run",
                "official_cycle_model": "not_available_not_run",
            },
            "notes": [
                "M2.2-A pipelines contain analysis and validation passes only.",
                "No scalar optimization pass is claimed by this report.",
                "Official Cycle Model metrics are represented as null until provided by the evaluator.",
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")


def build_metrics(module: IRModule, lowered: LoweredProgram) -> dict[str, Any]:
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
    return {
        "basic_block_count": len(module.function.blocks),
        "branch_count": branch_count,
        "code_size_bytes": len(instructions) * 16,
        "highest_encoded_register_index": max(registers, default=0),
        "machine_instruction_count": len(instructions),
        "memory_instruction_count": memory_instruction_count,
        "optimization_transforms_applied": 0,
        "source_instruction_count": source_instruction_count,
        "static_metrics": static_metrics,
        "cycle_model_metrics": _null_cycle_model_metrics(),
    }


def _build_static_metrics(lowered: LoweredProgram) -> dict[str, Any]:
    instructions = lowered.instructions
    instruction_mix = Counter(inst.opcode for inst in instructions)
    memory_space_ops = Counter(
        inst.memory_space for inst in instructions if inst.memory_space is not None
    )
    gmem_bytes = sum(
        _memory_instruction_bytes(inst)
        for inst in instructions
        if inst.memory_space == "gmem"
    )
    return {
        "branch_count": sum(inst.opcode in {"BR", "BRX", "CALL", "RET"} for inst in instructions),
        "estimated_arithmetic_intensity": None,
        "estimated_dependency_depth": None,
        "estimated_gmem_bytes": gmem_bytes,
        "estimated_gmem_lines_128b": _ceil_div(gmem_bytes, 128),
        "estimated_lmem_bytes_per_thread": None,
        "estimated_register_pressure": None,
        "estimated_smem_bytes_per_cta": None,
        "gmem_loads": sum(inst.opcode == "LD" and inst.memory_space == "gmem" for inst in instructions),
        "gmem_stores": sum(inst.opcode == "ST" and inst.memory_space == "gmem" for inst in instructions),
        "instruction_count": len(instructions),
        "instruction_mix": dict(sorted(instruction_mix.items())),
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
