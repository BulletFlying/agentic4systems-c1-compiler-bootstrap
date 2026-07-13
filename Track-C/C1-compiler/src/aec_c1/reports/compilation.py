"""Deterministic machine-readable compilation reports."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from ..ir import IRModule
from ..legacy_lowering import LoweredProgram
from ..passes import PassRecord


@dataclass(frozen=True)
class CompilationReport:
    input: str
    optimization: str
    profile: str
    pipeline: str
    passes: tuple[PassRecord, ...]
    metrics: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "input": self.input,
            "optimization": f"O{self.optimization}",
            "profile": self.profile,
            "pipeline": self.pipeline,
            "passes": [record.to_dict() for record in self.passes],
            "metrics": dict(sorted(self.metrics.items())),
            "validation": {
                "local_simulator": "not_run_by_compiler",
                "official_golden_model": "not_available_not_run",
                "official_cycle_model": "not_available_not_run",
            },
            "notes": [
                "M2.2-A pipelines contain analysis and validation passes only.",
                "No scalar optimization pass is claimed by this report.",
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")


def build_metrics(module: IRModule, lowered: LoweredProgram) -> dict[str, int]:
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
    return {
        "basic_block_count": len(module.function.blocks),
        "branch_count": branch_count,
        "code_size_bytes": len(instructions) * 16,
        "highest_encoded_register_index": max(registers, default=0),
        "machine_instruction_count": len(instructions),
        "memory_instruction_count": memory_instruction_count,
        "optimization_transforms_applied": 0,
        "source_instruction_count": source_instruction_count,
    }
