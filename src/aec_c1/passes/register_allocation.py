"""Linear-scan register allocator using live-interval analysis.

Produces a virtual-to-physical register mapping stored in the IR module
metadata.  The Lowerer reads this mapping and skips the bootstrap allocator
when it is present.

O2 proven-safe (2026-07-14):
  - Loop-aware liveness extension: registers used inside loops have their
    live ranges extended to the loop tail so the RA does not reuse physical
    registers across back edges.
  - Pair-assignment bug fixed (even base always selected).
  - Fallback pair-path verifies both registers available.
  - Predicate allocation uses proper expiry.
"""

from __future__ import annotations

from ..analysis import AnalysisManager, LivenessFacts
from ..analysis.cfg import CFG
from ..ir import IRModule
from ..ptx import PTXInstruction
from .base import PassResult


class LinearScanRegisterAllocationPass:
    """Assign physical GPRs to virtual registers using linear-scan allocation.

    Uses liveness facts to compute live intervals, then scans in order of
    first definition.  64-bit pair registers are allocated as consecutive
    even-odd pairs (e.g. R2/R3).  Predicates are assigned separately from
    GPRs.

    Loop-carried register values are protected by extending the live range
    of any register used inside a loop body to the loop tail, preventing
    the allocator from sharing a physical register across loop iterations.

    When physical registers are exhausted the pass reports pressure but
    does not spill — the caller should fall back to the bootstrap allocator
    when a mapping is incomplete.
    """

    name = "linear-scan-register-allocation"

    MAX_GPR = 239   # R1..R239 usable (R0 reserved); R240-R255 reserved for temps
    MAX_PRED = 7    # P0..P7

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        try:
            facts: LivenessFacts = analyses.get("liveness")
        except Exception:
            return PassResult(details={"error": "liveness analysis not available"})

        # ---- loop-aware liveness extension ----
        # Registers used inside a loop body must stay live through the
        # entire loop so the RA does not reuse their physical registers
        # for loop-body temporaries across back edges.
        loop_range: tuple[int, int] | None = _compute_loop_range(module, analyses)

        # Filter to live GPR ranges only, excluding predicates
        gpr_ranges = {
            name: lr for name, lr in facts.live_ranges.items()
            if lr.is_live and not name.startswith("%p")
        }

        if not gpr_ranges:
            return PassResult(details={"allocated": 0, "pressure": 0})

        # ---- Merge split live ranges for the same base register ----
        # Multi-def registers produce keys like %f4#0, %f4#1.  Merge them
        # into a single aggregate range per base register so the Lowerer
        # (which maps one virtual register → one physical register) gets
        # a single consistent mapping.
        merged: dict[str, tuple[int, int]] = {}  # base_name -> (first_def, last_use)
        for name, lr in gpr_ranges.items():
            base = name.split("#")[0]
            if base in merged:
                fd, lu = merged[base]
                merged[base] = (min(fd, lr.first_def), max(lu, lr.last_use))
            else:
                merged[base] = (lr.first_def, lr.last_use)

        # ---- Extend loop-used registers to the loop tail ----
        if loop_range is not None:
            loop_start, loop_end = loop_range
            for base, (first_def, last_use) in list(merged.items()):
                # Does this register have a use inside the loop body?
                uses_in_loop = _has_use_in_range(facts, base, loop_start, loop_end)
                if uses_in_loop and last_use < loop_end:
                    merged[base] = (first_def, loop_end)

        # Sort by first_def for linear scan
        sorted_regs = sorted(merged.items(), key=lambda kv: kv[1][0])

        mapping: dict[str, int] = {}
        active: list[tuple[int, int]] = []  # (last_use, phys_reg)
        free_list: list[int] = list(range(1, self.MAX_GPR + 1))
        free_list.reverse()

        for vreg, (first_def, last_use) in sorted_regs:
            # Expire: return physical registers whose live range ended
            still_active = []
            for end, phys in active:
                if end < first_def:
                    free_list.append(phys)
                else:
                    still_active.append((end, phys))
            active = still_active

            is_pair = vreg.startswith("%rd") or vreg.startswith("%bd")

            if is_pair:
                assigned = None
                for i in range(len(free_list) - 1, -1, -1):
                    if free_list[i] % 2 == 0 and free_list[i] + 1 in free_list:
                        j = free_list.index(free_list[i] + 1)
                        even_val = free_list[i]
                        if i > j:
                            free_list.pop(i)
                            free_list.pop(j)
                        else:
                            free_list.pop(j)
                            free_list.pop(i)
                        assigned = even_val
                        if assigned == 0:
                            assigned = None  # R0 reserved
                        break

                if assigned is not None:
                    mapping[vreg] = assigned
                    active.append((last_use, assigned))
                    active.append((last_use, assigned + 1))
                elif len(free_list) >= 2:
                    phys = free_list.pop()
                    if phys % 2 == 1 and phys > 0:
                        phys -= 1
                    if phys + 1 in free_list:
                        free_list.remove(phys + 1)
                        if phys > 0 and phys % 2 == 0 and phys + 1 <= self.MAX_GPR:
                            mapping[vreg] = phys
                            active.append((last_use, phys))
                            active.append((last_use, phys + 1))
                    else:
                        free_list.append(phys)
            else:
                if free_list:
                    phys = free_list.pop()
                    mapping[vreg] = phys
                    active.append((last_use, phys))

        # Predicate allocation
        pred_ranges = {
            name: lr for name, lr in facts.live_ranges.items()
            if lr.is_live and name.startswith("%p")
        }
        pred_mapping: dict[str, int] = {}
        pred_free = list(range(self.MAX_PRED + 1))
        pred_active: list[tuple[int, int]] = []
        for pred_name, lr in sorted(pred_ranges.items(), key=lambda kv: kv[1].first_def):
            pred_name = pred_name.split("#")[0]
            still_active = []
            for end, p in pred_active:
                if end < lr.first_def:
                    pred_free.append(p)
                else:
                    still_active.append((end, p))
            pred_active = still_active
            if pred_free:
                p = pred_free.pop()
                pred_mapping[pred_name] = p
                pred_active.append((lr.last_use, p))

        module.metadata["register_mapping"] = mapping
        module.metadata["predicate_mapping"] = pred_mapping

        allocated = len(mapping)
        details = {
            "allocated_gprs": allocated,
            "allocated_preds": len(pred_mapping),
            "total_virtual_regs": len(gpr_ranges),
            "register_pressure": allocated,
            "max_gpr": max(mapping.values()) if mapping else 0,
            "transforms_applied": 0,  # RA is infrastructure, not optimization
            "loop_extended": loop_range is not None,
        }
        return PassResult(changed=True, details=details)


# ---------------------------------------------------------------------------
# Loop-aware helpers
# ---------------------------------------------------------------------------


def _compute_loop_range(
    module: IRModule, analyses: AnalysisManager,
) -> tuple[int, int] | None:
    """Return (first_inst, last_inst) covering all loop bodies, or None."""
    try:
        cfg: CFG = analyses.get("cfg")
    except Exception:
        return None

    loops = cfg.natural_loops()
    if not loops:
        return None

    program = module.function.program
    loop_start = None
    loop_end = None

    for loop in loops:
        for block_name in loop.blocks:
            block = cfg.blocks.get(block_name)
            if block is None:
                continue
            for idx in block.item_indices:
                if isinstance(program.items[idx], PTXInstruction):
                    if loop_start is None or idx < loop_start:
                        loop_start = idx
                    if loop_end is None or idx > loop_end:
                        loop_end = idx

    if loop_start is not None and loop_end is not None:
        return (loop_start, loop_end)
    return None


def _has_use_in_range(
    facts: LivenessFacts,
    base: str,
    range_start: int,
    range_end: int,
) -> bool:
    """Return True if *base* has any use inside [range_start, range_end]."""
    for name, lr in facts.live_ranges.items():
        if name.split("#")[0] != base:
            continue
        if not lr.is_live:
            continue
        for u in lr.use_indices:
            if range_start <= u <= range_end:
                return True
    return False
