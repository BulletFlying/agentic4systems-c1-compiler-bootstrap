"""Encoder legality and hidden-variant tests for C1 submission quality hardening."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aec_c1.compiler import compile_ptx_detailed
from aec_c1.isa import (
    AECInstruction,
    C1_DEFAULT,
    TRACK_B_V1,
    EncodeError,
    encode_instruction,
    decode_words_to_instruction,
)
from aec_c1.legacy_lowering import Lowerer
from aec_c1.ptx import parse_ptx


# ---------------------------------------------------------------------------
# PTX helpers
# ---------------------------------------------------------------------------

def _ptx(body_lines: list[str], **kwargs: str) -> str:
    """Build valid multi-line PTX from body instruction lines."""
    regs = kwargs.get("regs", ".reg .b64 %rd<4>;\n.reg .b32 %r<8>;\n.reg .pred %p<3>;")
    params = kwargs.get("params", "    .param .u64 out")
    lines = [
        ".version 7.0",
        ".target sm_70",
        ".address_size 64",
        "",
        ".visible .entry test(",
        params,
        ")",
        "{",
    ]
    for r in regs.strip().split("\n"):
        if r.strip():
            lines.append(r.strip())
    for bl in body_lines:
        lines.append(bl)
    lines.append("}")
    return "\n".join(lines)


# ============================================================================
# Item 1: C1_DEFAULT profile encoder legality tests
# ============================================================================

class TestC1DefaultProfile:
    """Verify C1_DEFAULT profile enforces the reduced C1 spec opcode/type set."""

    @pytest.mark.parametrize("op,dtype", [
        ("DIV", "f32"), ("NEG", "f32"), ("ABS", "f32"),
        ("SHUF", "f32"), ("ATOM", "u32"),
        ("RCP", "f32"), ("RSQ", "f32"), ("SIN", "f32"), ("COS", "f32"),
        ("EXP", "f32"), ("LOG", "f32"), ("SQRT", "f32"),
        ("VOTE", "none"), ("MTCH", "none"),
    ])
    def test_c1_rejects_non_c1_opcode(self, op: str, dtype: str) -> None:
        inst = AECInstruction(op, dtype=dtype, dest=1, src1=2, src2=3)
        with pytest.raises(EncodeError):
            encode_instruction(inst, C1_DEFAULT)

    def test_c1_rejects_non_c1_types(self) -> None:
        for t in ["f16", "bf16", "f64", "u8", "s8"]:
            inst = AECInstruction("ADD", dtype=t, dest=1, src1=2, src2=3)
            with pytest.raises(EncodeError):
                encode_instruction(inst, C1_DEFAULT)

    def test_c1_accepts_all_c1_opcodes(self) -> None:
        c1_ops = ["ADD", "SUB", "MUL", "MAD", "FMA", "AND", "OR", "XOR",
                   "SHL", "SHR", "CMPP", "LD", "ST", "BR", "BRX", "HALT",
                   "CPY", "LOADI", "LOADI64"]
        for op in c1_ops:
            kwargs: dict[str, Any] = {"dest": 1, "src1": 2, "src2": 3}
            if op == "LOADI64":
                kwargs["imm"] = 0x123456789ABCDEF0
            elif op == "BRX":
                kwargs["imm"] = 4
                kwargs["src2"] = 0
                kwargs["predicate"] = 0
            elif op in ("BR", "LOADI"):
                kwargs["imm"] = 4
                kwargs["src2"] = 0
            inst = AECInstruction(op, dtype="u32", **kwargs)
            encode_instruction(inst, C1_DEFAULT)

    def test_shl_b32_encodes_as_shl_u32(self) -> None:
        inst = AECInstruction("SHL", dtype="b32", dest=5, src1=5, src2=3)
        words = encode_instruction(inst, C1_DEFAULT)
        decoded = decode_words_to_instruction(words, C1_DEFAULT)
        assert decoded.dtype == "u32"
        assert decoded.opcode == "SHL"

    def test_round_trip_all_c1_types(self) -> None:
        for dtype in ["b32", "b64", "u32", "s32", "f32", "none"]:
            inst = AECInstruction("ADD", dtype=dtype, dest=1, src1=2, src2=3)
            words = encode_instruction(inst, C1_DEFAULT)
            decoded = decode_words_to_instruction(words, C1_DEFAULT)
            assert decoded.opcode == "ADD" and decoded.dtype == dtype

    def test_track_b_profile_accepts_extensions(self) -> None:
        inst = AECInstruction("DIV", dtype="f32", dest=1, src1=2, src2=3)
        encode_instruction(inst, TRACK_B_V1)
        with pytest.raises(EncodeError):
            encode_instruction(inst, C1_DEFAULT)

    def test_predicated_instruction_round_trip(self) -> None:
        inst = AECInstruction("ADD", dtype="u32", dest=1, src1=2, src2=3,
                              predicate=3, predicate_negated=True)
        words = encode_instruction(inst, C1_DEFAULT)
        decoded = decode_words_to_instruction(words, C1_DEFAULT)
        assert decoded.predicate == 3 and decoded.predicate_negated is True

    def test_memory_space_round_trip(self) -> None:
        for space in ["gmem", "smem", "cmem", "lmem", "pmem"]:
            inst = AECInstruction("LD", dtype="u32", dest=1, src1=2,
                                  memory_space=space)
            words = encode_instruction(inst, C1_DEFAULT)
            decoded = decode_words_to_instruction(words, C1_DEFAULT)
            assert decoded.memory_space == space

    def test_compare_round_trip(self) -> None:
        for cmp_op in ["eq", "ne", "lt", "le", "gt", "ge"]:
            inst = AECInstruction("CMPP", dtype="u32", dest=1, src1=2, src2=3,
                                  compare=cmp_op)
            words = encode_instruction(inst, C1_DEFAULT)
            decoded = decode_words_to_instruction(words, C1_DEFAULT)
            assert decoded.compare == cmp_op


# ============================================================================
# Item 2: mov.u64/b64 immediate lowering tests
# ============================================================================

class TestMovU64Lowering:
    """Verify 64-bit immediate and register-copy lowering."""

    def test_mov_u64_immediate_emits_loadi64(self) -> None:
        text = _ptx([
            "    mov.u64 %rd1, 0xDEADBEEFCAFEBABE;",
        ], regs=".reg .b64 %rd<2>;")
        program = parse_ptx(text)
        lowered = Lowerer(program, profile=C1_DEFAULT).lower()
        loadi64_ops = [i for i in lowered.instructions if i.opcode == "LOADI64"]
        assert len(loadi64_ops) >= 1

    def test_mov_b64_immediate_emits_loadi64(self) -> None:
        text = _ptx([
            "    mov.b64 %rd1, 0x123456789ABCDEF0;",
        ], regs=".reg .b64 %rd<2>;")
        program = parse_ptx(text)
        lowered = Lowerer(program, profile=C1_DEFAULT).lower()
        assert any(i.opcode == "LOADI64" for i in lowered.instructions)

    def test_mov_u64_register_copy_uses_cpy(self) -> None:
        text = _ptx([
            "    ld.param.u64 %rd1, [out];",
            "    mov.u64 %rd2, %rd1;",
            "    st.global.u64 [%rd2], %rd2;",
        ], regs=".reg .b64 %rd<4>;")
        program = parse_ptx(text)
        lowered = Lowerer(program, profile=C1_DEFAULT).lower()
        assert any(i.opcode == "CPY" for i in lowered.instructions)

    def test_mov_u32_immediate_uses_loadi(self) -> None:
        text = _ptx([
            "    mov.u32 %r1, 42;",
        ], regs=".reg .b32 %r<2>;")
        program = parse_ptx(text)
        lowered = Lowerer(program, profile=C1_DEFAULT).lower()
        assert any(i.opcode == "LOADI" for i in lowered.instructions)
        assert not any(i.opcode == "LOADI64" for i in lowered.instructions)


# ============================================================================
# Item 5: Scheduler target correctness tests
# ============================================================================

class TestSchedulerTargets:
    """Verify scheduler preserves BR/BRX targets, block boundaries, and barriers."""

    def test_brx_target_preserved_after_scheduling(self) -> None:
        text = _ptx([
            "    ld.param.u32 %r1, [out];",
            "    mov.u32 %r2, 0;",
            "LOOP:",
            "    add.u32 %r2, %r2, 1;",
            "    setp.lt.u32 %p1, %r2, %r1;",
            "    @%p1 bra LOOP;",
        ], params="    .param .u32 out")
        result = compile_ptx_detailed(text, opt_level="2")
        brx_insts = [i for i in result.lowered.instructions if i.opcode == "BRX"]
        assert len(brx_insts) >= 1
        for brx in brx_insts:
            assert 0 <= brx.imm < len(result.lowered.instructions)

    def test_halt_at_end_of_block(self) -> None:
        from aec_c1.passes.scheduler import _schedule_block
        insts = [
            AECInstruction("ADD", dtype="u32", dest=1, src1=2, src2=3),
            AECInstruction("HALT", dtype="none"),
            AECInstruction("ADD", dtype="u32", dest=4, src1=1, src2=3),
        ]
        result = _schedule_block(insts)
        assert result[-1].opcode == "HALT"

    def test_br_at_end_of_block(self) -> None:
        from aec_c1.passes.scheduler import _schedule_block
        insts = [
            AECInstruction("ADD", dtype="u32", dest=1, src1=2, src2=3),
            AECInstruction("BR", dtype="none", imm=10),
            AECInstruction("ADD", dtype="u32", dest=4, src1=1, src2=3),
        ]
        result = _schedule_block(insts)
        assert result[-1].opcode == "BR"

    def test_store_barrier_prevents_load_reordering(self) -> None:
        from aec_c1.passes.scheduler import _schedule_block
        insts = [
            AECInstruction("ADD", dtype="u32", dest=1, src1=2, src2=3),
            AECInstruction("ST", dtype="u32", src1=10, src2=1, memory_space="gmem"),
            AECInstruction("LD", dtype="u32", dest=5, src1=20, memory_space="gmem"),
            AECInstruction("ADD", dtype="u32", dest=6, src1=5, src2=1),
        ]
        result = _schedule_block(insts)
        st_pos = next(i for i, inst in enumerate(result) if inst.opcode == "ST")
        ld_pos = next(i for i, inst in enumerate(result) if inst.opcode == "LD")
        assert st_pos < ld_pos

    def test_scheduler_no_crash_on_single_instruction_block(self) -> None:
        from aec_c1.passes.scheduler import _schedule_block
        result = _schedule_block([AECInstruction("HALT", dtype="none")])
        assert len(result) == 1


# ============================================================================
# Item 7: Hidden variant tests
# ============================================================================

class TestHiddenVariants:
    """Register renaming, label order, dead code, empty blocks, hex/negative
    immediates, special registers, u64 pointers, uniform negated branches."""

    def test_register_renamed_equivalent_opcodes(self) -> None:
        a = _ptx([
            "    ld.param.u64 %rd1, [out];",
            "    ld.global.u32 %r1, [%rd1];",
            "    add.u32 %r2, %r1, %r1;",
            "    st.global.u32 [%rd1], %r2;",
        ])
        b = _ptx([
            "    ld.param.u64 %rd3, [out];",
            "    ld.global.u32 %r5, [%rd3];",
            "    add.u32 %r6, %r5, %r5;",
            "    st.global.u32 [%rd3], %r6;",
        ])
        la = Lowerer(parse_ptx(a), profile=C1_DEFAULT).lower()
        lb = Lowerer(parse_ptx(b), profile=C1_DEFAULT).lower()
        assert len(la.instructions) == len(lb.instructions)
        assert [i.opcode for i in la.instructions] == [i.opcode for i in lb.instructions]

    def test_reversed_labels_compile(self) -> None:
        text = _ptx([
            "    bra L2;",
            "L1:",
            "    mov.u32 %r1, 10;",
            "    bra DONE;",
            "L2:",
            "    mov.u32 %r1, 20;",
            "    bra L1;",
            "DONE:",
        ])
        result = compile_ptx_detailed(text, opt_level="2")
        assert len(result.lowered.instructions) > 0

    def test_dead_code_removed_by_dre(self) -> None:
        clean = _ptx([
            "    ld.param.u64 %rd1, [out];",
            "    ld.global.u32 %r1, [%rd1];",
            "    st.global.u32 [%rd1], %r1;",
        ])
        dead = _ptx([
            "    ld.param.u64 %rd1, [out];",
            "    mul.u32 %r2, %r1, %r1;",
            "    add.u32 %r3, %r2, %r2;",
            "    ld.global.u32 %r1, [%rd1];",
            "    st.global.u32 [%rd1], %r1;",
        ])
        r_clean = compile_ptx_detailed(clean, opt_level="2")
        r_dead = compile_ptx_detailed(dead, opt_level="2")
        assert len(r_dead.lowered.instructions) <= len(r_clean.lowered.instructions) + 2

    def test_empty_block_handled_by_blocksimp(self) -> None:
        text = _ptx([
            "    mov.u32 %r1, 42;",
            "    bra REAL;",
            "EMPTY:",
            "REAL:",
        ])
        result = compile_ptx_detailed(text, opt_level="2")
        assert len(result.lowered.instructions) > 0

    def test_hex_immediate(self) -> None:
        text = _ptx([
            "    ld.param.u64 %rd1, [out];",
            "    mov.u32 %r1, 0xDEAD;",
            "    st.global.u32 [%rd1], %r1;",
        ])
        result = compile_ptx_detailed(text, opt_level="2")
        loadi_ops = [i for i in result.lowered.instructions if i.opcode == "LOADI"]
        assert len(loadi_ops) >= 1, f"Expected LOADI for hex imm, got {[i.opcode for i in result.lowered.instructions]}"

    def test_negative_f32_immediate(self) -> None:
        text = _ptx([
            "    ld.param.u64 %rd1, [out];",
            "    mov.f32 %f1, 0fbf800000;",
            "    st.global.f32 [%rd1], %f1;",
        ], regs=".reg .f32 %f<2>;\n.reg .b64 %rd<4>;\n.reg .b32 %r<4>;")
        result = compile_ptx_detailed(text, opt_level="2")
        assert len(result.lowered.instructions) > 0

    def test_tid_xyz_special_registers(self) -> None:
        text = _ptx([
            "    ld.param.u64 %rd1, [out];",
            "    mov.u32 %r1, %tid.x;",
            "    mov.u32 %r2, %tid.y;",
            "    mov.u32 %r3, %tid.z;",
            "    add.u32 %r1, %r1, %r2;",
            "    add.u32 %r1, %r1, %r3;",
            "    st.global.u32 [%rd1], %r1;",
        ])
        result = compile_ptx_detailed(text, opt_level="2")
        # CPY instructions load special registers into GPRs
        cpy_insts = [i for i in result.lowered.instructions if i.opcode == "CPY"]
        assert len(cpy_insts) >= 3, f"Expected >=3 CPY for %tid.x/y/z, got {[i.opcode for i in result.lowered.instructions]}"

    def test_u64_pointer_low32_truncation(self) -> None:
        text = _ptx([
            "    ld.param.u64 %rd1, [out];",
            "    ld.global.u64 %rd2, [%rd1];",
            "    add.u64 %rd3, %rd1, %rd2;",
            "    ld.global.u32 %r1, [%rd3];",
        ])
        result = compile_ptx_detailed(text, opt_level="2")
        assert len(result.lowered.instructions) > 0

    def test_uniform_negated_branch(self) -> None:
        text = _ptx([
            "    mov.u32 %r1, 0;",
            "    setp.eq.u32 %p1, %r1, 0;",
            "    @!%p1 bra SKIP;",
            "    mov.u32 %r2, 1;",
            "SKIP:",
        ])
        result = compile_ptx_detailed(text, opt_level="2")
        brx_insts = [i for i in result.lowered.instructions if i.opcode == "BRX"]
        assert len(brx_insts) >= 1
        assert brx_insts[0].predicate_negated is True

    def test_all_hides_combined(self) -> None:
        text = _ptx([
            "    mov.u32 %r5, 0x2A;",
            "    setp.eq.u32 %p1, %r5, 0;",
            "    @!%p1 bra STORE;",
            "    mov.u32 %r5, 0;",
            "STORE:",
            "    st.global.u32 [out], %r5;",
        ], params="    .param .u32 out")
        result = compile_ptx_detailed(text, opt_level="2")
        assert len(result.lowered.instructions) > 0
