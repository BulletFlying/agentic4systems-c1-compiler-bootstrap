"""Narrow, correctness-first scalar optimization passes."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
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
    return set(_collect_read_register_counts(program))


def _collect_read_register_counts(program: PTXProgram) -> Counter[str]:
    reads = Counter[str]()
    for item in program.items:
        if not isinstance(item, str):
            reads.update(_instruction_read_registers(item))
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


class BasicBlockLocalCSEPass:
    """Eliminate repeated unpredicated pure expressions inside one local scope."""

    name = "basic-block-local-cse"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        del analyses
        program = module.function.program
        scopes = _split_cse_scopes(program.items)
        all_read_counts = _collect_read_register_counts(program)
        replacements: dict[str, str] = {}
        removed_count = 0
        kept_items: list[str | PTXInstruction] = []

        for scope_items in scopes:
            if len(scope_items) == 1 and scope_items[0][1] is None:
                kept_items.append(scope_items[0][0])
                continue

            scope_read_counts = Counter[str]()
            for _item, read_registers in scope_items:
                if read_registers is not None:
                    scope_read_counts.update(read_registers)
            outside_reads = {
                name
                for name, count in all_read_counts.items()
                if count > scope_read_counts.get(name, 0)
            }
            optimized_scope, scope_replacements, scope_removed = _optimize_cse_scope(
                [item for item, _ in scope_items if isinstance(item, PTXInstruction)],
                outside_reads,
            )
            kept_items.extend(optimized_scope)
            replacements.update(scope_replacements)
            removed_count += scope_removed

        details = {
            "removed_instruction_count": removed_count,
            "replaced_destination_count": len(replacements),
            "replacements": [
                f"{new_destination} -> {old_destination}"
                for new_destination, old_destination in sorted(replacements.items())
            ],
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


def _split_cse_scopes(
    items: tuple[str | PTXInstruction, ...],
) -> list[list[tuple[str | PTXInstruction, set[str] | None]]]:
    scopes: list[list[tuple[str | PTXInstruction, set[str] | None]]] = []
    current: list[PTXInstruction] = []

    def flush_current() -> None:
        nonlocal current
        if current:
            scopes.append([(item, _instruction_read_registers(item)) for item in current])
            current = []

    for item in items:
        if isinstance(item, str):
            flush_current()
            scopes.append([(item, None)])
            continue
        if _is_cse_scope_boundary(item):
            flush_current()
            scopes.append([(item, None)])
            continue
        current.append(item)
    flush_current()
    return scopes


def _optimize_cse_scope(
    instructions: list[PTXInstruction],
    outside_reads: set[str],
) -> tuple[list[PTXInstruction], dict[str, str], int]:
    expression_destinations: dict[tuple[str, tuple[str, ...]], str] = {}
    aliases: dict[str, str] = {}
    replacements: dict[str, str] = {}
    optimized: list[PTXInstruction] = []
    removed_count = 0

    for inst in instructions:
        rewritten = _rewrite_sources(inst, aliases)
        destination = _destination_register(rewritten)
        if destination is not None:
            _invalidate_for_definition(destination, expression_destinations, aliases)

        key = _cse_expression_key(rewritten)
        if key is not None and destination is not None and destination not in outside_reads:
            prior_destination = expression_destinations.get(key)
            if prior_destination is not None:
                aliases[destination] = _resolve_alias(prior_destination, aliases)
                replacements[destination] = aliases[destination]
                removed_count += 1
                continue
            expression_destinations[key] = destination

        optimized.append(rewritten)

    return optimized, replacements, removed_count


def _is_cse_scope_boundary(inst: PTXInstruction) -> bool:
    if inst.predicate is not None:
        return True

    opcode_parts = inst.opcode.split(".")
    base = opcode_parts[0]
    if _SIDE_EFFECTING_MODIFIERS.intersection(opcode_parts[1:]):
        return True
    if base not in _PURE_RESULT_BASES:
        return True
    return _cse_expression_key(inst) is None


def _cse_expression_key(inst: PTXInstruction) -> tuple[str, tuple[str, ...]] | None:
    if inst.predicate is not None or not inst.operands:
        return None

    opcode_parts = inst.opcode.split(".")
    base = opcode_parts[0]
    expected_operand_count = _PURE_RESULT_OPERAND_COUNTS.get(base)
    if expected_operand_count is None or len(inst.operands) != expected_operand_count:
        return None
    if _SIDE_EFFECTING_MODIFIERS.intersection(opcode_parts[1:]):
        return None

    destination = inst.operands[0].strip()
    if _DESTINATION_REGISTER_RE.fullmatch(destination) is None or destination.startswith("%p"):
        return None
    return inst.opcode, tuple(operand.strip() for operand in inst.operands[1:])


def _destination_register(inst: PTXInstruction) -> str | None:
    if not inst.operands:
        return None
    base = inst.opcode.split(".", 1)[0]
    if base not in _DESTINATION_BASES:
        return None
    destination = inst.operands[0].strip()
    if _DESTINATION_REGISTER_RE.fullmatch(destination) is None:
        return None
    return destination


def _rewrite_sources(inst: PTXInstruction, aliases: dict[str, str]) -> PTXInstruction:
    if not aliases or not inst.operands:
        return inst

    base = inst.opcode.split(".", 1)[0]
    first_source = 1 if base in _DESTINATION_BASES else 0
    rewritten_operands = list(inst.operands)
    for index in range(first_source, len(rewritten_operands)):
        rewritten_operands[index] = _rewrite_operand(rewritten_operands[index], aliases)

    rewritten = tuple(rewritten_operands)
    if rewritten == inst.operands:
        return inst
    return replace(inst, operands=rewritten)


def _rewrite_operand(operand: str, aliases: dict[str, str]) -> str:
    return _REGISTER_REFERENCE_RE.sub(
        lambda match: _resolve_alias(match.group(0), aliases),
        operand,
    )


def _resolve_alias(name: str, aliases: dict[str, str]) -> str:
    seen: set[str] = set()
    current = name
    while current in aliases and current not in seen:
        seen.add(current)
        current = aliases[current]
    return current


def _invalidate_for_definition(
    destination: str,
    expression_destinations: dict[tuple[str, tuple[str, ...]], str],
    aliases: dict[str, str],
) -> None:
    stale_keys = [
        key
        for key, value in expression_destinations.items()
        if value == destination or _expression_uses_register(key, destination)
    ]
    for key in stale_keys:
        del expression_destinations[key]

    stale_aliases = [
        alias
        for alias, target in aliases.items()
        if alias == destination or target == destination
    ]
    for alias in stale_aliases:
        del aliases[alias]


def _expression_uses_register(key: tuple[str, tuple[str, ...]], destination: str) -> bool:
    return any(destination in _REGISTER_REFERENCE_RE.findall(operand) for operand in key[1])


def _instruction_read_registers(inst: PTXInstruction) -> set[str]:
    reads: set[str] = set()
    if inst.predicate is not None:
        predicate = inst.predicate.strip()
        reads.add(predicate if predicate.startswith("%") else f"%{predicate}")

    base = inst.opcode.split(".", 1)[0]
    first_source = 1 if base in _DESTINATION_BASES and inst.operands else 0
    for operand in inst.operands[first_source:]:
        reads.update(_REGISTER_REFERENCE_RE.findall(operand))
    return reads
