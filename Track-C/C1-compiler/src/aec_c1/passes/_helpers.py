"""Shared constants and helper functions for scalar optimization passes."""

from __future__ import annotations

from collections import Counter
import math
import re
import struct
from ..analysis.cfg import CFG
from ..ptx import PTXInstruction, PTXProgram


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PURE_RESULT_OPERAND_COUNTS = {
    "add": 3, "and": 3, "cvt": 2, "mad": 4, "mov": 2,
    "mul": 3, "or": 3, "shl": 3, "shr": 3, "sub": 3, "xor": 3,
}
_PURE_RESULT_BASES = frozenset(_PURE_RESULT_OPERAND_COUNTS)
_DESTINATION_BASES = _PURE_RESULT_BASES | {"ld", "setp"}
_SIDE_EFFECTING_MODIFIERS = frozenset({"cc"})
_REGISTER_REFERENCE_RE = re.compile(r"%(?:rd|bd|p|r|s|b|f|h)\d*")
_DESTINATION_REGISTER_RE = re.compile(r"%(?:rd|bd|p|r|s|b|f|h)\d*")
_INT32_TYPES = frozenset({"b32", "s32", "u32"})
_LOCAL_CONSTANT_FOLD_BASES = frozenset({"add", "mov", "mul", "sub"})
_SIDE_EFFECTING_BASES = frozenset({"ld", "st", "bra", "ret", "setp", "atom", "call"})


# ---------------------------------------------------------------------------
# Register analysis
# ---------------------------------------------------------------------------

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


def _collect_read_registers(program: PTXProgram) -> set[str]:
    return set(_collect_read_register_counts(program))


def _collect_read_register_counts(program: PTXProgram) -> Counter[str]:
    reads = Counter[str]()
    for item in program.items:
        if not isinstance(item, str):
            reads.update(_instruction_read_registers(item))
    return reads


def _is_side_effecting(inst: PTXInstruction) -> bool:
    """Instructions that can never be removed by DCE."""
    if inst.predicate is not None:
        return True
    parts = inst.opcode.split(".")
    base = parts[0]
    if ".cc" in inst.opcode or any(p == "cc" for p in parts[1:]):
        return True
    if base in _SIDE_EFFECTING_BASES:
        return True
    if base == "setp":
        return True
    dest = _destination_register(inst)
    if dest is not None and dest.startswith("%p"):
        return True
    if "pred" in parts:
        return True
    if base not in _PURE_RESULT_BASES:
        return True
    return False


# ---------------------------------------------------------------------------
# Constant folding helpers
# ---------------------------------------------------------------------------

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


def _scalar_bits_to_f32(bits: int) -> float:
    """Convert 32-bit IEEE 754 bit pattern to float (little-endian, AEC format)."""
    return struct.unpack("<f", struct.pack("<I", bits & 0xFFFFFFFF))[0]


def _scalar_f32_to_bits(value: float) -> int:
    """Convert float to 32-bit IEEE 754 bit pattern (little-endian, AEC format)."""
    return struct.unpack("<I", struct.pack("<f", value))[0]


def _evaluate_f32(base: str, lhs_bits: int, rhs_bits: int) -> int | None:
    lhs = _scalar_bits_to_f32(lhs_bits)
    rhs = _scalar_bits_to_f32(rhs_bits)
    if base == "add":
        value = lhs + rhs
    elif base == "mul":
        value = lhs * rhs
    else:
        return None
    if not math.isfinite(value):
        return None
    try:
        return _scalar_f32_to_bits(value)
    except OverflowError:
        return None


def _format_constant(known: tuple[str, int]) -> str:
    ptx_type, value = known
    if ptx_type == "f32":
        return f"0f{value & 0xFFFFFFFF:08x}"
    return str(value & 0xFFFFFFFF)


def _is_immediate(operand: str) -> bool:
    operand = operand.strip()
    if operand.startswith("0f") or operand.startswith("0x"):
        return True
    if operand.startswith("-"):
        return operand[1:].isdigit()
    return operand.isdigit()


def _label_to_block(label: str, cfg: CFG) -> str | None:
    """Map a label to its containing block name using CFG facts."""
    for name, block in cfg.blocks.items():
        if label in block.labels:
            return name
    return None


def _rebuild_program(program: PTXProgram, kept_items: list) -> PTXProgram:
    """Rebuild a PTXProgram from a list of items (shared template)."""
    return PTXProgram(
        kernel_name=program.kernel_name,
        parameters=program.parameters,
        registers=program.registers,
        items=tuple(kept_items),
    )
