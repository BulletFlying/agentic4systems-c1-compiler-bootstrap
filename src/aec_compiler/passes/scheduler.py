"""List scheduler with data-dependence graph for AEC instructions.

Operates post-lowering: reorders AEC instructions within basic blocks
to hide load latency while respecting all data and memory dependencies.
"""

from __future__ import annotations

from dataclasses import replace

from ..analysis import AnalysisManager
from ..ir import IRModule
from ..isa import AECInstruction
from ..legacy_lowering import LoweredProgram
from .base import PassResult


def _schedule_block(insts: list[AECInstruction]) -> list[AECInstruction]:
    """Schedule instructions within a single basic block."""
    n = len(insts)
    if n <= 2:
        return list(insts)

    # Classify each instruction
    kinds = [_inst_kind(i) for i in insts]

    # Build all def positions per register (sorted).  Temp registers like
    # R240-R255 are reused by LOADI — the DDG must use the closest
    # preceding definition, not just the last one.
    all_def_pos: dict[int, list[int]] = {}
    for idx, inst in enumerate(insts):
        if _has_dest(inst):
            all_def_pos.setdefault(inst.dest, []).append(idx)

    # Build ready set: instructions with all operands defined.
    # Also add STORE→LOAD barriers: a LOAD after a STORE must not move
    # before it (conservative alias safety — STORE may alias any LOAD).
    ready: list[int] = []
    dep_count: list[int] = []
    dependents: dict[int, list[int]] = {}

    last_store_idx: int | None = None
    for idx, inst in enumerate(insts):
        srcs = _source_regs(inst)
        unresolved = 0
        for s in srcs:
            defs = all_def_pos.get(s, [])
            # Find the closest definition before this use.
            closest_def = -1
            for d in defs:
                if d < idx and d > closest_def:
                    closest_def = d
            if closest_def >= 0:
                unresolved += 1
                dependents.setdefault(closest_def, []).append(idx)
        # STORE→LOAD barrier: each LOAD depends on the most recent STORE.
        if kinds[idx] == "LOAD" and last_store_idx is not None:
            unresolved += 1
            dependents.setdefault(last_store_idx, []).append(idx)
        if kinds[idx] == "STORE":
            last_store_idx = idx
        dep_count.append(unresolved)
        if unresolved == 0:
            ready.append(idx)

    # Priority: LOAD first, then COMPUTE, then STORE, then CONTROL.
    # STORES are NOT reordered relative to each other (memory order).
    def priority(idx: int) -> int:
        k = kinds[idx]
        if k == "LOAD":
            return 0
        if k == "COMPUTE":
            return 1
        if k == "STORE":
            return 2 + idx  # prevent ST reordering
        return 1000 + idx  # CONTROL at end, preserve relative order

    scheduled: list[int] = []
    while ready:
        # Pick highest-priority ready instruction
        ready.sort(key=lambda i: (priority(i), i))
        # For LOADs, pick one; for others, pick the first
        best = ready.pop(0)
        scheduled.append(best)
        # Update dependents
        for dep in dependents.get(best, []):
            dep_count[dep] -= 1
            if dep_count[dep] == 0:
                ready.append(dep)

    # Append any remaining unscheduled (shouldn't happen with valid DDG)
    for i in range(n):
        if i not in scheduled:
            scheduled.append(i)

    return [insts[i] for i in scheduled]


def _inst_kind(inst: AECInstruction) -> str:
    op = inst.opcode.upper()
    if op in {"BR", "BRX", "HALT", "CALL", "RET"}:
        return "CONTROL"
    if op == "ST":
        return "STORE"
    if op == "LD":
        return "LOAD"
    return "COMPUTE"


def _has_dest(inst: AECInstruction) -> bool:
    return inst.opcode.upper() not in {"ST", "BR", "BRX", "HALT", "CALL", "RET"}


def _source_regs(inst: AECInstruction) -> list[int]:
    regs: list[int] = []
    for val in (inst.src1, inst.src2, inst.src3):
        if isinstance(val, int) and 0 <= val <= 255:
            regs.append(val)
    return regs


def schedule_lowered(lowered: LoweredProgram, module: IRModule) -> LoweredProgram:
    """Post-lowering entry point: schedule AEC instructions within basic blocks."""

    instructions = list(lowered.instructions)
    if len(instructions) <= 2:
        return lowered

    # Find basic block boundaries from branch targets and labels
    leaders: set[int] = {0}
    for i, inst in enumerate(instructions):
        if inst.opcode.upper() in {"BR", "BRX"}:
            target = inst.imm
            if 0 <= target < len(instructions):
                leaders.add(target)
            if i + 1 < len(instructions):
                leaders.add(i + 1)
        elif inst.opcode.upper() == "HALT":
            if i + 1 < len(instructions):
                leaders.add(i + 1)

    sorted_leaders = sorted(leaders)
    for li in range(len(sorted_leaders)):
        start = sorted_leaders[li]
        end = sorted_leaders[li + 1] if li + 1 < len(sorted_leaders) else len(instructions)
        block = instructions[start:end]
        if len(block) <= 2:
            continue
        scheduled = _schedule_block(block)
        for j, inst in enumerate(scheduled):
            instructions[start + j] = inst

    return LoweredProgram(
        instructions=instructions,
        parameter_offsets=lowered.parameter_offsets,
    )
