"""Narrow, correctness-first scalar optimization passes."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
import math
import re
import struct

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
_INT32_TYPES = frozenset({"b32", "s32", "u32"})
_LOCAL_CONSTANT_FOLD_BASES = frozenset({"add", "mov", "mul", "sub"})


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


class LocalConstantFoldingPass:
    """Fold provably constant unpredicated pure expressions within a local block."""

    name = "local-constant-folding"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        del analyses
        program = module.function.program
        constants: dict[str, tuple[str, int]] = {}
        kept_items: list[str | PTXInstruction] = []
        folded_destinations: list[str] = []

        for item in program.items:
            if isinstance(item, str):
                constants.clear()
                kept_items.append(item)
                continue
            if _is_constant_fold_boundary(item):
                constants.clear()
                kept_items.append(item)
                continue

            folded, known_constant = _fold_local_constant_instruction(item, constants)
            destination = _destination_register(item)
            if destination is not None:
                if known_constant is None:
                    constants.pop(destination, None)
                else:
                    constants[destination] = known_constant
            if folded != item:
                folded_destinations.append(destination or "<unknown>")
            kept_items.append(folded)

        folded_count = len(folded_destinations)
        details = {
            "folded_destinations": sorted(folded_destinations),
            "folded_instruction_count": folded_count,
            "transforms_applied": folded_count,
        }
        if folded_count == 0:
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

    for index, inst in enumerate(instructions):
        rewritten = _rewrite_sources(inst, aliases)
        destination = _destination_register(rewritten)
        if destination is not None:
            _invalidate_for_definition(destination, expression_destinations, aliases)

        key = _cse_expression_key(rewritten)
        if key is not None and destination is not None and destination not in outside_reads:
            prior_destination = expression_destinations.get(key)
            if prior_destination is not None:
                alias_target = _resolve_alias(prior_destination, aliases)
                if _alias_read_after_target_redefinition(
                    destination,
                    alias_target,
                    instructions[index + 1 :],
                ):
                    expression_destinations[key] = destination
                else:
                    aliases[destination] = alias_target
                    replacements[destination] = alias_target
                    removed_count += 1
                    continue
            else:
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


def _is_constant_fold_boundary(inst: PTXInstruction) -> bool:
    if inst.predicate is not None:
        return True
    opcode_parts = inst.opcode.split(".")
    base = opcode_parts[0]
    if _SIDE_EFFECTING_MODIFIERS.intersection(opcode_parts[1:]):
        return True
    if base not in _LOCAL_CONSTANT_FOLD_BASES:
        return True
    if base == "mov":
        return len(opcode_parts) != 2 or len(inst.operands) != 2
    if base in {"add", "sub", "mul"}:
        return len(opcode_parts) != 2 or len(inst.operands) != 3
    return True


def _fold_local_constant_instruction(
    inst: PTXInstruction,
    constants: dict[str, tuple[str, int]],
) -> tuple[PTXInstruction, tuple[str, int] | None]:
    opcode_parts = inst.opcode.split(".")
    base, ptx_type = opcode_parts[0], opcode_parts[-1]
    destination = _destination_register(inst)
    if destination is None or destination.startswith("%p"):
        return inst, None

    if base == "mov":
        known = _resolve_constant(inst.operands[1], ptx_type, constants)
        if known is None:
            return inst, None
        folded_operand = _format_constant(known)
        folded = replace(inst, operands=(destination, folded_operand))
        return folded, known

    lhs = _resolve_constant(inst.operands[1], ptx_type, constants)
    rhs = _resolve_constant(inst.operands[2], ptx_type, constants)
    if lhs is None or rhs is None:
        return inst, None

    if ptx_type == "u32" and base in {"add", "sub", "mul"}:
        result = _evaluate_u32(base, lhs[1], rhs[1])
        known = ("u32", result)
    elif ptx_type == "f32" and base in {"add", "mul"}:
        result = _evaluate_f32(base, lhs[1], rhs[1])
        if result is None:
            return inst, None
        known = ("f32", result)
    else:
        return inst, None

    folded = replace(inst, opcode=f"mov.{known[0]}", operands=(destination, _format_constant(known)))
    return folded, known


def _resolve_constant(
    operand: str,
    ptx_type: str,
    constants: dict[str, tuple[str, int]],
) -> tuple[str, int] | None:
    operand = operand.strip()
    if _DESTINATION_REGISTER_RE.fullmatch(operand):
        known = constants.get(operand)
        if known is None or not _constant_type_matches(known[0], ptx_type):
            return None
        return ptx_type, _coerce_constant_value(known[1], ptx_type)
    return _parse_immediate_constant(operand, ptx_type)


def _constant_type_matches(known_type: str, requested_type: str) -> bool:
    if requested_type == "f32":
        return known_type == "f32"
    if requested_type in _INT32_TYPES:
        return known_type in _INT32_TYPES
    return known_type == requested_type


def _coerce_constant_value(value: int, ptx_type: str) -> int:
    if ptx_type in _INT32_TYPES or ptx_type == "f32":
        return value & 0xFFFFFFFF
    return value


def _parse_immediate_constant(token: str, ptx_type: str) -> tuple[str, int] | None:
    token = token.strip()
    if ptx_type == "f32":
        if not token.startswith("0f"):
            return None
        try:
            return "f32", int(token[2:], 16) & 0xFFFFFFFF
        except ValueError:
            return None
    if ptx_type in _INT32_TYPES:
        if token.startswith("0f"):
            return None
        try:
            return ptx_type, int(token, 0) & 0xFFFFFFFF
        except ValueError:
            return None
    return None


def _evaluate_u32(base: str, lhs: int, rhs: int) -> int:
    if base == "add":
        return (lhs + rhs) & 0xFFFFFFFF
    if base == "sub":
        return (lhs - rhs) & 0xFFFFFFFF
    if base == "mul":
        return (lhs * rhs) & 0xFFFFFFFF
    raise ValueError(f"unsupported u32 fold op: {base}")


def _evaluate_f32(base: str, lhs_bits: int, rhs_bits: int) -> int | None:
    lhs = _bits_to_f32(lhs_bits)
    rhs = _bits_to_f32(rhs_bits)
    if base == "add":
        value = lhs + rhs
    elif base == "mul":
        value = lhs * rhs
    else:
        return None
    if not math.isfinite(value):
        return None
    try:
        return _f32_to_bits(value)
    except OverflowError:
        return None


def _bits_to_f32(bits: int) -> float:
    return struct.unpack("!f", (bits & 0xFFFFFFFF).to_bytes(4, "big"))[0]


def _f32_to_bits(value: float) -> int:
    return struct.unpack("!I", struct.pack("!f", value))[0]


def _format_constant(known: tuple[str, int]) -> str:
    ptx_type, value = known
    if ptx_type == "f32":
        return f"0f{value & 0xFFFFFFFF:08x}"
    return str(value & 0xFFFFFFFF)


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

    stale_aliases = [alias for alias in aliases if alias == destination]
    for alias in stale_aliases:
        del aliases[alias]


def _alias_read_after_target_redefinition(
    alias: str,
    target: str,
    future_instructions: list[PTXInstruction],
) -> bool:
    target_redefined = False
    for inst in future_instructions:
        if _destination_register(inst) == target:
            target_redefined = True
        if target_redefined and alias in _instruction_read_registers(inst):
            return True
    return False


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
