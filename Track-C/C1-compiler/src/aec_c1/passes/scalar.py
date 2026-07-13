"""Narrow, correctness-first scalar optimization passes."""

from __future__ import annotations

import re

from ..analysis import AnalysisManager
from ..ir import IRModule
from ..ptx import PTXInstruction, PTXProgram
from .base import PassResult


_PURE_RESULT_OPERAND_COUNTS = {
    "add": 3,
    "and": 3,
    "cvt": 2,
    "mad": 4,
    "mov": 2,
    "mul": 3,
    "or": 3,
    "shl": 3,
    "shr": 3,
    "sub": 3,
    "xor": 3,
}
_PURE_RESULT_BASES = frozenset(_PURE_RESULT_OPERAND_COUNTS)
_DESTINATION_BASES = _PURE_RESULT_BASES | {"ld", "setp"}
_SIDE_EFFECTING_MODIFIERS = frozenset({"cc"})
_REGISTER_REFERENCE_RE = re.compile(r"%[A-Za-z]+\d+")
_DESTINATION_REGISTER_RE = re.compile(r"%[A-Za-z]+\d+")


class ConservativeDeadResultEliminationPass:
    """Remove unpredicated pure results that are never read anywhere.

    This is intentionally weaker than general dead-code elimination. It does
    not require SSA or liveness and never removes memory, control, predicate,
    synchronization, call, return, malformed, or unknown operations.
    """

    name = "conservative-dead-result-elimination"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        del analyses
        program = module.function.program
        read_registers = _collect_read_registers(program)
        kept_items: list[str | PTXInstruction] = []
        removed_destinations: list[str] = []

        for item in program.items:
            if isinstance(item, str) or not _is_removable_dead_result(item, read_registers):
                kept_items.append(item)
                continue
            removed_destinations.append(item.operands[0].strip())

        removed_count = len(removed_destinations)
        details = {
            "removed_destinations": sorted(set(removed_destinations)),
            "removed_instruction_count": removed_count,
            "transforms_applied": removed_count,
        }
        if removed_count == 0:
            return PassResult(details=details)

        module.function.program = PTXProgram(
            kernel_name=program.kernel_name,
            parameters=program.parameters,
            registers=program.registers,
            items=tuple(kept_items),
        )
        return PassResult(
            changed=True,
            details=details,
            invalidated_analyses=frozenset({"cfg", "uniformity"}),
        )


def _collect_read_registers(program: PTXProgram) -> set[str]:
    reads: set[str] = set()
    for item in program.items:
        if isinstance(item, str):
            continue
        if item.predicate is not None:
            predicate = item.predicate.strip()
            reads.add(predicate if predicate.startswith("%") else f"%{predicate}")

        base = item.opcode.split(".", 1)[0]
        first_source = 1 if base in _DESTINATION_BASES and item.operands else 0
        for operand in item.operands[first_source:]:
            reads.update(_REGISTER_REFERENCE_RE.findall(operand))
    return reads


def _is_removable_dead_result(inst: PTXInstruction, read_registers: set[str]) -> bool:
    if inst.predicate is not None or not inst.operands:
        return False

    opcode_parts = inst.opcode.split(".")
    base = opcode_parts[0]
    expected_operand_count = _PURE_RESULT_OPERAND_COUNTS.get(base)
    if expected_operand_count is None or len(inst.operands) != expected_operand_count:
        return False
    if _SIDE_EFFECTING_MODIFIERS.intersection(opcode_parts[1:]):
        return False

    destination = inst.operands[0].strip()
    if _DESTINATION_REGISTER_RE.fullmatch(destination) is None:
        return False
    if destination.startswith("%p"):
        return False
    return destination not in read_registers
