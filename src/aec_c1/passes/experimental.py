"""Repeated global load reuse pass (conservative, O2-safe).

O2-proven passes have been moved to dedicated modules:
  - global_cp.py     — GlobalConstantPropagationPass + _fold_with_constants
  - licm.py          — LoopInvariantCodeMotionPass
  - block_simplify.py — BlockSimplificationPass + _find_block_label
"""

from __future__ import annotations

from ..analysis import AnalysisManager
from ..ir import IRModule
from ..ptx import PTXInstruction
from ._helpers import (
    _destination_register,
    _rebuild_program,
)
from .base import PassResult


# ===========================================================================
# Repeated Global Load Reuse (conservative, O2-safe)
# ===========================================================================

class RepeatedGlobalLoadReusePass:
    """Eliminate repeated global loads from the same address within a scope.

    Operates on flat PTX source instructions with a conservative safety model:
    - Load cache cleared at every label (basic-block boundary).
    - Load cache cleared on any store, branch, call, or atomic (control/memory barrier).
    - Load cache cleared on any predicated instruction (control dependency).
    - Individual cache entries invalidated when the address register is redefined.
    - Only identical (address_register, load_type) pairs are reused.

    This model is intentionally conservative: any store invalidates ALL cached
    loads regardless of alias analysis. This is correct but may miss reuse
    opportunities across non-aliasing stores. Suitable for O2 scoring-critical use.
    """

    name = "repeated-global-load-reuse"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        del analyses
        program = module.function.program
        replaced_count = 0
        kept_items: list[str | PTXInstruction] = []
        load_cache: dict[tuple[str, str], str] = {}

        for item in program.items:
            if isinstance(item, str):
                load_cache.clear()
                kept_items.append(item)
                continue

            base = item.opcode.split(".", 1)[0]

            if base in {"st", "bra", "ret", "brx", "call", "atom"}:
                load_cache.clear()
                kept_items.append(item)
                continue

            if item.predicate is not None:
                load_cache.clear()
                kept_items.append(item)
                continue

            if base == "ld" and item.opcode.startswith("ld.global"):
                parts = item.opcode.split(".")
                if len(parts) < 3:
                    kept_items.append(item)
                    continue
                ptx_type = parts[-1]  # last segment is always the type
                dest = item.operands[0].strip()
                addr_operand = item.operands[1].strip()
                if addr_operand.startswith("[") and addr_operand.endswith("]"):
                    addr_reg = addr_operand[1:-1].strip()
                else:
                    addr_reg = addr_operand

                cache_key = (addr_reg, ptx_type)
                if cache_key in load_cache:
                    src = load_cache[cache_key]
                    new_inst = PTXInstruction(
                        opcode=f"mov.{ptx_type}", operands=(dest, src),
                    )
                    kept_items.append(new_inst)
                    replaced_count += 1
                else:
                    load_cache[cache_key] = dest
                    kept_items.append(item)
                continue

            dest = _destination_register(item)
            if dest is not None:
                stale_keys = [k for k in load_cache if k[0] == dest]
                for k in stale_keys:
                    del load_cache[k]

            kept_items.append(item)

        details = {
            "replaced_load_count": replaced_count,
            "transforms_applied": replaced_count,
        }
        if replaced_count == 0:
            return PassResult(details=details)

        module.function.program = _rebuild_program(program, kept_items)
        return PassResult(
            changed=True,
            details=details,
            invalidated_analyses=frozenset({"cfg", "uniformity"}),
        )
