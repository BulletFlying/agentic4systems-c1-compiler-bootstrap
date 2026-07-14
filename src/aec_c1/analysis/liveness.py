"""Liveness analysis for virtual registers in PTX programs.

Computes live ranges per virtual register definition.  Registers with
multiple definitions (e.g. loop counters) are split into separate live
ranges so the register allocator can reuse physical registers correctly.
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
    live_in: dict[int, frozenset[str]] = field(default_factory=dict)
    live_out: dict[int, frozenset[str]] = field(default_factory=dict)


def analyze_liveness(program: PTXProgram) -> LivenessFacts:
    """Compute live ranges for all virtual registers.

    Registers with multiple definitions (e.g. loop counters) are split into
    separate live ranges per definition: %r3#0 covers the first definition
    to its last use before the next definition; %r3#1 covers the second
    definition to its last use; and so on.  This prevents the register
    allocator from treating multi-def registers as one monolithic live
    range that overlaps everything.
    """
    ranges: dict[str, LiveRange] = {}
    inst_indices: list[int] = []

    for i, item in enumerate(program.items):
        if isinstance(item, str):
            continue
        inst_indices.append(i)

    # Collect all definitions and uses per register
    all_defs: dict[str, list[int]] = {}
    all_uses: dict[str, list[int]] = {}

    for i in inst_indices:
        item = program.items[i]
        assert isinstance(item, PTXInstruction)

        dest = _dest_register(item)
        if dest is not None:
            all_defs.setdefault(dest, []).append(i)

        for src in _source_registers(item):
            all_uses.setdefault(src, []).append(i)

    # Build per-definition live ranges.
    #
    # When an instruction both reads and writes the same register
    # (e.g.  add.f32 %f1, %f1, %f4) the read logically precedes the
    # write and belongs to the *previous* definition's live range.
    # We therefore use an inclusive upper bound for the old range
    # (u <= next_def) and an exclusive lower bound for the new range
    # (u > def_idx).
    for reg_name, def_indices in all_defs.items():
        uses = sorted(all_uses.get(reg_name, []))
        for def_num, def_idx in enumerate(def_indices):
            next_def = (
                def_indices[def_num + 1]
                if def_num + 1 < len(def_indices)
                else max(inst_indices) + 1
            )
            last_use = -1
            use_indices: list[int] = []
            if def_num == 0:
                # First definition: include uses up to and including the
                # next definition (captures RMW reads at the re-def site).
                for u in uses:
                    if def_idx <= u <= next_def:
                        use_indices.append(u)
                        last_use = max(last_use, u)
            else:
                # Subsequent definition: the use at def_idx itself reads
                # the *previous* value, so exclude it from this range.
                for u in uses:
                    if def_idx < u < next_def:
                        use_indices.append(u)
                        last_use = max(last_use, u)
            if last_use < 0:
                last_use = def_idx
            key = f"{reg_name}#{def_num}" if len(def_indices) > 1 else reg_name
            ranges[key] = LiveRange(
                register=key,
                first_def=def_idx,
                last_use=last_use,
                definition_indices=[def_idx],
                use_indices=use_indices,
            )

    # Also capture registers that are only used (parameters, special regs)
    for reg_name, use_indices in all_uses.items():
        if reg_name not in all_defs:
            key = reg_name
            if key not in ranges:
                ranges[key] = LiveRange(
                    register=key,
                    first_def=-1,
                    last_use=max(use_indices),
                    use_indices=sorted(use_indices),
                )

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
        predicate = inst.predicate.strip()
        regs.append(predicate if predicate.startswith("%") else f"%{predicate}")

    base = inst.opcode.split(".", 1)[0]
    first_src = 1 if base in {"ld", "mov", "add", "sub", "mul", "mad", "and", "or", "xor", "shl", "shr", "cvt", "fma", "setp"} and inst.operands else 0

    for op in inst.operands[first_src:]:
        op = op.strip()
        if op.startswith("[") and op.endswith("]"):
            op = op[1:-1].strip()
        if op.startswith("%"):
            regs.append(op)
    return regs
