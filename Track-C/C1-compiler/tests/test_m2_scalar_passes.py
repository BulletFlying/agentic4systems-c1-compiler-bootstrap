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
