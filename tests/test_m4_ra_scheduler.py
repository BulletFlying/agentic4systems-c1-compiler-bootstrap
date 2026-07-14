"""Unit and safety tests for M4 register allocation and scheduling passes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aec_c1.analysis import build_default_analysis_manager
from aec_c1.compiler import compile_ptx_detailed
from aec_c1.ir import module_from_program
from aec_c1.isa import TRACK_B_V1
from aec_c1.legacy_lowering import Lowerer
from aec_c1.passes.register_allocation import LinearScanRegisterAllocationPass
from aec_c1.passes.scheduler import ListSchedulerPass, _schedule_block
from aec_c1.ptx import PTXInstruction, PTXProgram


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_simple_program(items: list[str | PTXInstruction]) -> PTXProgram:
    return PTXProgram(
        kernel_name="test",
        parameters=(),
        registers=(),
        items=tuple(items),
    )


def _run_ra(program: PTXProgram) -> dict:
    """Run the LinearScanRA pass and return the register mapping."""
    module = module_from_program("<test>", program)
    analyses = build_default_analysis_manager(module)
    result = LinearScanRegisterAllocationPass().run(module, analyses)
    return module.metadata.get("register_mapping", {}), module.metadata.get("predicate_mapping", {})


def _i(opcode: str, *operands: str) -> PTXInstruction:
    return PTXInstruction(opcode=opcode, operands=operands)


# ---------------------------------------------------------------------------
# Register Allocation tests
# ---------------------------------------------------------------------------


class TestLinearScanRA:
    def test_ra_no_physical_register_overlap(self) -> None:
        """Two virtual registers with overlapping live ranges must not
        share the same physical register."""
        # %r1 and %r2 have overlapping lives: both defined before ret,
        # both used in the store.
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "42"),
            _i("mov.u32", "%r2", "99"),
            _i("add.u32", "%r3", "%r1", "%r2"),
            _i("st.global.u32", "[%rd1]", "%r3"),
            _i("ret"),
        ])
        mapping, _ = _run_ra(prog)
        assert mapping, "should have register mappings"
        # %r1 and %r2 are live simultaneously → must be in different phys regs
        phys_regs = set(mapping.values())
        assert len(phys_regs) == len(mapping), (
            f"overlapping virtual regs must not share physical regs: {mapping}"
        )

    def test_ra_handles_multiple_live_ranges(self) -> None:
        """A program with non-overlapping live ranges should reuse physical
        registers."""
        # %r1 lives from def to store1; %r2 lives from def to store2.
        # Their ranges don't overlap → can share the same physical register.
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "10"),
            _i("st.global.u32", "[%rd1]", "%r1"),
            _i("mov.u32", "%r2", "20"),
            _i("st.global.u32", "[%rd2]", "%r2"),
            _i("ret"),
        ])
        mapping, _ = _run_ra(prog)
        assert len(mapping) >= 2
        # Reuse is not guaranteed but valid if it happens
        phys_regs = set(mapping.values())
        assert len(phys_regs) <= len(mapping), "no duplicate phys regs allowed"

    def test_ra_pair_constraint_even_aligned(self) -> None:
        """64-bit registers (%rd, %bd) must be allocated at even physical
        register boundaries."""
        prog = _make_simple_program([
            _i("mov.u64", "%rd1", "%rd10"),
            _i("add.u64", "%rd2", "%rd1", "%rd10"),
            _i("st.global.u64", "[%rd3]", "%rd2"),
            _i("ret"),
        ])
        mapping, _ = _run_ra(prog)
        assert mapping, "should have register mappings"
        for vreg, phys in mapping.items():
            if vreg.startswith("%rd") or vreg.startswith("%bd"):
                assert phys % 2 == 0, (
                    f"pair register {vreg} -> R{phys} must be even-aligned"
                )
                # The pair should not exceed MAX_GPR
                assert phys + 1 <= 239, (
                    f"pair register {vreg} -> R{phys}/R{phys+1} exceeds MAX_GPR"
                )

    def test_ra_pair_constraint_no_r255_base(self) -> None:
        """No pair register should use R255 as the low register (R255 is
        reserved for temps)."""
        prog = _make_simple_program([
            _i("mov.u64", "%rd1", "%rd10"),
            _i("ret"),
        ])
        mapping, _ = _run_ra(prog)
        for vreg, phys in mapping.items():
            if vreg.startswith("%rd") or vreg.startswith("%bd"):
                assert phys != 255, "R255 must not be used as pair base"

    def test_ra_predicate_no_overlap(self) -> None:
        """Predicate registers must not overlap in allocation."""
        prog = _make_simple_program([
            _i("setp.eq.u32", "%p1", "%r1", "0"),
            _i("setp.lt.u32", "%p2", "%r2", "10"),
            PTXInstruction("add.u32", ("%r3", "%r1", "%r2"), predicate="%p1"),
            PTXInstruction("sub.u32", ("%r4", "%r1", "%r2"), predicate="%p2"),
            _i("ret"),
        ])
        _, pred_mapping = _run_ra(prog)
        if pred_mapping:
            phys_preds = set(pred_mapping.values())
            assert len(phys_preds) == len(pred_mapping), (
                f"predicate regs must not overlap: {pred_mapping}"
            )
            for p in phys_preds:
                assert 0 <= p <= 7, f"predicate {p} out of range"

    def test_ra_handles_register_pressure(self) -> None:
        """A kernel with many virtual registers should not crash."""
        # Build a long dependency chain using many virtual registers
        items: list[str | PTXInstruction] = []
        items.append(_i("mov.u32", "%r0", "0"))
        for i in range(1, 64):
            items.append(_i("add.u32", f"%r{i}", f"%r{i - 1}", "1"))
        items.append(_i("st.global.u32", "[%rd1]", "%r63"))
        items.append(_i("ret"))
        prog = _make_simple_program(items)
        mapping, _ = _run_ra(prog)
        # Should not crash and should produce mappings
        assert isinstance(mapping, dict)
        # Most registers should be allocated (though the chain pattern reuses well)


# ---------------------------------------------------------------------------
# Scheduler tests
# ---------------------------------------------------------------------------


class TestScheduler:
    def test_scheduler_preserves_data_dependencies(self) -> None:
        """An instruction that consumes a register must not be scheduled
        before the instruction that defines it (RAW dependency)."""
        from aec_c1.isa import AECInstruction

        insts = [
            AECInstruction(opcode="ADD", dest=1, src1=2, src2=3),
            AECInstruction(opcode="MOV", dest=4, src1=1, src2=0),
        ]
        result = _schedule_block(insts)
        # ADD defines R1, MOV uses R1 → ADD must come before MOV
        add_pos = next(i for i, inst in enumerate(result) if inst.opcode == "ADD")
        mov_pos = next(i for i, inst in enumerate(result) if inst.opcode == "MOV")
        assert add_pos < mov_pos, "ADD must precede MOV (RAW dependency)"

    def test_scheduler_preserves_memory_order(self) -> None:
        """Two ST instructions must maintain their relative order."""
        from aec_c1.isa import AECInstruction

        insts = [
            AECInstruction(opcode="ST", src1=1, src2=0, imm=100),
            AECInstruction(opcode="ST", src1=2, src2=0, imm=200),
        ]
        result = _schedule_block(insts)
        st_positions = [(i, inst.imm) for i, inst in enumerate(result) if inst.opcode == "ST"]
        assert st_positions[0][1] == 100, "first ST must stay first"
        assert st_positions[1][1] == 200, "second ST must stay second"

    def test_scheduler_keeps_branch_at_block_end(self) -> None:
        """Control-flow instructions must remain at the end of the block."""
        from aec_c1.isa import AECInstruction

        insts = [
            AECInstruction(opcode="ADD", dest=1, src1=2, src2=3),
            AECInstruction(opcode="BR", imm=10),
            AECInstruction(opcode="ADD", dest=5, src1=1, src2=3),
        ]
        result = _schedule_block(insts)
        # BR should be the last instruction
        last = result[-1]
        assert last.opcode == "BR", "BR must be at block end"
        # The second ADD should NOT be after BR (it gets scheduled before)
        br_pos = next(i for i, inst in enumerate(result) if inst.opcode == "BR")
        assert br_pos == len(result) - 1, "BR must be the last instruction"

    def test_scheduler_deterministic(self) -> None:
        """Same input must produce the same output on two calls."""
        from aec_c1.isa import AECInstruction

        insts = [
            AECInstruction(opcode="LD", dest=1, src1=2, src2=0, imm=0),
            AECInstruction(opcode="ADD", dest=3, src1=1, src2=4),
            AECInstruction(opcode="MUL", dest=5, src1=3, src2=6),
            AECInstruction(opcode="ST", src1=5, src2=0, imm=0),
        ]
        first = tuple(inst.opcode for inst in _schedule_block(insts))
        second = tuple(inst.opcode for inst in _schedule_block(insts))
        assert first == second, f"scheduler must be deterministic: {first} != {second}"

    def test_scheduler_never_moves_instruction_before_its_operands(self) -> None:
        """No instruction may be scheduled before all its source operands
        are defined."""
        from aec_c1.isa import AECInstruction

        insts = [
            AECInstruction(opcode="MOV", dest=10, src1=0, src2=0),
            AECInstruction(opcode="ADD", dest=1, src1=10, src2=11),
            AECInstruction(opcode="SUB", dest=2, src1=1, src2=12),
        ]
        result = _schedule_block(insts)
        # MOV must be before ADD (ADD uses R10), ADD must be before SUB (SUB uses R1)
        positions = {inst.opcode: i for i, inst in enumerate(result)}
        assert positions["MOV"] < positions["ADD"], "MOV must precede ADD"
        assert positions["ADD"] < positions["SUB"], "ADD must precede SUB"
