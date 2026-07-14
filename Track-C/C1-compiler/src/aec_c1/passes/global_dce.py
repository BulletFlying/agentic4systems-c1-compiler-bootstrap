"""Worklist-based global dead code elimination (O2 scoring-critical)."""

from __future__ import annotations

from ..analysis import AnalysisManager
from ..ir import IRModule
from ..ptx import PTXInstruction
from ._helpers import (
    _destination_register,
    _instruction_read_registers,
    _is_side_effecting,
    _rebuild_program,
)
from .base import PassResult


class GlobalDeadCodeEliminationPass:
    """Iteratively remove instructions whose results are never used.

    Unlike conservative DRE, this uses a worklist algorithm that propagates
    liveness through def-use chains. An instruction is live if any of its
    results may be observed: side-effecting operations, branch conditions,
    predicate definitions, and transitively any instruction that computes a
    value read by a live instruction.

    Safety:
    - Never removes memory, control, predicate, or predicated instructions.
    - Never removes .cc carry or predicate-destination instructions.
    - Requires CFG/uniformity to be valid (consumed, not mutated).
    - Invalidates CFG and uniformity after changing the program.
    """

    name = "global-dead-code-elimination"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        del analyses
        program = module.function.program
        items = program.items

        indexed_items = [(i, item) for i, item in enumerate(items) if not isinstance(item, str)]

        # Build def map: register -> list of defining instruction indices
        def_map: dict[str, list[int]] = {}
        for i, item in indexed_items:
            dest = _destination_register(item)
            if dest is not None and not dest.startswith("%p"):
                def_map.setdefault(dest, []).append(i)

        # Build use map: instruction index -> set of source registers
        use_map: dict[int, set[str]] = {}
        for i, item in indexed_items:
            use_map[i] = _instruction_read_registers(item)

        # Live set (worklist algorithm)
        live: set[int] = set()
        worklist: list[int] = []

        def mark_live(idx: int) -> None:
            if idx not in live:
                live.add(idx)
                worklist.append(idx)

        # Seed: all side-effecting instructions are live
        for i, item in indexed_items:
            if _is_side_effecting(item):
                mark_live(i)

        # Propagate: for each live instruction, mark all source definitions as live
        while worklist:
            idx = worklist.pop()
            for src_reg in use_map.get(idx, set()):
                for def_idx in def_map.get(src_reg, ()):
                    mark_live(def_idx)

        # Remove dead instructions
        dead_indices = {i for i, item in indexed_items if i not in live}
        if not dead_indices:
            return PassResult(
                details={"removed_instruction_count": 0, "live_count": len(live), "transforms_applied": 0},
            )

        kept_items: list[str | PTXInstruction] = []
        for i, item in enumerate(items):
            if i in dead_indices:
                continue
            kept_items.append(item)

        removed = len(dead_indices)
        module.function.program = _rebuild_program(program, kept_items)
        return PassResult(
            changed=True,
            details={
                "removed_instruction_count": removed,
                "live_count": len(live),
                "transforms_applied": removed,
            },
            invalidated_analyses=frozenset({"cfg", "uniformity"}),
        )
