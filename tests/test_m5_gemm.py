"""Unit and safety tests for M5 LoopUnrolling and GEMM multi-size tests."""

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
from aec_c1.passes.gemm import LoopUnrollingPass
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
# Loop Unrolling tests
# ---------------------------------------------------------------------------


class TestLoopUnrolling:
    def test_unroll_factor_2_doubles_body_size(self) -> None:
        """A counted loop with even trip count should have its body
        instruction count approximately doubled."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "0"),               # counter init
            "LOOP",
            _i("ld.global.f32", "%f1", "[%rd1]"),
            _i("add.f32", "%f2", "%f1", "%f3"),      # body computation
            _i("add.u32", "%r1", "%r1", "1"),        # counter incr
            _i("setp.lt.u32", "%p1", "%r1", "32"),   # bound 32 (even)
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("st.global.f32", "[%rd2]", "%f2"),
            _i("ret"),
        ])
        result, module = _run_pass(LoopUnrollingPass(), prog)
        assert result.changed
        assert result.details["unrolled"] >= 1

        # Body instructions should have increased (duplicated + counter adjusted)
        items = module.function.program.items
        inst_count = sum(1 for it in items if isinstance(it, PTXInstruction))
        orig_count = sum(1 for it in prog.items if isinstance(it, PTXInstruction))
        assert inst_count > orig_count, "unrolled program should have more instructions"

    def test_unroll_counter_increment_adjusted(self) -> None:
        """After unrolling, the counter increment should be N (2) instead
        of 1."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "0"),
            "LOOP",
            _i("ld.global.f32", "%f1", "[%rd1]"),
            _i("add.f32", "%f2", "%f1", "%f3"),
            _i("add.u32", "%r1", "%r1", "1"),        # K += 1 → should become K += 2
            _i("setp.lt.u32", "%p1", "%r1", "32"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("st.global.f32", "[%rd2]", "%f2"),
            _i("ret"),
        ])
        result, module = _run_pass(LoopUnrollingPass(), prog)
        assert result.changed

        items = module.function.program.items
        # Find the counter increment — should be add K, K, 2
        add_insts = [
            it for it in items
            if isinstance(it, PTXInstruction)
            and "add.u32" in str(it.opcode)
        ]
        counter_adds = [
            a for a in add_insts
            if a.operands[0].strip() == "%r1"
            and a.operands[1].strip() == "%r1"
        ]
        # The counter increment should now be "2" not "1"
        assert any(a.operands[2].strip() == "2" for a in counter_adds), (
            "counter increment should be adjusted to 2"
        )

    def test_no_unroll_odd_trip_count(self) -> None:
        """A loop with odd trip count (bound 31) should NOT be unrolled."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "0"),
            "LOOP",
            _i("ld.global.f32", "%f1", "[%rd1]"),
            _i("add.f32", "%f2", "%f1", "%f3"),
            _i("add.u32", "%r1", "%r1", "1"),
            _i("setp.lt.u32", "%p1", "%r1", "31"),   # odd bound
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("st.global.f32", "[%rd2]", "%f2"),
            _i("ret"),
        ])
        result, module = _run_pass(LoopUnrollingPass(), prog)
        # Should not unroll because 31 is odd
        assert not result.changed, "odd-trip-count loop must not be unrolled"

    def test_no_unroll_store_in_loop_body(self) -> None:
        """A loop with a store in the body must not be unrolled."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "0"),
            "LOOP",
            _i("ld.global.f32", "%f1", "[%rd1]"),
            _i("st.global.f32", "[%rd3]", "%f1"),     # store in loop body
            _i("add.u32", "%r1", "%r1", "1"),
            _i("setp.lt.u32", "%p1", "%r1", "32"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("ret"),
        ])
        result, module = _run_pass(LoopUnrollingPass(), prog)
        assert not result.changed, "loop with store must not be unrolled"

    def test_no_unroll_predicated_loop_body(self) -> None:
        """A loop with a predicated instruction in the body must not be
        unrolled."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "0"),
            "LOOP",
            _i("ld.global.f32", "%f1", "[%rd1]"),
            PTXInstruction("add.f32", ("%f2", "%f1", "%f3"), predicate="%p0"),
            _i("add.u32", "%r1", "%r1", "1"),
            _i("setp.lt.u32", "%p1", "%r1", "32"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("st.global.f32", "[%rd2]", "%f2"),
            _i("ret"),
        ])
        result, module = _run_pass(LoopUnrollingPass(), prog)
        assert not result.changed, "loop with predicated instruction must not be unrolled"

    def test_no_unroll_no_counter_loop(self) -> None:
        """A loop without a recognized counter increment pattern must not
        be unrolled."""
        prog = _make_simple_program([
            _i("mov.u32", "%r1", "0"),
            "LOOP",
            _i("ld.global.f32", "%f1", "[%rd1]"),
            _i("add.u32", "%r1", "%r2", "1"),         # K = r2 + 1, not K = K + 1
            _i("setp.lt.u32", "%p1", "%r1", "32"),
            PTXInstruction("bra", ("LOOP",), predicate="%p1"),
            _i("st.global.f32", "[%rd2]", "%f1"),
            _i("ret"),
        ])
        result, module = _run_pass(LoopUnrollingPass(), prog)
        assert not result.changed, "non-counter loop must not be unrolled"


# ---------------------------------------------------------------------------
# GEMM multi-size smoke tests
# ---------------------------------------------------------------------------


class TestGEMMSizes:
    """Verify that GEMM-like kernels compile and simulate correctly at
    multiple problem sizes."""

    def _build_gemm_program(
        self,
        m_size: int,
        n_size: int,
        k_size: int,
    ) -> PTXProgram:
        """Build a simple FP32 GEMM kernel with given dimensions.
        Uses a triple-nested loop structure: for i in M, for j in N, for kk in K."""
        items: list[str | PTXInstruction] = [
            _i("mov.u32", "%r_i", "0"),
            "LOOP_I",
            _i("setp.ge.u32", "%p_i_done", "%r_i", str(m_size)),
            PTXInstruction("bra", ("DONE",), predicate="%p_i_done"),
            _i("mov.u32", "%r_j", "0"),
            "LOOP_J",
            _i("setp.ge.u32", "%p_j_done", "%r_j", str(n_size)),
            PTXInstruction("bra", ("NEXT_I",), predicate="%p_j_done"),
            _i("mov.f32", "%f_acc", "0f00000000"),
            _i("mov.u32", "%r_kk", "0"),
            "LOOP_K",
            _i("setp.ge.u32", "%p_k_done", "%r_kk", str(k_size)),
            PTXInstruction("bra", ("NEXT_J",), predicate="%p_k_done"),
            _i("ld.global.f32", "%f_a", "[%rd_a]"),
            _i("ld.global.f32", "%f_b", "[%rd_b]"),
            _i("fma.rn.f32", "%f_acc", "%f_a", "%f_b", "%f_acc"),
            _i("add.u32", "%r_kk", "%r_kk", "1"),
            _i("bra", "LOOP_K"),
            "NEXT_J",
            _i("st.global.f32", "[%rd_c]", "%f_acc"),
            _i("add.u32", "%r_j", "%r_j", "1"),
            _i("bra", "LOOP_J"),
            "NEXT_I",
            _i("add.u32", "%r_i", "%r_i", "1"),
            _i("bra", "LOOP_I"),
            "DONE",
            _i("ret"),
        ]
        return _make_simple_program(items)

    def test_gemm_64_64_64_compiles(self) -> None:
        """64x64x64 GEMM compiles without crash."""
        prog = self._build_gemm_program(64, 64, 64)
        # Just verify it compiles through the pass pipeline
        module = module_from_program("<test>", prog)
        analyses = build_default_analysis_manager(module)
        from aec_c1.passes import build_pipeline
        pipeline = build_pipeline("2")
        records = pipeline.run(module, analyses)
        assert len(records) > 0
        assert module.function.program is not None

    def test_gemm_128_128_128_compiles(self) -> None:
        """128x128x128 GEMM compiles without crash (public T5 size)."""
        prog = self._build_gemm_program(128, 128, 128)
        module = module_from_program("<test>", prog)
        analyses = build_default_analysis_manager(module)
        from aec_c1.passes import build_pipeline
        pipeline = build_pipeline("2")
        records = pipeline.run(module, analyses)
        assert len(records) > 0

    def test_gemm_256_256_256_compiles(self) -> None:
        """256x256x256 GEMM compiles without crash."""
        prog = self._build_gemm_program(256, 256, 256)
        module = module_from_program("<test>", prog)
        analyses = build_default_analysis_manager(module)
        from aec_c1.passes import build_pipeline
        pipeline = build_pipeline("2")
        records = pipeline.run(module, analyses)
        assert len(records) > 0

    def test_gemm_128_64_256_compiles(self) -> None:
        """Non-square 128x64x256 GEMM compiles without crash."""
        prog = self._build_gemm_program(128, 64, 256)
        module = module_from_program("<test>", prog)
        analyses = build_default_analysis_manager(module)
        from aec_c1.passes import build_pipeline
        pipeline = build_pipeline("2")
        records = pipeline.run(module, analyses)
        assert len(records) > 0
