"""Unit, negative, and mutation tests for M3 memory optimization passes."""

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
from aec_c1.passes.memory import LoadHoistingPass
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


def _run_pass(pass_instance, program: PTXProgram):
    module = module_from_program("<test>", program)
    analyses = build_default_analysis_manager(module)
    return pass_instance.run(module, analyses), module


def _i(opcode: str, *operands: str) -> PTXInstruction:
    return PTXInstruction(opcode=opcode, operands=operands)


# ---------------------------------------------------------------------------
# Load Hoisting tests (O2 proven-safe verification)
# ---------------------------------------------------------------------------


class TestLoadHoisting:
    def test_hoist_loop_invariant_global_load(self) -> None:
        """A ld.global.f32 with invariant address in a store-free loop
        should be hoisted to the preheader."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "%rd0"),
            _i("mov.u32", "%r2", "0"),
            "LOOP",
            _i("ld.global.f32", "%f1", "[%r1]"),
            _i("add.u32", "%r2", "%r2", "1"),
            _i("setp.lt.u32", "%p1", "%r2", "32"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("st.global.f32", "[%rd2]", "%f1"),
            _i("ret"),
        ])
        result, module = _run_pass(LoadHoistingPass(), prog)
        assert result.changed
        assert result.details["hoisted"] >= 1

        items = module.function.program.items
        loop_idx = next(i for i, it in enumerate(items)
                        if isinstance(it, str) and it == "LOOP")
        before_loop = items[:loop_idx]
        loads_before = [
            it for it in before_loop
            if isinstance(it, PTXInstruction) and "ld.global" in str(it.opcode)
        ]
        assert len(loads_before) >= 1, "invariant load should be hoisted before loop"

    def test_no_hoist_varying_address(self) -> None:
        """A load whose address register is modified in the loop must NOT
        be hoisted."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "%rd0"),
            _i("mov.u32", "%r2", "0"),
            "LOOP",
            _i("ld.global.f32", "%f1", "[%r1]"),
            _i("add.u32", "%r1", "%r1", "4"),   # address varies
            _i("add.u32", "%r2", "%r2", "1"),
            _i("setp.lt.u32", "%p1", "%r2", "32"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("st.global.f32", "[%rd2]", "%f1"),
            _i("ret"),
        ])
        result, module = _run_pass(LoadHoistingPass(), prog)
        items = module.function.program.items
        loop_idx = next(i for i, it in enumerate(items)
                        if isinstance(it, str) and it == "LOOP")
        before_loop = items[:loop_idx]
        loads_before = [
            it for it in before_loop
            if isinstance(it, PTXInstruction) and "ld.global" in str(it.opcode)
        ]
        assert len(loads_before) == 0, "varying-address load must not be hoisted"

    def test_no_hoist_store_in_loop_body(self) -> None:
        """A store anywhere in the loop body disables all load hoisting
        for that loop (conservative alias model)."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "%rd0"),
            _i("mov.u32", "%r2", "0"),
            "LOOP",
            _i("ld.global.f32", "%f1", "[%r1]"),
            _i("st.global.f32", "[%rd3]", "%f1"),        # store in loop
            _i("add.u32", "%r2", "%r2", "1"),
            _i("setp.lt.u32", "%p1", "%r2", "32"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("ret"),
        ])
        result, module = _run_pass(LoadHoistingPass(), prog)
        assert not result.changed or result.details["hoisted"] == 0
        items = module.function.program.items
        loop_idx = next(i for i, it in enumerate(items)
                        if isinstance(it, str) and it == "LOOP")
        before_loop = items[:loop_idx]
        loads_before = [
            it for it in before_loop
            if isinstance(it, PTXInstruction) and "ld.global" in str(it.opcode)
        ]
        assert len(loads_before) == 0, "load must not be hoisted when store in loop"

    def test_no_hoist_predicated_load(self) -> None:
        """A predicated load must never be hoisted."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "%rd0"),
            _i("mov.u32", "%r2", "0"),
            "LOOP",
            _i("setp.eq.u32", "%p2", "%r2", "16"),
            PTXInstruction("ld.global.f32", ("%f1", "[%r1]"), predicate="%p2"),
            _i("add.u32", "%r2", "%r2", "1"),
            _i("setp.lt.u32", "%p1", "%r2", "32"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("st.global.f32", "[%rd2]", "%f1"),
            _i("ret"),
        ])
        result, module = _run_pass(LoadHoistingPass(), prog)
        items = module.function.program.items
        loop_idx = next(i for i, it in enumerate(items)
                        if isinstance(it, str) and it == "LOOP")
        before_loop = items[:loop_idx]
        loads_before = [
            it for it in before_loop
            if isinstance(it, PTXInstruction) and "ld.global" in str(it.opcode)
        ]
        assert len(loads_before) == 0, "predicated load must not be hoisted"

    def test_no_hoist_conditional_load(self) -> None:
        """A load inside a conditional branch (not dominating the latch)
        must not be hoisted."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "%rd0"),
            _i("mov.u32", "%r2", "0"),
            "LOOP",
            _i("setp.eq.u32", "%p2", "%r2", "0"),
            PTXInstruction("bra", ("SKIP_LOAD",), predicate="%p2"),
            "LOAD_PATH",
            _i("ld.global.f32", "%f1", "[%r1]"),
            "SKIP_LOAD",
            _i("add.u32", "%r2", "%r2", "1"),
            _i("setp.lt.u32", "%p1", "%r2", "32"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("st.global.f32", "[%rd2]", "%f1"),
            _i("ret"),
        ])
        result, module = _run_pass(LoadHoistingPass(), prog)
        items = module.function.program.items
        loop_idx = next(i for i, it in enumerate(items)
                        if isinstance(it, str) and it == "LOOP")
        before_loop = items[:loop_idx]
        loads_before = [
            it for it in before_loop
            if isinstance(it, PTXInstruction) and "ld.global" in str(it.opcode)
        ]
        assert len(loads_before) == 0, "conditional load must not be hoisted"

    def test_no_hoist_without_preheader(self) -> None:
        """A loop with multiple entries (no unique preheader) must not
        have loads hoisted."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "%rd0"),
            _i("mov.u32", "%r2", "0"),
            _i("bra", "LOOP_ENTRY"),
            "ALT_ENTRY",
            _i("mov.u32", "%r1", "0"),
            "LOOP_ENTRY",
            _i("ld.global.f32", "%f1", "[%r1]"),
            _i("add.u32", "%r2", "%r2", "1"),
            _i("setp.lt.u32", "%p1", "%r2", "32"),
            PTXInstruction("bra", ("LOOP_ENTRY",), predicate="%p1"),
            _i("st.global.f32", "[%rd2]", "%f1"),
            _i("ret"),
        ])
        result, module = _run_pass(LoadHoistingPass(), prog)
        items = module.function.program.items
        loop_idx = next(i for i, it in enumerate(items)
                        if isinstance(it, str) and it == "LOOP_ENTRY")
        before_loop = items[:loop_idx]
        loads_before = [
            it for it in before_loop
            if isinstance(it, PTXInstruction) and "ld.global" in str(it.opcode)
        ]
        assert len(loads_before) == 0, "load must not be hoisted without unique preheader"

    def test_hoist_single_def_load_only(self) -> None:
        """A load whose destination register is redefined in the loop
        must not be hoisted."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "%rd0"),
            _i("mov.u32", "%r2", "0"),
            "LOOP",
            _i("ld.global.f32", "%f1", "[%r1]"),
            _i("add.f32", "%f1", "%f1", "%f3"),        # redefines %f1
            _i("add.u32", "%r2", "%r2", "1"),
            _i("setp.lt.u32", "%p1", "%r2", "32"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("st.global.f32", "[%rd2]", "%f1"),
            _i("ret"),
        ])
        result, module = _run_pass(LoadHoistingPass(), prog)
        items = module.function.program.items
        loop_idx = next(i for i, it in enumerate(items)
                        if isinstance(it, str) and it == "LOOP")
        before_loop = items[:loop_idx]
        loads_before = [
            it for it in before_loop
            if isinstance(it, PTXInstruction) and "ld.global" in str(it.opcode)
        ]
        assert len(loads_before) == 0, "load with redefined dest must not be hoisted"

    def test_no_hoist_non_global_load(self) -> None:
        """Only ld.global loads are hoisted; other load types are ignored."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "%rd0"),
            _i("mov.u32", "%r2", "0"),
            "LOOP",
            _i("ld.shared.f32", "%f1", "[%r1]"),
            _i("add.u32", "%r2", "%r2", "1"),
            _i("setp.lt.u32", "%p1", "%r2", "32"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("st.global.f32", "[%rd2]", "%f1"),
            _i("ret"),
        ])
        result, module = _run_pass(LoadHoistingPass(), prog)
        items = module.function.program.items
        loop_idx = next(i for i, it in enumerate(items)
                        if isinstance(it, str) and it == "LOOP")
        before_loop = items[:loop_idx]
        loads_before = [
            it for it in before_loop
            if isinstance(it, PTXInstruction) and "ld." in str(it.opcode)
        ]
        assert len(loads_before) == 0, "non-global load must not be hoisted"
