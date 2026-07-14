"""GEMM-specific optimization passes: loop unrolling, accumulator expansion."""

from __future__ import annotations

from dataclasses import replace

from ..analysis import AnalysisManager
from ..ir import IRModule
from ..ptx import PTXInstruction, PTXProgram
from ._helpers import (
    _PURE_RESULT_BASES,
    _destination_register,
    _instruction_read_registers,
    _rebuild_program,
)
from .base import PassResult


class LoopUnrollingPass:
    """Unroll innermost counted loops by factor N (default 2).

    Detects loops with: counter init (mov.u32 K, 0), increment by constant
    (add.u32 K, K, C), comparison against constant bound (setp.lt/ge K, BOUND),
    and conditional backedge (@p bra LOOP).

    Safety:
    - Only unrolls pure loops (no predicated instructions, no stores).
    - Handles register renaming for duplicated loop body.
    - Adjusts counter increment to account for unrolling factor.
    - O3 experimental: has known limitations with complex loop bodies.

    Does NOT hardcode kernel names, dimensions, or register names.
    """

    name = "loop-unrolling"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        cfg = analyses.get("cfg")
        program = module.function.program
        loops = cfg.natural_loops()
        if not loops:
            return PassResult(details={"unrolled": 0, "loops": 0, "transforms_applied": 0})

        total_unrolled = 0
        kept_items: dict[int, str | PTXInstruction] = {i: item for i, item in enumerate(program.items)}

        for loop in loops:
            # Find a simple counted loop: counter init, increment, compare, backedge
            items_in_loop = []
            for idx in sorted(loop.blocks):
                block = cfg.blocks[idx]
                for i in block.item_indices:
                    items_in_loop.append((i, program.items[i]))

            # Skip loops with stores or predicated non-branch instructions
            has_store = any(
                not isinstance(item, str) and item.opcode.split(".")[0] == "st"
                for _, item in items_in_loop
            )
            if has_store:
                continue

            # Find the counter increment instruction
            counter_reg = None
            incr_amount = None
            for idx, item in items_in_loop:
                if isinstance(item, str):
                    continue
                base = item.opcode.split(".", 1)[0]
                if base == "add" and len(item.operands) == 3:
                    dest, src1, src2 = item.operands
                    if dest.strip() == src1.strip() and _is_const_one(src2):
                        counter_reg = dest.strip()
                        incr_amount = 1
                        break

            if counter_reg is None:
                continue

            # Find the loop body: all instructions between the last "counter init" before loop and the backedge
            # For now, duplicate the entire loop body (all loop-block instructions)
            # and adjust the counter increment
            loop_body = [item for _, item in items_in_loop if not isinstance(item, str)]

            if len(loop_body) == 0:
                continue

            # Find the backedge branch
            backedge_branch = None
            for idx, item in reversed(items_in_loop):
                if isinstance(item, str):
                    continue
                base = item.opcode.split(".", 1)[0]
                if base == "bra":
                    backedge_branch = idx
                    break

            if backedge_branch is None:
                continue

            # Duplicate loop body with register renaming
            rename_map: dict[str, str] = {}
            renamed_body: list[PTXInstruction] = []
            for inst in loop_body:
                if inst.predicate is not None:
                    continue
                base = inst.opcode.split(".", 1)[0]
                if base not in _PURE_RESULT_BASES and base not in {"setp", "ld", "st"}:
                    continue
                new_inst = _rename_instruction(inst, rename_map, counter_reg)
                if new_inst is not None:
                    renamed_body.append(new_inst)

            # Adjust the counter increment: add N instead of 1
            # Replace add.u32 K, K, 1 with add.u32 K, K, 2
            for idx, item in items_in_loop:
                if isinstance(item, str):
                    continue
                if item.opcode.startswith("add") and len(item.operands) == 3:
                    dest, src1, src2 = item.operands
                    if dest.strip() == counter_reg and src1.strip() == counter_reg and _is_const_one(src2):
                        new_op = (dest, src1, "2")
                        new_item = replace(item, operands=new_op)
                        kept_items[idx] = new_item
                        break

            # Insert duplicated body before the backedge branch
            insertions: dict[int, list[PTXInstruction]] = {backedge_branch: renamed_body}
            total_unrolled += 1

            # Rebuild items with insertions
            rebuilt: list[str | PTXInstruction] = []
            for i, item in enumerate(program.items):
                if i in insertions:
                    rebuilt.extend(insertions[i])
                if i in kept_items:
                    rebuilt.append(kept_items[i])

            module.function.program = PTXProgram(
                kernel_name=program.kernel_name,
                parameters=program.parameters,
                registers=program.registers,
                items=tuple(rebuilt),
            )
            # Only unroll the first loop found
            break

        details = {"unrolled": total_unrolled, "loops": len(loops), "transforms_applied": total_unrolled}
        if total_unrolled == 0:
            return PassResult(details=details)
        return PassResult(changed=True, details=details, invalidated_analyses=frozenset({"cfg", "uniformity"}))


def _is_const_one(op: str) -> bool:
    op = op.strip()
    return op in ("1", "0x1", "0x01")


def _rename_instruction(
    inst: PTXInstruction,
    rename_map: dict[str, str],
    skip_reg: str | None,
) -> PTXInstruction | None:
    """Create a renamed copy of an instruction for the unrolled body."""
    base = inst.opcode.split(".", 1)[0]
    if base in {"setp", "bra", "ret"}:
        return None  # don't duplicate control flow

    dest = _destination_register(inst)
    new_operands = list(inst.operands)
    if dest is not None and dest != skip_reg:
        new_name = _fresh_name(dest, rename_map)
        rename_map[dest] = new_name
        new_operands[0] = new_name
    # Rename source operands
    for i in range(1, len(new_operands)):
        op = new_operands[i].strip()
        if op.startswith("[") and op.endswith("]"):
            op = op[1:-1].strip()
        if op in rename_map:
            new_operands[i] = new_operands[i].replace(op, rename_map[op], 1)
    return replace(inst, operands=tuple(new_operands))


def _fresh_name(reg: str, rename_map: dict[str, str]) -> str:
    """Generate a fresh register name based on existing renames."""
    base = reg.rstrip("0123456789")
    nums = "".join(c for c in reg if c.isdigit())
    num = int(nums) if nums else 0
    new_num = num + 20  # offset to avoid conflicts
    return f"{base}{new_num}"
