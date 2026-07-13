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


@dataclass(frozen=True)
class CompilationReport:
    input: str
    optimization: str
    profile: str
    pipeline: str
    passes: tuple[PassRecord, ...]
    metrics: dict[str, Any]

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
    return {
        "branch_count": sum(inst.opcode in {"BR", "BRX", "CALL", "RET"} for inst in instructions),
        "estimated_dependency_depth": None,
        "estimated_register_pressure": None,
        "gmem_loads": sum(inst.opcode == "LD" and inst.memory_space == "gmem" for inst in instructions),
        "gmem_stores": sum(inst.opcode == "ST" and inst.memory_space == "gmem" for inst in instructions),
        "instruction_count": len(instructions),
        "instruction_mix": dict(sorted(instruction_mix.items())),
        "smem_ops": sum(inst.memory_space == "smem" for inst in instructions),
    }


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
