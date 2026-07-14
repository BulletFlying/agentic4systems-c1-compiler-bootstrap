"""Memory optimization passes: load hoisting, address strength reduction."""

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


# ===========================================================================
# Load Hoisting (O3 experimental)
# ===========================================================================

class LoadHoistingPass:
    """Hoist loop-invariant global loads out of natural loops (O2 proven-safe).

    Safety guarantees:
    - Unique preheader required: multi-entry loops are skipped.
    - Conservative alias model: any store in the loop body disables all
      hoisting for that loop.
    - Never hoists predicated loads (predicate may resolve differently
      across iterations).
    - Domination check: the load must dominate the loop latch (the block
      containing the backedge).  Loads inside conditional branches are
      not hoisted because they don't execute on every iteration.
    - Single-def check: the load's destination register must not be
      redefined anywhere else in the loop.
    - Address invariance: the address register's definition must not be
      inside the loop.
    - Invalidates CFG, uniformity, and loops after rewriting.
    """

    name = "load-hoisting"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        cfg = analyses.get("cfg")
        program = module.function.program
        loops = cfg.natural_loops()
        if not loops:
            return PassResult(details={"hoisted": 0, "loops": 0, "transforms_applied": 0})

        dominators = cfg.dominators()

        # Build def map and index→block map
        index_to_block: dict[int, str] = {}
        def_map: dict[str, tuple[int, str]] = {}
        for name, block in cfg.blocks.items():
            for idx in block.item_indices:
                index_to_block[idx] = name
                item = program.items[idx]
                if isinstance(item, str):
                    continue
                dest = _destination_register(item)
                if dest is not None:
                    def_map[dest] = (idx, name)

        total_hoisted = 0
        all_kept: dict[int, str | PTXInstruction] = {i: item for i, item in enumerate(program.items)}
        insertions: dict[int, list[PTXInstruction]] = {}

        for loop in loops:
            header = loop.header
            header_block = cfg.blocks[header]
            preheaders = [p for p in header_block.predecessors if p not in loop.blocks]
            if len(preheaders) != 1:
                continue
            preheader = preheaders[0]
            preheader_block = cfg.blocks[preheader]
            if not preheader_block.item_indices:
                continue

            # ---- Conservative alias: any store in loop → skip entire loop ----
            has_store = False
            for bn in loop.blocks:
                for idx in cfg.blocks[bn].item_indices:
                    item = program.items[idx]
                    if isinstance(item, str):
                        continue
                    base = item.opcode.split(".", 1)[0]
                    if base == "st":
                        has_store = True
                        break
                if has_store:
                    break
            if has_store:
                continue

            # ---- Identify the loop latch (tail block) ----
            backedges = [(t, h) for t, h in cfg.backedges() if h == header]
            latch = backedges[0][0] if backedges else header

            insert_before = preheader_block.item_indices[-1]

            # ---- Count dest register definitions within the loop ----
            loop_def_counts: dict[str, int] = {}
            for bn in loop.blocks:
                for idx in cfg.blocks[bn].item_indices:
                    item = program.items[idx]
                    if isinstance(item, str):
                        continue
                    dest = _destination_register(item)
                    if dest is not None:
                        loop_def_counts[dest] = loop_def_counts.get(dest, 0) + 1

            # ---- Find and hoist invariant loads ----
            for bn in loop.blocks:
                for idx in cfg.blocks[bn].item_indices:
                    item = program.items[idx]
                    if isinstance(item, str):
                        continue

                    # Predicated load filter
                    if item.predicate is not None:
                        continue

                    if not item.opcode.startswith("ld.global"):
                        continue

                    # ---- Domination check: load block must dominate latch ----
                    if bn not in dominators.get(latch, set()):
                        continue

                    # ---- Single-def check: dest register must not be redefined ----
                    dest_reg = _destination_register(item)
                    if dest_reg is not None and loop_def_counts.get(dest_reg, 0) > 1:
                        continue

                    # ---- Address invariance: address register not defined in loop ----
                    addr_op = item.operands[1].strip()
                    if addr_op.startswith("[") and addr_op.endswith("]"):
                        addr_op = addr_op[1:-1].strip()
                    if not addr_op.startswith("%"):
                        continue
                    def_info = def_map.get(addr_op)
                    if def_info is None:
                        # param/special → invariant → hoistable
                        pass
                    else:
                        def_block = def_info[1]
                        if def_block in loop.blocks:
                            continue  # address defined in loop → skip

                    # ---- Hoist: move before the preheader terminator ----
                    all_kept.pop(idx, None)
                    insertions.setdefault(insert_before, []).append(item)
                    total_hoisted += 1

        if total_hoisted == 0:
            return PassResult(details={"hoisted": 0, "loops": len(loops), "transforms_applied": 0})

        rebuilt: list[str | PTXInstruction] = []
        for i, item in enumerate(program.items):
            if i in insertions:
                rebuilt.extend(insertions[i])
            if i in all_kept:
                rebuilt.append(all_kept[i])

        module.function.program = _rebuild_program(program, rebuilt)
        return PassResult(
            changed=True,
            details={"hoisted": total_hoisted, "loops": len(loops), "transforms_applied": total_hoisted},
            invalidated_analyses=frozenset({"cfg", "uniformity", "loops"}),
        )
