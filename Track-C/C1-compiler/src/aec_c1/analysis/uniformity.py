"""Uniformity analysis for PTX-style C1 programs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .ptx import PTXInstruction, PTXProgram


class Uniformity(str, Enum):
    UNKNOWN = "unknown"
    UNIFORM = "uniform"
    VARYING = "varying"

    @property
    def is_proven_uniform(self) -> bool:
        return self is Uniformity.UNIFORM

    @property
    def is_proven_varying(self) -> bool:
        return self is Uniformity.VARYING


@dataclass(frozen=True)
class BranchUniformity:
    item_index: int
    source_line: int
    predicate: str
    state: Uniformity

    @property
    def result(self) -> str:
        if self.state is Uniformity.UNIFORM:
            return "proven_uniform"
        if self.state is Uniformity.VARYING:
            return "proven_varying"
        return "unknown"


@dataclass
class UniformityFacts:
    final_values: dict[str, Uniformity] = field(default_factory=dict)
    values_before: dict[int, dict[str, Uniformity]] = field(default_factory=dict)
    values_after: dict[int, dict[str, Uniformity]] = field(default_factory=dict)
    branch_states: dict[int, BranchUniformity] = field(default_factory=dict)
    definitions: dict[str, list[int]] = field(default_factory=dict)
    uses: dict[int, tuple[str, ...]] = field(default_factory=dict)
    definitions_by_index: dict[int, str] = field(default_factory=dict)


def analyze_uniformity(program: PTXProgram) -> UniformityFacts:
    facts = UniformityFacts()
    values: dict[str, Uniformity] = {param.name: Uniformity.UNIFORM for param in program.parameters}

    for index, item in enumerate(program.items):
        if isinstance(item, str):
            continue

        facts.values_before[index] = dict(values)
        uses = tuple(_instruction_uses(item))
        facts.uses[index] = uses
        dest = _instruction_dest(item)
        state = _result_uniformity(item, values, uses)

        if dest is not None:
            values[dest] = state
            facts.definitions.setdefault(dest, []).append(index)
            facts.definitions_by_index[index] = dest

        if item.opcode.split(".")[0] == "bra" and item.predicate is not None:
            predicate = _normalize_predicate(item.predicate)
            branch_state = values.get(predicate, Uniformity.UNKNOWN)
            facts.branch_states[index] = BranchUniformity(
                item_index=index,
                source_line=item.source_line,
                predicate=predicate,
                state=branch_state,
            )

        facts.values_after[index] = dict(values)

    facts.final_values = values
    return facts


def merge_uniformity(states: list[Uniformity]) -> Uniformity:
    if any(state is Uniformity.VARYING for state in states):
        return Uniformity.VARYING
    if states and all(state is Uniformity.UNIFORM for state in states):
        return Uniformity.UNIFORM
    return Uniformity.UNKNOWN


def _result_uniformity(item: PTXInstruction, values: dict[str, Uniformity], uses: tuple[str, ...]) -> Uniformity:
    opcode_parts = item.opcode.split(".")
    base = opcode_parts[0]
    if base == "ld" and len(opcode_parts) >= 2 and opcode_parts[1] == "param":
        return Uniformity.UNIFORM
    if base == "ld" and len(opcode_parts) >= 2 and opcode_parts[1] == "global":
        return Uniformity.VARYING
    if base == "mov":
        if len(item.operands) != 2:
            return Uniformity.UNKNOWN
        source = item.operands[1]
        if _is_immediate(source):
            return Uniformity.UNIFORM
        if source.startswith("%"):
            return _source_uniformity(source, values)
        return Uniformity.UNKNOWN
    if base in {"add", "sub", "mul", "mad", "and", "shr", "cvt", "setp"}:
        return merge_uniformity([_operand_uniformity(operand, values) for operand in uses])
    if base == "st":
        return Uniformity.UNKNOWN
    return Uniformity.UNKNOWN


def _instruction_dest(item: PTXInstruction) -> str | None:
    base = item.opcode.split(".")[0]
    if base in {"ld", "mov", "add", "sub", "mul", "mad", "and", "shr", "cvt", "setp"}:
        if item.operands:
            return _normalize_register(item.operands[0])
    return None


def _instruction_uses(item: PTXInstruction) -> list[str]:
    base = item.opcode.split(".")[0]
    operands = list(item.operands)
    if base in {"ld", "mov", "cvt"}:
        return [_normalize_operand(operand) for operand in operands[1:]]
    if base == "st":
        return [_normalize_operand(operand) for operand in operands]
    if base in {"add", "sub", "mul", "mad", "and", "shr", "setp"}:
        return [_normalize_operand(operand) for operand in operands[1:]]
    if base == "bra" and item.predicate is not None:
        return [_normalize_predicate(item.predicate)]
    return []


def _operand_uniformity(operand: str, values: dict[str, Uniformity]) -> Uniformity:
    if _is_immediate(operand):
        return Uniformity.UNIFORM
    if operand.startswith("[") and operand.endswith("]"):
        operand = operand[1:-1].strip()
    if operand.startswith("%"):
        return _source_uniformity(operand, values)
    return values.get(operand, Uniformity.UNKNOWN)


def _source_uniformity(source: str, values: dict[str, Uniformity]) -> Uniformity:
    source = _normalize_register(source)
    if source in {"%ctaid", "%ctaid.x", "%ctaid.y", "%ctaid.z"}:
        return Uniformity.UNIFORM
    if source in {"%ntid", "%ntid.x", "%ntid.y", "%ntid.z"}:
        return Uniformity.UNIFORM
    if source in {"%nctaid", "%nctaid.x", "%nctaid.y", "%nctaid.z"}:
        return Uniformity.UNIFORM
    if source == "%warpid":
        return Uniformity.UNIFORM
    if source in {"%tid", "%tid.x", "%tid.y", "%tid.z", "%laneid"}:
        return Uniformity.VARYING
    return values.get(source, Uniformity.UNKNOWN)


def _normalize_operand(operand: str) -> str:
    operand = operand.strip()
    if operand.startswith("[") and operand.endswith("]"):
        operand = operand[1:-1].strip()
    if operand.startswith("%p"):
        return _normalize_predicate(operand)
    return _normalize_register(operand)


def _normalize_register(register: str) -> str:
    return register.strip()


def _normalize_predicate(predicate: str) -> str:
    predicate = predicate.strip()
    if not predicate.startswith("%"):
        predicate = f"%{predicate}"
    return predicate


def _is_immediate(operand: str) -> bool:
    operand = operand.strip()
    if operand.startswith("0f") or operand.startswith("0x"):
        return True
    if operand.startswith("-"):
        return operand[1:].isdigit()
    return operand.isdigit()
