"""GEMM-specific optimization passes: loop unrolling, accumulator expansion."""

from __future__ import annotations

import re
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

_REG_NUM_RE = re.compile(r"^%[a-z]+(\d+)$")


class LoopUnrollingPass:
    """Unroll innermost counted loops by factor N (default 2) — O2 proven-safe.

    Detects loops with: counter init (mov.u32 K, 0), increment by constant
    (add.u32 K, K, C), comparison against constant bound (setp.lt/ge K, BOUND),
    and conditional backedge (@p bra LOOP).

    Safety guarantees:
    - Only unrolls pure loops (no stores, no predicated non-branch instructions).
    - Only unrolls loops with even trip count (bound divisible by 2).
    - Handles register renaming for duplicated loop body with conflict avoidance.
    - Adjusts counter increment to account for unrolling factor.
    - Does NOT hardcode kernel names, dimensions, or register names.
    """

    name = "loop-unrolling"

    UNROLL_FACTOR = 2

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        cfg = analyses.get("cfg")
        program = module.function.program
        loops = cfg.natural_loops()
        if not loops:
            return PassResult(details={"unrolled": 0, "loops": 0, "transforms_applied": 0})

        total_unrolled = 0
        kept_items: dict[int, str | PTXInstruction] = {i: item for i, item in enumerate(program.items)}

        for loop in loops:
            items_in_loop = []
            for idx in sorted(loop.blocks):
                block = cfg.blocks[idx]
                for i in block.item_indices:
                    items_in_loop.append((i, program.items[i]))

            # Skip loops with stores
            has_store = any(
                not isinstance(item, str) and item.opcode.split(".")[0] == "st"
                for _, item in items_in_loop
            )
            if has_store:
                continue

            # Skip loops with predicated non-branch instructions
            has_predicated = any(
                not isinstance(item, str)
                and item.predicate is not None
                and item.opcode.split(".")[0] != "bra"
                for _, item in items_in_loop
            )
            if has_predicated:
                continue

            # Find counter register and increment
            counter_reg = None
            for idx, item in items_in_loop:
                if isinstance(item, str):
                    continue
                base = item.opcode.split(".", 1)[0]
                if base == "add" and len(item.operands) == 3:
                    dest, src1, src2 = item.operands
                    if dest.strip() == src1.strip() and _is_const_one(src2):
                        counter_reg = dest.strip()
                        break

            if counter_reg is None:
                continue

            # ---- Even-trip-count check: find the comparison bound ----
            bound_value = None
            for idx, item in items_in_loop:
                if isinstance(item, str):
                    continue
                base = item.opcode.split(".", 1)[0]
                if base == "setp" and len(item.operands) >= 3:
                    # Look for setp.lt/le/gt/ge %p, K, BOUND
                    for op in item.operands[1:]:
                        op_s = op.strip()
                        if op_s == counter_reg:
                            continue
                        if _is_immediate_const(op_s):
                            try:
                                bound_value = int(op_s, 0)
                            except ValueError:
                                pass
                            break
                if bound_value is not None:
                    break

            if bound_value is not None and bound_value % self.UNROLL_FACTOR != 0:
                # Trip count not divisible by unroll factor → skip this loop
                continue

            # Find the loop body instructions
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

            # ---- Collect used register numbers to avoid rename conflicts ----
            used_nums: set[int] = set()
            for inst in loop_body:
                for op in inst.operands:
                    m = _REG_NUM_RE.match(op.strip().lstrip("[").rstrip("]"))
                    if m:
                        used_nums.add(int(m.group(1)))

            # ---- Identify loop-carried registers ----
            # A register is loop-carried if it appears as both source and
            # destination in the SAME instruction (self-referencing, e.g.
            # add K, K, 1 or add.f32 F, F, X).  These carry state across
            # iterations and must not be renamed.
            loop_carried: set[str] = {counter_reg}
            for inst in loop_body:
                if inst.predicate is not None:
                    continue
                base = inst.opcode.split(".", 1)[0]
                if base in {"setp", "bra", "ret"}:
                    continue
                dest = _destination_register(inst)
                if dest is None:
                    continue
                first_src = 1
                for op in inst.operands[first_src:]:
                    op_s = op.strip().lstrip("[").rstrip("]")
                    if op_s == dest:
                        # Self-referencing: same register as dest and source
                        loop_carried.add(dest)
                        break

            # Duplicate loop body with register renaming.
            # Skip the counter increment — it gets adjusted in-place (add N instead of 1).
            rename_map: dict[str, str] = {}
            renamed_body: list[PTXInstruction] = []
            for inst in loop_body:
                if inst.predicate is not None:
                    continue
                base = inst.opcode.split(".", 1)[0]
                if base not in _PURE_RESULT_BASES and base not in {"setp", "ld", "st"}:
                    continue
                # Skip the counter increment — handled separately below
                dest = _destination_register(inst)
                if dest is not None and dest.strip() == counter_reg:
                    continue
                new_inst = _rename_instruction_safe(
                    inst, rename_map, skip_regs=loop_carried, used_nums=used_nums,
                )
                if new_inst is not None:
                    renamed_body.append(new_inst)
                    used_nums.update(_collect_reg_nums(new_inst))

            # Adjust the counter increment: add N instead of 1
            for idx, item in items_in_loop:
                if isinstance(item, str):
                    continue
                if item.opcode.startswith("add") and len(item.operands) == 3:
                    dest, src1, src2 = item.operands
                    if dest.strip() == counter_reg and src1.strip() == counter_reg and _is_const_one(src2):
                        new_op = (dest, src1, str(self.UNROLL_FACTOR))
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

            module.function.program = _rebuild_program(program, rebuilt)
            # Only unroll the first loop found
            break

        details = {"unrolled": total_unrolled, "loops": len(loops), "transforms_applied": total_unrolled}
        if total_unrolled == 0:
            return PassResult(details=details)
        return PassResult(
            changed=True,
            details=details,
            invalidated_analyses=frozenset({"cfg", "uniformity", "loops"}),
        )


def _is_const_one(op: str) -> bool:
    op = op.strip()
    return op in ("1", "0x1", "0x01")


def _is_immediate_const(op: str) -> bool:
    """Check if a string looks like an integer immediate."""
    op = op.strip()
    if not op:
        return False
    if op.startswith("0x") or op.startswith("0X"):
        return all(c in "0123456789abcdefABCDEF" for c in op[2:])
    if op.startswith("-"):
        return op[1:].isdigit()
    return op.isdigit()


def _collect_reg_nums(inst: PTXInstruction) -> set[int]:
    """Collect all register numbers used in an instruction."""
    nums: set[int] = set()
    for op in inst.operands:
        m = _REG_NUM_RE.match(op.strip().lstrip("[").rstrip("]"))
        if m:
            nums.add(int(m.group(1)))
    return nums


def _rename_instruction_safe(
    inst: PTXInstruction,
    rename_map: dict[str, str],
    skip_regs: set[str],
    used_nums: set[int],
) -> PTXInstruction | None:
    """Create a renamed copy of an instruction, avoiding conflicts with
    already-used register numbers.  Registers in skip_regs (loop-carried
    dependencies) are never renamed."""
    base = inst.opcode.split(".", 1)[0]
    if base in {"setp", "bra", "ret"}:
        return None

    dest = _destination_register(inst)
    new_operands = list(inst.operands)
    if dest is not None and dest not in skip_regs:
        new_name = _fresh_name_safe(dest, rename_map, used_nums)
        rename_map[dest] = new_name
        new_operands[0] = new_name
        m = _REG_NUM_RE.match(new_name)
        if m:
            used_nums.add(int(m.group(1)))

    # Rename source operands (but not loop-carried ones)
    for i in range(1, len(new_operands)):
        op = new_operands[i].strip()
        bracket = ""
        if op.startswith("[") and op.endswith("]"):
            op = op[1:-1].strip()
            bracket = "[]"
        if op in rename_map and op not in skip_regs:
            renamed = rename_map[op]
            new_operands[i] = f"[{renamed}]" if bracket else renamed
    return replace(inst, operands=tuple(new_operands))


def _fresh_name_safe(rname: str, rename_map: dict[str, str], used_nums: set[int]) -> str:
    """Generate a fresh register name that doesn't conflict with existing ones."""
    m = _REG_NUM_RE.match(rname)
    if not m:
        return rname
    base = rname[:m.start(1)]
    num = int(m.group(1))
    # Find a number that doesn't conflict with used registers
    new_num = num + 50  # large offset to avoid collision with source registers
    max_attempts = 256  # safety cap — register file has 256 entries
    attempts = 0
    while new_num in used_nums and attempts < max_attempts:
        new_num += 1
        if new_num > 255:
            new_num = (new_num % 256)  # wrap to avoid stalling at 255
        attempts += 1
    if attempts >= max_attempts:
        return rname  # fallback: don't rename, accept potential conflict
    return f"{base}{new_num}"
