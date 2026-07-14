"""Loop-invariant code motion pass (O2 proven-safe).

Hoists loop-invariant pure computations out of natural loops with domination
and single-definition safety checks.
"""

from __future__ import annotations

from ..analysis import AnalysisManager
from ..ir import IRModule
from ..ptx import PTXInstruction
from ._helpers import (
    _PURE_RESULT_BASES,
    _destination_register,
    _is_immediate,
    _rebuild_program,
)
from .base import PassResult


class LoopInvariantCodeMotionPass:
    """Hoist loop-invariant pure computations out of natural loops (O2 proven-safe).

    Safety guarantees:
    - Domination: every operand defined outside the loop must have its defining
      block dominate the loop header, so the value is available on all paths
      into the loop.
    - Single-definition: a candidate instruction's destination register must
      have exactly one definition within the loop.  Registers with multiple
      intra-loop definitions are not hoisted because hoisting would alter
      which definition reaches later uses.
    - Side-effect filtering: load, store, branch, call, atom, setp, and any
      instruction with a .cc modifier are never hoisted.
    - Predicated filtering: any instruction with an active predicate is never
      hoisted; the predicate may resolve differently across loop iterations.
    - Multi-entry loops are skipped (require a unique preheader).
    """

    name = "loop-invariant-code-motion"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        cfg = analyses.get("cfg")
        program = module.function.program

        loops = cfg.natural_loops()
        if not loops:
            return PassResult(
                details={"hoisted_count": 0, "loops_found": 0, "transforms_applied": 0},
            )

        dominators = cfg.dominators()

        index_to_block: dict[int, str] = {}
        for name, block in cfg.blocks.items():
            for idx in block.item_indices:
                index_to_block[idx] = name

        def_map: dict[str, tuple[int, str]] = {}
        for i, item in enumerate(program.items):
            if isinstance(item, str):
                continue
            dest = _destination_register(item)
            block_name = index_to_block.get(i)
            if dest is not None and block_name is not None:
                def_map[dest] = (i, block_name)

        total_hoisted = 0
        all_kept: dict[int, str | PTXInstruction] = {
            i: item for i, item in enumerate(program.items)
        }
        insertions: dict[int, list[PTXInstruction]] = {}

        for loop in loops:
            loop_blocks = loop.blocks
            header = loop.header
            header_dominators = dominators.get(header, set())

            header_block = cfg.blocks[header]
            preheaders = [p for p in header_block.predecessors if p not in loop_blocks]
            if len(preheaders) != 1:
                continue
            preheader = preheaders[0]
            preheader_block = cfg.blocks[preheader]

            if not preheader_block.item_indices:
                continue
            insert_before = preheader_block.item_indices[-1]

            # Count definitions per register within the loop for single-def safety.
            loop_def_counts: dict[str, int] = {}
            for block_name in sorted(loop_blocks):
                block = cfg.blocks[block_name]
                for idx in block.item_indices:
                    item = program.items[idx]
                    if isinstance(item, str):
                        continue
                    dest = _destination_register(item)
                    if dest is not None:
                        loop_def_counts[dest] = loop_def_counts.get(dest, 0) + 1

            invariant: set[int] = set()
            changed = True
            while changed:
                changed = False
                for block_name in sorted(loop_blocks):
                    block = cfg.blocks[block_name]
                    for idx in block.item_indices:
                        if idx in invariant:
                            continue
                        item = program.items[idx]
                        if isinstance(item, str):
                            continue
                        # Predicated filtering
                        if item.predicate is not None:
                            continue
                        # Side-effect filtering — only pure arithmetic / data-movement bases
                        base = item.opcode.split(".", 1)[0]
                        if base not in _PURE_RESULT_BASES:
                            continue
                        # Explicit side-effect guard: never hoist anything with .cc modifier
                        if ".cc" in item.opcode:
                            continue

                        operands = list(item.operands[1:]) if _destination_register(item) else list(item.operands)
                        all_invariant = True
                        for op in operands:
                            op = op.strip()
                            if op.startswith("[") and op.endswith("]"):
                                op = op[1:-1].strip()
                            if _is_immediate(op):
                                continue
                            if op.startswith("%"):
                                def_info = def_map.get(op)
                                if def_info is None:
                                    # Operand register has no known definition.
                                    # Could be a parameter / special register — treat as invariant.
                                    continue
                                def_idx, def_block = def_info
                                if def_block not in loop_blocks:
                                    # Definition is outside the loop — must dominate header.
                                    if def_block not in header_dominators:
                                        all_invariant = False
                                        break
                                    # Safe: external def dominates loop header.
                                    continue
                                if def_idx in invariant:
                                    # Operand is already marked invariant — safe.
                                    continue
                                # Operand defined in loop but not invariant yet.
                                all_invariant = False
                                break

                        if all_invariant:
                            invariant.add(idx)
                            changed = True

            if not invariant:
                continue

            # Single-def safety: only hoist instructions whose destination
            # register has exactly one definition in the loop.
            safe_invariant: list[int] = []
            for idx in sorted(invariant):
                item = program.items[idx]
                if isinstance(item, str):
                    continue
                dest = _destination_register(item)
                if dest is not None and loop_def_counts.get(dest, 0) != 1:
                    # Multiple definitions of this register exist within the
                    # loop — hoisting this one would alter which definition
                    # reaches later intra-loop uses.
                    continue
                safe_invariant.append(idx)

            for idx in safe_invariant:
                item = program.items[idx]
                if isinstance(item, str):
                    continue
                all_kept.pop(idx, None)
                insertions.setdefault(insert_before, []).append(item)
                total_hoisted += 1

        if total_hoisted == 0:
            return PassResult(
                details={"hoisted_count": 0, "loops_found": len(loops), "transforms_applied": 0},
            )

        rebuilt: list[str | PTXInstruction] = []
        for i, item in enumerate(program.items):
            if i in insertions:
                rebuilt.extend(insertions[i])
            if i in all_kept:
                rebuilt.append(all_kept[i])

        module.function.program = _rebuild_program(program, rebuilt)
        return PassResult(
            changed=True,
            details={
                "hoisted_count": total_hoisted,
                "loops_found": len(loops),
                "transforms_applied": total_hoisted,
            },
            invalidated_analyses=frozenset({"cfg", "uniformity"}),
        )
