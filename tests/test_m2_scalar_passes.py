"""Unit, negative, and mutation tests for M2 scalar optimization passes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aec_c1.analysis import build_default_analysis_manager
from aec_c1.ir import module_from_program
from aec_c1.passes.scalar import (
    BlockSimplificationPass,
    GlobalConstantPropagationPass,
    GlobalDeadCodeEliminationPass,
    LoopInvariantCodeMotionPass,
    RepeatedGlobalLoadReusePass,
)
from aec_c1.ptx import PTXInstruction, PTXProgram, Parameter, RegisterDecl, parse_ptx


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


def _run_pass(pass_instance, program: PTXProgram):
    module = module_from_program("<test>", program)
    analyses = build_default_analysis_manager(module)
    return pass_instance.run(module, analyses), module


def _i(opcode: str, *operands: str) -> PTXInstruction:
    return PTXInstruction(opcode=opcode, operands=operands)


# ---------------------------------------------------------------------------
# Global DCE tests
# ---------------------------------------------------------------------------


class TestGlobalDCE:
    def test_removes_unused_pure_computation(self) -> None:
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "42"),
            _i("add.u32", "%r2", "%r1", "1"),
            _i("ret"),
        ])
        result, module = _run_pass(GlobalDeadCodeEliminationPass(), prog)
        assert result.changed
        assert result.details["removed_instruction_count"] == 2

    def test_preserves_used_pure_computation(self) -> None:
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "42"),
            _i("st.global.u32", "[%rd1]", "%r1"),
            _i("ret"),
        ])
        result, module = _run_pass(GlobalDeadCodeEliminationPass(), prog)
        assert not result.changed or result.details["removed_instruction_count"] == 0

    def test_never_removes_side_effecting(self) -> None:
        prog = _make_simple_program([
            _i("ld.global.u32", "%r1", "[%rd1]"),
            _i("ret"),
        ])
        result, module = _run_pass(GlobalDeadCodeEliminationPass(), prog)
        assert not result.changed or result.details["removed_instruction_count"] == 0

    def test_never_removes_predicated(self) -> None:
        prog = _make_simple_program([
            PTXInstruction("add.u32", ("%r1", "%r2", "%r3"), predicate="%p1"),
            _i("ret"),
        ])
        result, module = _run_pass(GlobalDeadCodeEliminationPass(), prog)
        assert not result.changed or result.details["removed_instruction_count"] == 0

    def test_preserves_multi_def_register(self) -> None:
        """The loop counter %r3 is defined by both mov and add — both must be kept."""
        prog = _make_simple_program([
            _i("mov.u32", "%r3", "0"),
            "LOOP",
            _i("add.u32", "%r3", "%r3", "1"),
            _i("setp.lt.u32", "%p1", "%r3", "32"),
            _i("bra", "LOOP"),
            _i("ret"),
        ])
        result, module = _run_pass(GlobalDeadCodeEliminationPass(), prog)
        items = module.function.program.items
        mov_items = [i for i in items if isinstance(i, PTXInstruction) and "mov.u32" in str(i.opcode) and "%r3" in i.operands[0]]
        assert len(mov_items) == 1, "loop counter init must be preserved"

    def test_no_change_on_fully_live_program(self) -> None:
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "%tid.x"),
            _i("st.global.u32", "[%rd1]", "%r1"),
            _i("ret"),
        ])
        result, module = _run_pass(GlobalDeadCodeEliminationPass(), prog)
        assert not result.changed

    def test_preserves_predicate_destination(self) -> None:
        """mov.pred feeding a @%p branch must NOT be removed."""
        prog = _make_simple_program([
            _i("setp.eq.u32", "%p1", "%r1", "0"),
            _i("mov.pred", "%p2", "%p1"),
            _i("bra", "DONE"),
            PTXInstruction("bra", ("DONE",), predicate="%p2"),
            "DONE",
            _i("ret"),
        ])
        result, module = _run_pass(GlobalDeadCodeEliminationPass(), prog)
        items = module.function.program.items
        mov_pred_items = [
            i for i in items
            if isinstance(i, PTXInstruction) and "mov.pred" in i.opcode
        ]
        assert len(mov_pred_items) >= 1, "mov.pred must not be removed"

    def test_preserves_cc_modifier(self) -> None:
        """add.cc.u32 must NOT be removed (carry side effect)."""
        prog = _make_simple_program([
            _i("add.cc.u32", "%r1", "%r2", "%r3"),
            _i("ret"),
        ])
        result, module = _run_pass(GlobalDeadCodeEliminationPass(), prog)
        items = module.function.program.items
        add_cc_items = [
            i for i in items
            if isinstance(i, PTXInstruction) and ".cc" in i.opcode
        ]
        assert len(add_cc_items) >= 1, "add.cc must not be removed"


# ---------------------------------------------------------------------------
# Global Constant Propagation tests
# ---------------------------------------------------------------------------


class TestGlobalCP:
    def test_folds_simple_constant_chain(self) -> None:
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "10"),
            _i("add.u32", "%r2", "%r1", "5"),
            _i("st.global.u32", "[%rd1]", "%r2"),
            _i("ret"),
        ])
        result, module = _run_pass(GlobalConstantPropagationPass(), prog)
        assert result.changed

    def test_constant_folds_across_labels(self) -> None:
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "10"),
            "NEXT",
            _i("add.u32", "%r2", "%r1", "1"),
            _i("st.global.u32", "[%rd1]", "%r2"),
            _i("ret"),
        ])
        result, module = _run_pass(GlobalConstantPropagationPass(), prog)
        # r1=10 flows across label boundary within same block → add should fold
        assert result.changed

    def test_no_crash_on_loop_program(self) -> None:
        """Loop program should compile without crashing."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "0"),
            _i("mov.u32", "%r2", "1"),
            "LOOP",
            _i("setp.ge.u32", "%p1", "%r1", "128"),
            PTXInstruction("bra", ("DONE",), predicate="%p1"),
            _i("add.u32", "%r1", "%r1", "%r2"),
            _i("bra", "LOOP"),
            "DONE",
            _i("ret"),
        ])
        result, module = _run_pass(GlobalConstantPropagationPass(), prog)
        items = module.function.program.items
        assert any(isinstance(i, str) and i == "LOOP" for i in items)
        assert any(isinstance(i, str) and i == "DONE" for i in items)


# ---------------------------------------------------------------------------
# Block Simplification tests
# ---------------------------------------------------------------------------


class TestBlockSimplification:
    def test_no_change_on_simple_program(self) -> None:
        prog = _make_simple_program([
            _i("ret"),
        ])
        result, module = _run_pass(BlockSimplificationPass(), prog)
        assert not result.changed

    def test_no_crash_on_branch_program(self) -> None:
        prog = _make_simple_program([
            _i("setp.eq.u32", "%p1", "%r1", "0"),
            PTXInstruction("bra", ("DONE",), predicate="%p1"),
            _i("add.u32", "%r2", "%r1", "1"),
            "DONE",
            _i("ret"),
        ])
        result, module = _run_pass(BlockSimplificationPass(), prog)
        # Should not crash


# ---------------------------------------------------------------------------
# LICM tests
# ---------------------------------------------------------------------------


class TestLICM:
    def test_no_change_on_loop_free_program(self) -> None:
        prog = _make_simple_program([
            _i("add.u32", "%r1", "%r2", "%r3"),
            _i("ret"),
        ])
        result, module = _run_pass(LoopInvariantCodeMotionPass(), prog)
        assert result.details["loops_found"] == 0
        assert not result.changed

    def test_no_crash_on_simple_loop(self) -> None:
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "0"),
            _i("mov.u32", "%r2", "100"),
            "LOOP",
            _i("add.u32", "%r1", "%r1", "1"),
            _i("setp.lt.u32", "%p1", "%r1", "10"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("ret"),
        ])
        result, module = _run_pass(LoopInvariantCodeMotionPass(), prog)
        # At minimum should not crash

    def test_preserves_all_instructions(self) -> None:
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "0"),
            "LOOP",
            _i("ld.global.u32", "%r2", "[%rd1]"),
            _i("add.u32", "%r1", "%r1", "1"),
            _i("setp.lt.u32", "%p1", "%r1", "10"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("ret"),
        ])
        result, module = _run_pass(LoopInvariantCodeMotionPass(), prog)
        # ld.global must not be hoisted
        items = module.function.program.items
        all_opcodes = [i.opcode for i in items if isinstance(i, PTXInstruction)]
        assert "ld.global.u32" in all_opcodes


# ---------------------------------------------------------------------------
# Repeated Global Load Reuse tests (negative + positive)
# ---------------------------------------------------------------------------


class TestRepeatedGlobalLoadReuse:
    def test_reuses_same_addr_same_type_within_block(self) -> None:
        """Positive: second load from [%rd1] with same type should be replaced."""
        prog = _make_simple_program([
            _i("ld.global.f32", "%f1", "[%rd1]"),
            _i("ld.global.f32", "%f2", "[%rd1]"),
            _i("st.global.f32", "[%rd2]", "%f2"),
            _i("ret"),
        ])
        result, module = _run_pass(RepeatedGlobalLoadReusePass(), prog)
        assert result.changed
        assert result.details["replaced_load_count"] == 1

    def test_no_reuse_across_label_boundary(self) -> None:
        """Negative: label boundary clears cache — second load must be kept."""
        prog = _make_simple_program([
            _i("ld.global.f32", "%f1", "[%rd1]"),
            "MIDDLE",
            _i("ld.global.f32", "%f2", "[%rd1]"),
            _i("st.global.f32", "[%rd2]", "%f2"),
            _i("ret"),
        ])
        result, module = _run_pass(RepeatedGlobalLoadReusePass(), prog)
        # Cache cleared at label → second load not replaced
        assert not result.changed or result.details["replaced_load_count"] == 0

    def test_no_reuse_after_store(self) -> None:
        """Negative: store invalidates cache — subsequent load must be fresh."""
        prog = _make_simple_program([
            _i("ld.global.f32", "%f1", "[%rd1]"),
            _i("st.global.f32", "[%rd3]", "%f1"),
            _i("ld.global.f32", "%f2", "[%rd1]"),
            _i("st.global.f32", "[%rd2]", "%f2"),
            _i("ret"),
        ])
        result, module = _run_pass(RepeatedGlobalLoadReusePass(), prog)
        assert not result.changed or result.details["replaced_load_count"] == 0

    def test_no_reuse_after_predicated_instruction(self) -> None:
        """Negative: predicated instruction clears cache."""
        prog = _make_simple_program([
            _i("ld.global.f32", "%f1", "[%rd1]"),
            PTXInstruction("add.f32", ("%f3", "%f1", "%f2"), predicate="%p1"),
            _i("ld.global.f32", "%f2", "[%rd1]"),
            _i("st.global.f32", "[%rd2]", "%f2"),
            _i("ret"),
        ])
        result, module = _run_pass(RepeatedGlobalLoadReusePass(), prog)
        assert not result.changed or result.details["replaced_load_count"] == 0

    def test_no_reuse_after_addr_redefinition(self) -> None:
        """Negative: address register redefined between loads."""
        prog = _make_simple_program([
            _i("ld.global.f32", "%f1", "[%rd1]"),
            _i("add.u64", "%rd1", "%rd1", "%rd2"),
            _i("ld.global.f32", "%f2", "[%rd1]"),
            _i("st.global.f32", "[%rd2]", "%f2"),
            _i("ret"),
        ])
        result, module = _run_pass(RepeatedGlobalLoadReusePass(), prog)
        # add.u64 redefines %rd1 → cache entry for %rd1 removed → second load fresh
        assert not result.changed or result.details["replaced_load_count"] == 0

    def test_no_reuse_different_type_same_addr(self) -> None:
        """Negative: different load types from same address — not equivalent."""
        prog = _make_simple_program([
            _i("ld.global.f32", "%f1", "[%rd1]"),
            _i("ld.global.u32", "%r1", "[%rd1]"),
            _i("st.global.u32", "[%rd2]", "%r1"),
            _i("ret"),
        ])
        result, module = _run_pass(RepeatedGlobalLoadReusePass(), prog)
        # Different type → different cache key → not replaced
        assert not result.changed or result.details["replaced_load_count"] == 0

    def test_no_reuse_different_addr_register(self) -> None:
        """Negative: loads from different address registers — independent."""
        prog = _make_simple_program([
            _i("ld.global.f32", "%f1", "[%rd1]"),
            _i("ld.global.f32", "%f2", "[%rd2]"),
            _i("st.global.f32", "[%rd3]", "%f1"),
            _i("st.global.f32", "[%rd4]", "%f2"),
            _i("ret"),
        ])
        result, module = _run_pass(RepeatedGlobalLoadReusePass(), prog)
        # Different addr regs → different cache keys → both loads kept
        assert not result.changed or result.details["replaced_load_count"] == 0

    def test_no_reuse_after_branch(self) -> None:
        """Negative: branch clears cache."""
        prog = _make_simple_program([
            _i("ld.global.f32", "%f1", "[%rd1]"),
            _i("bra", "NEXT"),
            "NEXT",
            _i("ld.global.f32", "%f2", "[%rd1]"),
            _i("st.global.f32", "[%rd2]", "%f2"),
            _i("ret"),
        ])
        result, module = _run_pass(RepeatedGlobalLoadReusePass(), prog)
        assert not result.changed or result.details["replaced_load_count"] == 0

    def test_t3_pattern_reuse(self) -> None:
        """Positive: the T3 pattern — ld %f1 [%rd6], ld %f3 [%rd6] reused."""
        prog = _make_simple_program([
            _i("ld.global.f32", "%f1", "[%rd6]"),
            _i("ld.global.f32", "%f2", "[%rd7]"),
            _i("ld.global.f32", "%f3", "[%rd6]"),
            _i("ld.global.f32", "%f4", "[%rd8]"),
            _i("mul.f32", "%f5", "%f1", "%f2"),
            _i("mul.f32", "%f6", "%f3", "%f4"),
            _i("add.f32", "%f7", "%f5", "%f6"),
            _i("st.global.f32", "[%rd9]", "%f7"),
            _i("ret"),
        ])
        result, module = _run_pass(RepeatedGlobalLoadReusePass(), prog)
        # %f3 should be replaced by mov from %f1
        assert result.changed
        assert result.details["replaced_load_count"] == 1
        items = module.function.program.items
        mov_count = sum(
            1 for i in items
            if isinstance(i, PTXInstruction) and i.opcode == "mov.f32"
            and i.operands[1] == "%f1"
        )
        assert mov_count >= 1, "should have mov.f32 replacing reused load"


# ---------------------------------------------------------------------------
# Extended LICM tests (O2 proven-safe verification)
# ---------------------------------------------------------------------------


class TestLICMSafety:
    """Verify LICM safety invariants: domination, single-def, side-effect,
    predicated filtering, and semantic equivalence."""

    def test_licm_hoists_loop_invariant_add(self) -> None:
        """A pure add.u32 whose operands are loop-invariant should be hoisted."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "42"),
            _i("mov.u32", "%r2", "10"),
            "LOOP",
            _i("add.u32", "%r3", "%r1", "%r2"),
            _i("add.u32", "%r4", "%r4", "1"),
            _i("setp.lt.u32", "%p1", "%r4", "32"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("st.global.u32", "[%rd1]", "%r3"),
            _i("ret"),
        ])
        result, module = _run_pass(LoopInvariantCodeMotionPass(), prog)
        assert result.changed
        assert result.details["hoisted_count"] >= 1

        # The add.u32 %r3, %r1, %r2 should now appear before LOOP
        items = module.function.program.items
        loop_idx = next(i for i, it in enumerate(items) if isinstance(it, str) and it == "LOOP")
        before_loop = items[:loop_idx]
        add_before = [
            it for it in before_loop
            if isinstance(it, PTXInstruction) and "add.u32" in str(it.opcode)
            and "%r3" in it.operands[0]
        ]
        assert len(add_before) >= 1, "invariant add should be hoisted before loop"

    def test_licm_does_not_hoist_varying_operand(self) -> None:
        """An add whose operand is redefined in the loop must NOT be hoisted."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "0"),
            "LOOP",
            _i("add.u32", "%r1", "%r1", "1"),       # %r1 varies each iteration
            _i("add.u32", "%r2", "%r1", "100"),      # depends on varying %r1
            _i("setp.lt.u32", "%p1", "%r1", "32"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("st.global.u32", "[%rd1]", "%r2"),
            _i("ret"),
        ])
        result, module = _run_pass(LoopInvariantCodeMotionPass(), prog)
        # The add %r2, %r1, 100 depends on varying %r1 → must not hoist
        items = module.function.program.items
        loop_idx = next(i for i, it in enumerate(items) if isinstance(it, str) and it == "LOOP")
        before_loop = items[:loop_idx]
        adds_before = [
            it for it in before_loop
            if isinstance(it, PTXInstruction) and "add.u32" in str(it.opcode)
        ]
        # Only the invariant instructions (if any) should be before loop.
        # %r2's add depends on %r1 which is defined IN the loop and varies → not hoisted.
        add_r2_before = [
            it for it in adds_before
            if "%r2" in it.operands[0]
        ]
        assert len(add_r2_before) == 0, "varying-dependent add must not be hoisted"

    def test_licm_does_not_hoist_store(self) -> None:
        """Store instructions must never be hoisted (side-effecting)."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "0"),
            "LOOP",
            _i("st.global.u32", "[%rd1]", "%r1"),
            _i("add.u32", "%r1", "%r1", "1"),
            _i("setp.lt.u32", "%p1", "%r1", "10"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("ret"),
        ])
        result, module = _run_pass(LoopInvariantCodeMotionPass(), prog)
        # st.global must remain inside the loop
        items = module.function.program.items
        loop_idx = next(i for i, it in enumerate(items) if isinstance(it, str) and it == "LOOP")
        before_loop = items[:loop_idx]
        stores_before = [
            it for it in before_loop
            if isinstance(it, PTXInstruction) and "st." in str(it.opcode)
        ]
        assert len(stores_before) == 0, "store must not be hoisted"

    def test_licm_does_not_hoist_across_nondominating_def(self) -> None:
        """An operand defined outside the loop but not dominating the header
        must not be considered invariant."""
        # Build a program where a value is defined on one path to the loop
        # but not the other.
        prog = _make_simple_program([
            _i("setp.eq.u32", "%p0", "%rd0", "0"),
            PTXInstruction("bra", ("SKIP_INIT",), predicate="%p0"),
            _i("mov.u32", "%r10", "999"),           # def on one path only
            "SKIP_INIT",
            # %r10 may or may not be defined here (doesn't dominate loop header)
            _i("mov.u32", "%r1", "0"),
            "LOOP",
            _i("add.u32", "%r2", "%r10", "%r1"),    # uses potentially undefined %r10
            _i("add.u32", "%r1", "%r1", "1"),
            _i("setp.lt.u32", "%p1", "%r1", "10"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("st.global.u32", "[%rd1]", "%r2"),
            _i("ret"),
        ])
        result, module = _run_pass(LoopInvariantCodeMotionPass(), prog)
        # %r10 is defined outside the loop but its def block (after SKIP_INIT)
        # does NOT dominate the loop header LOOP because there's a path via
        # the predicated branch that skips it.
        # The add %r2, %r10, %r1 depends on %r10 which does not dominate LOOP
        # → must NOT be hoisted.
        items = module.function.program.items
        loop_idx = next(i for i, it in enumerate(items) if isinstance(it, str) and it == "LOOP")
        before_loop = items[:loop_idx]
        add_r2_before = [
            it for it in before_loop
            if isinstance(it, PTXInstruction) and "add.u32" in str(it.opcode)
            and "%r2" in it.operands[0]
        ]
        assert len(add_r2_before) == 0, (
            "add using non-dominating operand must not be hoisted"
        )

    def test_licm_preserves_predicated_instruction_in_loop(self) -> None:
        """Predicated instructions must never be hoisted."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "0"),
            _i("mov.u32", "%r5", "100"),
            "LOOP",
            _i("add.u32", "%r1", "%r1", "1"),
            PTXInstruction("add.u32", ("%r2", "%r5", "%r1"), predicate="%p0"),
            _i("setp.lt.u32", "%p1", "%r1", "10"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("ret"),
        ])
        result, module = _run_pass(LoopInvariantCodeMotionPass(), prog)
        # The predicated add must remain in the loop
        items = module.function.program.items
        loop_idx = next(i for i, it in enumerate(items) if isinstance(it, str) and it == "LOOP")
        before_loop = items[:loop_idx]
        predicated_before = [
            it for it in before_loop
            if isinstance(it, PTXInstruction) and it.predicate is not None
        ]
        assert len(predicated_before) == 0, "predicated instruction must not be hoisted"

    def test_licm_renamed_registers_still_hoist(self) -> None:
        """Register renaming should not affect hoisting behavior — if an
        invariant add is hoisted with one register naming, it should still
        be hoisted after renaming."""
        # Version A: original register names
        prog_a = _make_simple_program([
            _i("mov.u32", "%r10", "42"),
            _i("mov.u32", "%r11", "10"),
            "LOOP_A",
            _i("add.u32", "%r12", "%r10", "%r11"),
            _i("add.u32", "%r13", "%r13", "1"),
            _i("setp.lt.u32", "%p1", "%r13", "32"),
            PTXInstruction("bra", ("LOOP_A",), predicate="%p1"),
            _i("ret"),
        ])
        # Version B: same structure, renamed registers
        prog_b = _make_simple_program([
            _i("mov.u32", "%r20", "42"),
            _i("mov.u32", "%r21", "10"),
            "LOOP_B",
            _i("add.u32", "%r22", "%r20", "%r21"),
            _i("add.u32", "%r23", "%r23", "1"),
            _i("setp.lt.u32", "%p2", "%r23", "32"),
            PTXInstruction("bra", ("LOOP_B",), predicate="%p2"),
            _i("ret"),
        ])
        result_a, _ = _run_pass(LoopInvariantCodeMotionPass(), prog_a)
        result_b, _ = _run_pass(LoopInvariantCodeMotionPass(), prog_b)
        # Both should hoist the same number of instructions
        assert result_a.details["hoisted_count"] == result_b.details["hoisted_count"]


# ---------------------------------------------------------------------------
# Extended Block Simplification tests (O2 proven-safe verification)
# ---------------------------------------------------------------------------


class TestBlockSimplificationSafety:
    """Verify BlockSimplification safety: merge, unreachable removal,
    side-effect preservation, branch remapping, semantic equivalence."""

    def test_block_simplification_merges_single_jump_block(self) -> None:
        """A block containing only an unconditional branch should be merged."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "42"),
            _i("bra", "TARGET"),
            "SKIP",
            _i("bra", "TARGET"),
            "TARGET",
            _i("st.global.u32", "[%rd1]", "%r1"),
            _i("ret"),
        ])
        result, module = _run_pass(BlockSimplificationPass(), prog)
        assert result.changed
        # The SKIP label should be removed (its block is a jump-only block)
        items = module.function.program.items
        labels = [it for it in items if isinstance(it, str)]
        assert "SKIP" not in labels, "SKIP label should be removed"

    def test_block_simplification_removes_unreachable_block(self) -> None:
        """A block that is not reachable from entry and contains no
        side-effecting instructions should be removed."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "42"),
            _i("st.global.u32", "[%rd1]", "%r1"),
            _i("ret"),
            "DEAD",
            _i("add.u32", "%r2", "%r1", "1"),
            _i("mul.u32", "%r3", "%r2", "%r1"),
            _i("mov.u32", "%r4", "%r3"),
        ])
        result, module = _run_pass(BlockSimplificationPass(), prog)
        assert result.changed
        assert result.details["unreachable_blocks_removed"] >= 1
        items = module.function.program.items
        labels = [it for it in items if isinstance(it, str)]
        assert "DEAD" not in labels, "unreachable DEAD label should be removed"

    def test_block_simplification_preserves_side_effecting_block(self) -> None:
        """A block containing a store must not be merged or removed even if
        it could otherwise be simplified."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "42"),
            _i("bra", "NEXT"),
            "MIDDLE",
            _i("st.global.u32", "[%rd1]", "%r1"),    # side-effecting!
            _i("bra", "NEXT"),
            "NEXT",
            _i("ret"),
        ])
        result, module = _run_pass(BlockSimplificationPass(), prog)
        items = module.function.program.items
        labels = [it for it in items if isinstance(it, str)]
        # MIDDLE has side-effecting store → must be preserved
        assert "MIDDLE" in labels, "side-effecting block must be preserved"
        store_items = [
            it for it in items
            if isinstance(it, PTXInstruction) and "st." in str(it.opcode)
        ]
        assert len(store_items) >= 1, "store must not be removed"

    def test_block_simplification_branch_targets_remapped(self) -> None:
        """After removing a jump block, branch targets should be remapped
        to the final target."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "42"),
            _i("bra", "MIDDLE"),
            "MIDDLE",
            _i("bra", "FINAL"),
            "FINAL",
            _i("st.global.u32", "[%rd1]", "%r1"),
            _i("ret"),
        ])
        result, module = _run_pass(BlockSimplificationPass(), prog)
        assert result.changed
        items = module.function.program.items
        # Any bra should now target FINAL (not MIDDLE)
        bra_instructions = [
            it for it in items
            if isinstance(it, PTXInstruction)
            and it.opcode.split(".", 1)[0] == "bra"
            and it.predicate is None
        ]
        for bra in bra_instructions:
            assert bra.operands[0] != "MIDDLE", (
                f"branch should not target removed MIDDLE: {bra}"
            )

    def test_block_simplification_no_change_needed(self) -> None:
        """A minimal program with no simplification opportunities."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "42"),
            _i("st.global.u32", "[%rd1]", "%r1"),
            _i("ret"),
        ])
        result, module = _run_pass(BlockSimplificationPass(), prog)
        assert not result.changed

    def test_block_simplification_preserves_entry_block(self) -> None:
        """The entry block must never be removed, even if it appears empty."""
        prog = _make_simple_program([
            _i("ret"),
        ])
        result, module = _run_pass(BlockSimplificationPass(), prog)
        items = module.function.program.items
        # The ret instruction must still be present
        ret_items = [
            it for it in items
            if isinstance(it, PTXInstruction) and "ret" in str(it.opcode)
        ]
        assert len(ret_items) >= 1, "entry block ret must be preserved"


# ---------------------------------------------------------------------------
# Extended Global CP tests (O2 proven-safe verification)
# ---------------------------------------------------------------------------


class TestGlobalCPSafety:
    """Verify GlobalCP safety: join-point reset, memory isolation, convergence,
    and register-renaming invariance."""

    def test_globalcp_resets_at_join_point(self) -> None:
        """At a block with multiple predecessors, constants that differ on
        incoming paths must be reset (not propagated)."""
        prog = _make_simple_program([
            _i("setp.eq.u32", "%p0", "%rd0", "0"),
            PTXInstruction("bra", ("PATH_B",), predicate="%p0"),
            # PATH_A: %r1 = 10
            _i("mov.u32", "%r1", "10"),
            _i("bra", "JOIN"),
            # PATH_B: %r1 = 20
            "PATH_B",
            _i("mov.u32", "%r1", "20"),
            # JOIN: %r1 differs across paths → must NOT be propagated
            "JOIN",
            _i("add.u32", "%r2", "%r1", "5"),
            _i("st.global.u32", "[%rd1]", "%r2"),
            _i("ret"),
        ])
        result, module = _run_pass(GlobalConstantPropagationPass(), prog)
        # The add at JOIN should NOT be folded to an immediate because
        # %r1 has conflicting values from the two paths.
        items = module.function.program.items
        join_idx = next(i for i, it in enumerate(items) if isinstance(it, str) and it == "JOIN")
        after_join = items[join_idx:]
        add_insts = [
            it for it in after_join
            if isinstance(it, PTXInstruction) and "add.u32" in str(it.opcode)
            and "%r2" in it.operands[0]
        ]
        assert len(add_insts) >= 1
        # The add should still have register operands, not immediates
        add = add_insts[0]
        assert any(op.startswith("%") for op in add.operands[1:]), (
            "add at join should use register operands, not folded constants"
        )

    def test_globalcp_does_not_propagate_through_memory(self) -> None:
        """Constants must not be propagated through load/store operations."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "42"),
            _i("st.global.u32", "[%rd1]", "%r1"),     # store clobbers memory
            _i("ld.global.u32", "%r2", "[%rd1]"),      # load may return different value
            _i("add.u32", "%r3", "%r2", "1"),          # %r2 is NOT 42 after load
            _i("st.global.u32", "[%rd2]", "%r3"),
            _i("ret"),
        ])
        result, module = _run_pass(GlobalConstantPropagationPass(), prog)
        # The add should NOT have %r2 folded to 42 because ld.global
        # breaks the constant chain.
        items = module.function.program.items
        add_insts = [
            it for it in items
            if isinstance(it, PTXInstruction) and "add.u32" in str(it.opcode)
            and "%r3" in it.operands[0]
        ]
        assert len(add_insts) >= 1
        add = add_insts[0]
        # At least one source operand should still be a register
        has_register_source = any(
            op.strip().startswith("%") for op in add.operands[1:]
        )
        assert has_register_source, "add should not fold through memory barrier"

    def test_globalcp_loop_program_converges(self) -> None:
        """A loop program must converge in a finite number of dataflow
        iterations without crashing."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "0"),
            _i("mov.u32", "%r_step", "1"),
            "LOOP",
            _i("setp.ge.u32", "%p1", "%r1", "128"),
            PTXInstruction("bra", ("DONE",), predicate="%p1"),
            _i("add.u32", "%r1", "%r1", "%r_step"),
            _i("bra", "LOOP"),
            "DONE",
            _i("st.global.u32", "[%rd1]", "%r1"),
            _i("ret"),
        ])
        result, module = _run_pass(GlobalConstantPropagationPass(), prog)
        # Must converge — iteration count should be finite
        assert result.details["dataflow_iterations"] <= 20
        assert result.details["converged"] is True
        # Labels must be preserved
        items = module.function.program.items
        assert any(isinstance(it, str) and it == "LOOP" for it in items)
        assert any(isinstance(it, str) and it == "DONE" for it in items)

    def test_globalcp_renamed_registers_still_propagate(self) -> None:
        """Register renaming should not affect constant propagation behavior."""
        # Version A
        prog_a = _make_simple_program([
            _i("mov.u32", "%r10", "42"),
            _i("add.u32", "%r11", "%r10", "8"),
            _i("st.global.u32", "[%rd1]", "%r11"),
            _i("ret"),
        ])
        # Version B: renamed
        prog_b = _make_simple_program([
            _i("mov.u32", "%r20", "42"),
            _i("add.u32", "%r21", "%r20", "8"),
            _i("st.global.u32", "[%rd2]", "%r21"),
            _i("ret"),
        ])
        result_a, _ = _run_pass(GlobalConstantPropagationPass(), prog_a)
        result_b, _ = _run_pass(GlobalConstantPropagationPass(), prog_b)
        # Both should fold the same number of instructions
        assert result_a.details["folded_instruction_count"] == result_b.details["folded_instruction_count"]
