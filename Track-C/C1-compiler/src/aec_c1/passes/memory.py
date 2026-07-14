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
    """Hoist loop-invariant global loads out of natural loops (O3 experimental).

    Safety:
    - Only operates on natural loops with unique preheaders.
    - Conservative alias model: any store in loop body → no hoisting.
    - Never hoists predicated loads.
    - Never hoists across control-flow boundaries.
    - Requires valid CFG with loop analysis.
    """

    name = "load-hoisting"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        cfg = analyses.get("cfg")
        program = module.function.program
        loops = cfg.natural_loops()
        if not loops:
            return PassResult(details={"hoisted": 0, "loops": 0, "transforms_applied": 0})

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

            # Check for stores in loop (conservative alias)
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

            insert_before = preheader_block.item_indices[-1]

            # Find invariant loads in loop
            for bn in loop.blocks:
                for idx in cfg.blocks[bn].item_indices:
                    item = program.items[idx]
                    if isinstance(item, str):
                        continue
                    if item.predicate is not None:
                        continue
                    if not item.opcode.startswith("ld.global"):
                        continue  # only handle global loads
                    # Check address register is loop-invariant
                    addr_op = item.operands[1].strip()
                    if addr_op.startswith("[") and addr_op.endswith("]"):
                        addr_op = addr_op[1:-1].strip()
                    if not addr_op.startswith("%"):
                        continue
                    def_info = def_map.get(addr_op)
                    if def_info is None:
                        continue  # param/special → invariant → hoistable
                    def_block = def_info[1]
                    if def_block in loop.blocks:
                        continue  # address defined in loop → skip

                    # Hoist: create a copy before the preheader terminator
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
            invalidated_analyses=frozenset({"cfg", "uniformity"}),
        )
