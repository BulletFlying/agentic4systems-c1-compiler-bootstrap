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
from aec_c1.passes import LocalConstantFoldingPass
from aec_c1.ptx import PTXInstruction, parse_ptx


PTX02 = ROOT / "tests" / "fixtures" / "legacy_ptx" / "PTX-02_invariant_poly.ptx"
PASS_NAME = "local-constant-folding"


def _run_pass(text: str):
    program = parse_ptx(text)
    module = module_from_program(text, program)
    result = LocalConstantFoldingPass().run(module, AnalysisManager(module, {}))
    return module.function.program, result


def _instructions(program):
    return [item for item in program.items if isinstance(item, PTXInstruction)]


def _pass_record(compilation, name: str):
    return next(record for record in compilation.report.passes if record.name == name)


def test_u32_constants_fold_within_basic_block() -> None:
    text = _kernel(
        """
    mov.u32 %r1, 2;
    add.u32 %r2, %r1, 3;
    sub.u32 %r3, %r2, 1;
    mul.u32 %r4, %r3, 4;
    st.global.u32 [%rd1], %r4;
"""
    )

    optimized_program, result = _run_pass(text)
    instructions = _instructions(optimized_program)

    assert result.changed is True
    assert result.details["folded_instruction_count"] == 3
    assert result.details["folded_destinations"] == ["%r2", "%r3", "%r4"]
    assert result.details["transforms_applied"] == 3
    assert any(item.opcode == "mov.u32" and item.operands == ("%r2", "5") for item in instructions)
    assert any(item.opcode == "mov.u32" and item.operands == ("%r3", "4") for item in instructions)
    assert any(item.opcode == "mov.u32" and item.operands == ("%r4", "16") for item in instructions)


def test_f32_constants_fold_with_hex_float_immediates() -> None:
    text = _kernel(
        """
    mov.f32 %f1, 0f3f800000;
    add.f32 %f2, %f1, 0f40000000;
    mul.f32 %f3, %f2, 0f40400000;
    st.global.f32 [%rd1], %f3;
"""
    )

    optimized_program, result = _run_pass(text)
    instructions = _instructions(optimized_program)

    assert result.changed is True
    assert result.details["folded_instruction_count"] == 2
    assert any(item.opcode == "mov.f32" and item.operands == ("%f2", "0f40400000") for item in instructions)
    assert any(item.opcode == "mov.f32" and item.operands == ("%f3", "0f41100000") for item in instructions)


def test_f32_overflow_preserves_original_instruction() -> None:
    text = _kernel(
        """
    mov.f32 %f1, 0f7f7fffff;
    add.f32 %f2, %f1, %f1;
    st.global.f32 [%rd1], %f2;
"""
    )

    optimized_program, result = _run_pass(text)
    instructions = _instructions(optimized_program)

    assert result.changed is False
    assert result.details["folded_instruction_count"] == 0
    assert any(item.opcode == "add.f32" and item.operands == ("%f2", "%f1", "%f1") for item in instructions)


def test_register_redefinition_invalidates_constant() -> None:
    text = _kernel(
        """
    mov.u32 %r1, 2;
    mov.u32 %r1, %r6;
    add.u32 %r2, %r1, 3;
    st.global.u32 [%rd1], %r2;
"""
    )

    optimized_program, result = _run_pass(text)
    instructions = _instructions(optimized_program)

    assert result.changed is False
    assert result.details["folded_instruction_count"] == 0
    assert any(item.opcode == "add.u32" and item.operands == ("%r2", "%r1", "3") for item in instructions)


def test_cross_label_scope_does_not_fold() -> None:
    text = _kernel(
        """
    mov.u32 %r1, 2;
NEXT:
    add.u32 %r2, %r1, 3;
    st.global.u32 [%rd1], %r2;
"""
    )

    optimized_program, result = _run_pass(text)
    instructions = _instructions(optimized_program)

    assert result.changed is False
    assert result.details["folded_instruction_count"] == 0
    assert any(item.opcode == "add.u32" and item.operands == ("%r2", "%r1", "3") for item in instructions)


def test_predicated_instruction_does_not_fold() -> None:
    text = _kernel(
        """
    mov.u32 %r1, 2;
    @%p1 add.u32 %r2, %r1, 3;
    st.global.u32 [%rd1], %r2;
"""
    )

    optimized_program, result = _run_pass(text)
    instructions = _instructions(optimized_program)

    assert result.changed is False
    assert any(item.predicate == "p1" and item.operands == ("%r2", "%r1", "3") for item in instructions)


@pytest.mark.parametrize(
    "boundary",
    [
        "ld.global.u32 %r6, [%rd1];",
        "st.global.u32 [%rd1], %r1;",
        "atom.global.add.u32 %r6, [%rd1], %r1;",
        "bra EXIT;",
        "call FUNC;",
        "ret;",
        "setp.lt.u32 %p1, %r1, 4;",
        "custom.op %r6, %r1;",
        "add.cc.u32 %r6, %r1, 1;",
    ],
)
def test_memory_control_setp_unknown_and_cc_boundaries_do_not_fold(boundary: str) -> None:
    text = _kernel(
        f"""
    mov.u32 %r1, 2;
    {boundary}
    add.u32 %r2, %r1, 3;
EXIT:
    st.global.u32 [%rd1], %r2;
"""
    )

    optimized_program, result = _run_pass(text)
    instructions = _instructions(optimized_program)

    assert result.changed is False
    assert result.details["folded_instruction_count"] == 0
    assert any(item.opcode == "add.u32" and item.operands == ("%r2", "%r1", "3") for item in instructions)


def test_o0_ptx02_golden_binary_is_unchanged() -> None:
    golden_path = ROOT / "tests" / "fixtures" / "o0_binary_sha256.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    text = PTX02.read_text(encoding="utf-8")

    lowered = compile_ptx(text, profile=TRACK_B_V1, opt_level="0")
    blob = instructions_to_bytes(lowered.instructions, TRACK_B_V1)

    assert sha256(blob).hexdigest() == golden["PTX-02_invariant_poly.ptx"]["sha256"]


def test_pipeline_reports_local_constant_folding_and_preserves_cycle_placeholders() -> None:
    text = _kernel(
        """
    mov.u32 %r1, 2;
    add.u32 %r2, %r1, 3;
    st.global.u32 [%rd1], %r2;
"""
    )

    compiled = compile_ptx_detailed(text, opt_level="3")
    record = _pass_record(compiled, PASS_NAME)
    payload = compiled.report.to_dict()

    assert record.changed is True
    assert record.details["folded_instruction_count"] == 1
    assert record.details["transforms_applied"] == 1
    assert payload["metrics"]["optimization_transforms_applied"] >= 1
    assert payload["cycle_model_metrics"] == {
        "dual_issue_rate": None,
        "memory_transactions": None,
        "spill_count": None,
        "stall_cycles": None,
        "total_cycles": None,
    }
    assert any("constant folding" in note for note in payload["notes"])


def _kernel(body: str) -> str:
    return f"""
.visible .entry const_fold_probe(
    .param .u64 output
)
{{
    .reg .pred %p<3>;
    .reg .b32 %r<8>;
    .reg .b64 %rd<4>;
    .reg .f32 %f<20>;

    ld.param.u64 %rd1, [output];
{body}
    ret;
}}
"""
