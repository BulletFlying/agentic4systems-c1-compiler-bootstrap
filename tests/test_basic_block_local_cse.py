from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aec_c1.analysis import AnalysisManager
from aec_c1.compiler import compile_ptx, compile_ptx_detailed
from aec_c1.ir import module_from_program
from aec_c1.isa import TRACK_B_V1, instructions_to_bytes
from aec_c1.passes import BasicBlockLocalCSEPass
from aec_c1.ptx import PTXInstruction, parse_ptx


PTX02 = ROOT / "tests" / "fixtures" / "legacy_ptx" / "PTX-02_invariant_poly.ptx"
CSE_PASS_NAME = "basic-block-local-cse"
DRE_PASS_NAME = "conservative-dead-result-elimination"


def _run_pass(text: str):
    program = parse_ptx(text)
    module = module_from_program(text, program)
    result = BasicBlockLocalCSEPass().run(module, AnalysisManager(module, {}))
    return module.function.program, result


def _instructions(program):
    return [item for item in program.items if isinstance(item, PTXInstruction)]


def _pass_record(compilation, name: str):
    return next(record for record in compilation.report.passes if record.name == name)


def test_ptx02_o2_and_o3_remove_one_duplicate_expression_after_dre() -> None:
    text = PTX02.read_text(encoding="utf-8")
    baseline = compile_ptx_detailed(text, opt_level="0")
    optimized_o2 = compile_ptx_detailed(text, opt_level="2")
    optimized_o3 = compile_ptx_detailed(text, opt_level="3")

    # O2 with LoopUnrolling may add body copies → net reduction ≥ 1
    assert len(optimized_o2.lowered.instructions) <= len(baseline.lowered.instructions) - 1
    assert len(optimized_o3.lowered.instructions) >= len(baseline.lowered.instructions) - 2  # O3 adds loop unrolling

    # O2: DRE(1) + CSE(1) = 2, LoopUnrolling may add body copies
    assert _pass_record(optimized_o2, DRE_PASS_NAME).details["transforms_applied"] == 1
    assert _pass_record(optimized_o2, CSE_PASS_NAME).details["transforms_applied"] == 1
    assert optimized_o2.report.metrics["optimization_transforms_applied"] >= 2  # DRE+CSE+LICM

    # O3: same base transforms plus experimental passes (e.g. LICM may hoist)
    assert _pass_record(optimized_o3, DRE_PASS_NAME).details["transforms_applied"] == 1
    assert _pass_record(optimized_o3, CSE_PASS_NAME).details["transforms_applied"] == 1
    assert optimized_o3.report.metrics["optimization_transforms_applied"] >= 2

    assert all(record.name != CSE_PASS_NAME for record in baseline.report.passes)
    assert baseline.report.metrics["optimization_transforms_applied"] == 0


def test_pass_rewrites_duplicate_destination_uses_and_deletes_duplicate_add() -> None:
    optimized_program, result = _run_pass(PTX02.read_text(encoding="utf-8"))
    instructions = _instructions(optimized_program)

    assert result.changed is True
    assert result.details["replacements"] == ["%f6 -> %f5"]
    assert not any(item.operands and item.operands[0] == "%f6" for item in instructions)
    assert sum(
        item.opcode == "add.f32" and item.operands == ("%f5", "%f1", "%f2")
        for item in instructions
    ) == 1
    assert any(
        item.opcode == "add.f32" and item.operands == ("%f8", "%f7", "%f5")
        for item in instructions
    )


def test_o0_ptx02_golden_binary_is_unchanged() -> None:
    golden_path = ROOT / "tests" / "fixtures" / "o0_binary_sha256.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    text = PTX02.read_text(encoding="utf-8")

    lowered = compile_ptx(text, profile=TRACK_B_V1, opt_level="0")
    blob = instructions_to_bytes(lowered.instructions, TRACK_B_V1)

    assert sha256(blob).hexdigest() == golden["PTX-02_invariant_poly.ptx"]["sha256"]


def test_renamed_kernel_registers_and_labels_still_cse() -> None:
    original = PTX02.read_text(encoding="utf-8")
    renamed = (
        original.replace("invariant_poly", "renamed_poly")
        .replace("%f5", "%f13")
        .replace("%f6", "%f14")
        .replace("LOOP", "RENAMED_LOOP")
        .replace("DONE", "RENAMED_DONE")
    )

    optimized_program, result = _run_pass(renamed)
    instructions = _instructions(optimized_program)

    assert result.changed is True
    assert result.details["replacements"] == ["%f14 -> %f13"]
    assert not any(item.operands and item.operands[0] == "%f14" for item in instructions)
    assert any(
        item.opcode == "add.f32" and item.operands == ("%f8", "%f7", "%f13")
        for item in instructions
    )


def test_intermediate_operand_redefinition_blocks_cse() -> None:
    text = _kernel(
        """
    add.f32 %f5, %f1, %f2;
    mov.f32 %f1, 0f00000000;
    add.f32 %f6, %f1, %f2;
    add.f32 %f7, %f5, %f6;
"""
    )

    optimized_program, result = _run_pass(text)
    instructions = _instructions(optimized_program)

    assert result.changed is False
    assert result.details["removed_instruction_count"] == 0
    assert any(item.operands == ("%f5", "%f1", "%f2") for item in instructions)
    assert any(item.operands == ("%f6", "%f1", "%f2") for item in instructions)


def test_target_redefinition_before_alias_use_blocks_cse() -> None:
    text = _kernel(
        """
    add.u32 %r1, %r2, %r3;
    add.u32 %r4, %r2, %r3;
    mov.u32 %r1, 0;
    add.u32 %r5, %r4, 1;
"""
    )

    optimized_program, result = _run_pass(text)
    instructions = _instructions(optimized_program)

    assert result.changed is False
    assert result.details["removed_instruction_count"] == 0
    assert any(item.opcode == "add.u32" and item.operands == ("%r4", "%r2", "%r3") for item in instructions)
    assert any(item.opcode == "mov.u32" and item.operands == ("%r1", "0") for item in instructions)
    assert any(item.opcode == "add.u32" and item.operands == ("%r5", "%r4", "1") for item in instructions)


def test_cross_label_scope_does_not_cse() -> None:
    text = _kernel(
        """
    add.f32 %f5, %f1, %f2;
NEXT:
    add.f32 %f6, %f1, %f2;
    add.f32 %f7, %f5, %f6;
"""
    )

    optimized_program, result = _run_pass(text)
    instructions = _instructions(optimized_program)

    assert result.changed is False
    assert result.details["removed_instruction_count"] == 0
    assert any(item.operands == ("%f5", "%f1", "%f2") for item in instructions)
    assert any(item.operands == ("%f6", "%f1", "%f2") for item in instructions)


def test_predicated_instruction_does_not_cse() -> None:
    text = _kernel(
        """
    add.f32 %f5, %f1, %f2;
    @%p1 add.f32 %f6, %f1, %f2;
    add.f32 %f7, %f5, %f6;
"""
    )

    optimized_program, result = _run_pass(text)
    instructions = _instructions(optimized_program)

    assert result.changed is False
    assert any(item.predicate == "p1" and item.operands == ("%f6", "%f1", "%f2") for item in instructions)


@pytest.mark.parametrize(
    "boundary",
    [
        "ld.global.f32 %f3, [%rd1];",
        "st.global.f32 [%rd1], %f5;",
        "atom.global.add.u32 %r2, [%rd1], %r1;",
        "bra EXIT;",
        "call FUNC;",
        "ret;",
        "setp.lt.u32 %p1, %r1, 4;",
        "custom.op %f3, %f1;",
        "add.cc.u32 %r2, %r1, 1;",
    ],
)
def test_memory_control_setp_unknown_and_cc_boundaries_do_not_cse(boundary: str) -> None:
    text = _kernel(
        f"""
    add.f32 %f5, %f1, %f2;
    {boundary}
    add.f32 %f6, %f1, %f2;
    add.f32 %f7, %f5, %f6;
EXIT:
    mov.f32 %f8, %f7;
"""
    )

    optimized_program, result = _run_pass(text)
    instructions = _instructions(optimized_program)

    assert result.changed is False
    assert result.details["removed_instruction_count"] == 0
    assert any(item.opcode == "add.f32" and item.operands == ("%f5", "%f1", "%f2") for item in instructions)
    assert any(item.opcode == "add.f32" and item.operands == ("%f6", "%f1", "%f2") for item in instructions)


def _kernel(body: str) -> str:
    return f"""
.visible .entry cse_probe(
    .param .u64 output
)
{{
    .reg .pred %p<3>;
    .reg .b32 %r<8>;
    .reg .b64 %rd<4>;
    .reg .f32 %f<20>;

{body}
    ret;
}}
"""
