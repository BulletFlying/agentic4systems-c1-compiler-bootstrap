"""Liveness analysis for virtual registers in PTX programs.

Computes live ranges per virtual register: first definition and last use
instruction indices. Used by the register allocator to compute interference
and guide allocation decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ptx import PTXInstruction, PTXProgram


@dataclass
class LiveRange:
    register: str
    first_def: int  # instruction index of first definition (-1 if never defined)
    last_use: int   # instruction index of last use (-1 if never used)
    definition_indices: list[int] = field(default_factory=list)
    use_indices: list[int] = field(default_factory=list)

    @property
    def is_live(self) -> bool:
        return self.first_def >= 0 and self.last_use >= 0

    @property
    def span(self) -> int:
        if not self.is_live:
            return 0
        return self.last_use - self.first_def + 1


@dataclass
class LivenessFacts:
    live_ranges: dict[str, LiveRange]
    # Per-instruction: which registers are live at entry
    live_in: dict[int, frozenset[str]] = field(default_factory=dict)
    # Per-instruction: which registers are live at exit
    live_out: dict[int, frozenset[str]] = field(default_factory=dict)


def analyze_liveness(program: PTXProgram) -> LivenessFacts:
    """Compute live ranges for all virtual registers.

    Uses a backward pass through instructions to compute liveness.
    For now this is a simple whole-program analysis; CFG-aware liveness
    can be added when needed.
    """
    ranges: dict[str, LiveRange] = {}
    inst_indices: list[int] = []

    for i, item in enumerate(program.items):
        if isinstance(item, str):
            continue
        inst_indices.append(i)

    # Collect all definitions and uses
    for i in inst_indices:
        item = program.items[i]
        assert isinstance(item, PTXInstruction)

        dest = _dest_register(item)
        if dest is not None:
            if dest not in ranges:
                ranges[dest] = LiveRange(register=dest, first_def=-1, last_use=-1)
            if ranges[dest].first_def < 0:
                ranges[dest].first_def = i
            ranges[dest].definition_indices.append(i)

        for src in _source_registers(item):
            if src not in ranges:
                ranges[src] = LiveRange(register=src, first_def=-1, last_use=-1)
            ranges[src].use_indices.append(i)
            ranges[src].last_use = max(ranges[src].last_use, i)

    return LivenessFacts(live_ranges=ranges)


def _dest_register(inst: PTXInstruction) -> str | None:
    """Return the destination register of an instruction, if any."""
    base = inst.opcode.split(".", 1)[0]
    if base in {"ld", "mov", "add", "sub", "mul", "mad", "and", "or", "xor", "shl", "shr", "cvt", "fma"}:
        if inst.operands and inst.operands[0].startswith("%"):
            return inst.operands[0].strip()
    return None


def _source_registers(inst: PTXInstruction) -> list[str]:
    """Return all source registers of an instruction."""
    regs: list[str] = []
    if inst.predicate is not None:
        regs.append(inst.predicate.strip() if inst.predicate.startswith("%") else f"%{inst.predicate}")

    base = inst.opcode.split(".", 1)[0]
    first_src = 1 if base in {"ld", "mov", "add", "sub", "mul", "mad", "and", "or", "xor", "shl", "shr", "cvt", "fma", "setp"} and inst.operands else 0

    for op in inst.operands[first_src:]:
        op = op.strip()
        # Extract register from [reg] or %reg
        if op.startswith("[") and op.endswith("]"):
            op = op[1:-1].strip()
        if op.startswith("%"):
            regs.append(op)
    return regs
