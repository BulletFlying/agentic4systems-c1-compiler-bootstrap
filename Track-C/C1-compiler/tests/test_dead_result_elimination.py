from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aec_c1.analysis import AnalysisManager
from aec_c1.compiler import compile_ptx_detailed
from aec_c1.ir import module_from_program
from aec_c1.passes import ConservativeDeadResultEliminationPass
from aec_c1.ptx import PTXInstruction, parse_ptx
from aec_c1.sim import TrackBSimulator, f32_to_bits


PTX02 = ROOT / "testcases" / "PTX-02_invariant_poly.ptx"
PASS_NAME = "conservative-dead-result-elimination"


def _pass_record(compilation):
    return next(record for record in compilation.report.passes if record.name == PASS_NAME)


def _run_pass(text: str):
    program = parse_ptx(text)
    module = module_from_program(text, program)
    result = ConservativeDeadResultEliminationPass().run(module, AnalysisManager(module, {}))
    return module.function.program, result


def _instructions(program):
    return [item for item in program.items if isinstance(item, PTXInstruction)]


def test_o2_and_o3_remove_ptx02_never_read_result_but_o0_is_unchanged() -> None:
    text = PTX02.read_text(encoding="utf-8")
    baseline = compile_ptx_detailed(text, opt_level="0")
    optimized_o2 = compile_ptx_detailed(text, opt_level="2")
    optimized_o3 = compile_ptx_detailed(text, opt_level="3")

    assert len(optimized_o2.lowered.instructions) == len(baseline.lowered.instructions) - 1
    assert len(optimized_o3.lowered.instructions) == len(baseline.lowered.instructions) - 1

    for optimized in (optimized_o2, optimized_o3):
        record = _pass_record(optimized)
        assert record.changed is True
        assert record.details["removed_instruction_count"] == 1
        assert record.details["removed_destinations"] == ["%f15"]
        assert record.details["transforms_applied"] == 1
        assert optimized.report.metrics["optimization_transforms_applied"] == 1
        assert optimized.report.metrics["machine_instruction_count"] == len(
            optimized.lowered.instructions
        )

    assert all(record.name != PASS_NAME for record in baseline.report.passes)
    assert baseline.report.metrics["optimization_transforms_applied"] == 0


def test_pass_keeps_duplicate_adds_for_future_local_cse() -> None:
    optimized_program, result = _run_pass(PTX02.read_text(encoding="utf-8"))
    instructions = _instructions(optimized_program)

    assert result.changed is True
    assert not any(item.operands and item.operands[0] == "%f15" for item in instructions)
    assert sum(
        item.opcode == "add.f32"
        and item.operands in {("%f5", "%f1", "%f2"), ("%f6", "%f1", "%f2")}
        for item in instructions
    ) == 2


def test_renamed_kernel_register_and_labels_still_optimize() -> None:
    original = PTX02.read_text(encoding="utf-8")
    renamed = (
        original.replace("invariant_poly", "renamed_poly")
        .replace("%f15", "%f14")
        .replace("LOOP", "RENAMED_LOOP")
        .replace("DONE", "RENAMED_DONE")
    )

    baseline = compile_ptx_detailed(renamed, opt_level="0")
    optimized = compile_ptx_detailed(renamed, opt_level="2")
    record = _pass_record(optimized)

    assert len(optimized.lowered.instructions) == len(baseline.lowered.instructions) - 1
    assert record.details["removed_destinations"] == ["%f14"]
    assert record.details["removed_instruction_count"] == 1


def test_memory_control_predicate_unknown_and_cc_operations_are_preserved() -> None:
    text = """
.visible .entry negative_case(
    .param .u64 output
)
{
    .reg .pred %p<3>;
    .reg .b32 %r<8>;
    .reg .b64 %rd<4>;

    ld.param.u64 %rd1, [output];
    mov.u32 %r1, 7;
    add.u64 %rd2, %rd1, 4;
    setp.ne.u32 %p1, %r1, 0;
    @%p1 add.u32 %r2, %r1, 1;
    mov.pred %p2, %p1;
    add.cc.u32 %r3, %r1, 1;
    ld.global.u32 %r4, [%rd2];
    st.global.u32 [%rd2], %r1;
    atom.global.add.u32 %r5, [%rd2], %r1;
    custom.u32 %r7, %r1;
    add.u32 %r6, %r1, 3;
    @%p1 bra EXIT;
    bar.sync 0;
EXIT:
    ret;
}
"""
    optimized_program, result = _run_pass(text)
    instructions = _instructions(optimized_program)
    opcodes = [item.opcode for item in instructions]

    assert result.details["removed_destinations"] == ["%r6"]
    assert result.details["removed_instruction_count"] == 1
    assert any(item.operands and item.operands[0] == "%rd2" for item in instructions)
    assert any(item.predicate == "p1" and item.opcode == "add.u32" for item in instructions)
    assert "mov.pred" in opcodes
    assert "add.cc.u32" in opcodes
    assert "ld.global.u32" in opcodes
    assert "st.global.u32" in opcodes
    assert "atom.global.add.u32" in opcodes
    assert "custom.u32" in opcodes
    assert "bra" in opcodes
    assert "bar.sync" in opcodes
    assert "ret" in opcodes
    assert not any(item.operands and item.operands[0] == "%r6" for item in instructions)


def test_o0_and_o2_are_locally_simulator_equivalent() -> None:
    text = PTX02.read_text(encoding="utf-8")
    baseline = compile_ptx_detailed(text, opt_level="0")
    optimized = compile_ptx_detailed(text, opt_level="2")
    block_dim = 32
    n = 17
    base_x = 0
    base_y = block_dim * 4
    initial_gmem = bytearray(block_dim * 8)

    for index in range(block_dim):
        _write_u32(initial_gmem, base_x + index * 4, f32_to_bits(index * 0.25 - 2.0))
        _write_u32(initial_gmem, base_y + index * 4, 0xDEADBEEF)

    baseline_result = _simulate(
        baseline,
        initial_gmem,
        base_x=base_x,
        base_y=base_y,
        n=n,
    )
    optimized_result = _simulate(
        optimized,
        initial_gmem,
        base_x=base_x,
        base_y=base_y,
        n=n,
    )

    assert optimized_result.gmem == baseline_result.gmem
    assert optimized_result.accesses == baseline_result.accesses
    assert optimized_result.non_uniform_branch_failures == 0
    assert baseline_result.non_uniform_branch_failures == 0
    assert optimized_result.dynamic_instruction_count < baseline_result.dynamic_instruction_count


def _simulate(compilation, initial_gmem: bytearray, *, base_x: int, base_y: int, n: int):
    lowered = compilation.lowered
    pmem = bytearray(28)
    _write_u64(pmem, lowered.parameter_offsets["param_x"], base_x)
    _write_u64(pmem, lowered.parameter_offsets["param_y"], base_y)
    _write_u32(pmem, lowered.parameter_offsets["param_n"], n)
    _write_u32(pmem, lowered.parameter_offsets["param_a"], f32_to_bits(1.25))
    _write_u32(pmem, lowered.parameter_offsets["param_b"], f32_to_bits(-0.75))
    return TrackBSimulator(
        lowered.instructions,
        pmem,
        bytearray(initial_gmem),
        block_dim=32,
        grid_dim=1,
    ).run()


def _write_u32(memory: bytearray, offset: int, value: int) -> None:
    memory[offset : offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")


def _write_u64(memory: bytearray, offset: int, value: int) -> None:
    memory[offset : offset + 8] = (value & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
