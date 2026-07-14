from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aec_c1.compiler import compile_ptx
from aec_c1.isa import decode_words_to_instruction, encode_instruction


def test_shl_b32_encodes_as_shl_u32_per_20260714_erratum() -> None:
    ptx = """
.version 9.3
.target sm_90
.address_size 64
.visible .entry shift_kernel(
    .param .b32 param_x
)
{
    .reg .b32 %b<4>;
    ld.param.b32 %b0, [param_x];
    mov.b32 %b1, 3;
    shl.b32 %b2, %b0, %b1;
    ret;
}
"""
    lowered = compile_ptx(ptx)
    shl = next(inst for inst in lowered.instructions if inst.opcode == "SHL")

    # The PTX source type remains .b32, but the legal AEC encoding is SHL.u32.
    assert shl.dtype == "b32"
    decoded = decode_words_to_instruction(encode_instruction(shl))
    assert decoded.opcode == "SHL"
    assert decoded.dtype == "u32"


def test_negated_brx_encoding_remains_available_for_uniform_branches() -> None:
    ptx = """
.version 9.3
.target sm_90
.address_size 64
.visible .entry uniform_negated_branch(
    .param .u32 param_n
)
{
    .reg .pred %p<2>;
    .reg .u32 %r<2>;
    ld.param.u32 %r0, [param_n];
    setp.eq.u32 %p0, %r0, %r0;
    @!%p0 bra DONE;
    mov.u32 %r1, 1;
DONE:
    ret;
}
"""
    lowered = compile_ptx(ptx)
    brx = next(inst for inst in lowered.instructions if inst.opcode == "BRX")

    assert brx.predicate == 0
    assert brx.predicate_negated is True
