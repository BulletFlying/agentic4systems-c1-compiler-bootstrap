from pathlib import Path
import random
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aec_c1.compiler import compile_ptx
from aec_c1.isa import AECInstruction, decode_words_to_instruction, encode_instruction, instructions_to_bytes, words_to_msb_hex
from aec_c1.objdump import disassemble
from aec_c1.sim import TrackBSimulator, bits_to_f32, f32_to_bits


def test_track_b_abi_smoke_encoding_matches_public_hex() -> None:
    instructions = [
        AECInstruction("LOADI", dest=1, imm=40),
        AECInstruction("LOADI", dest=2, imm=2),
        AECInstruction("ADD", dtype="u32", dest=3, src1=1, src2=2),
        AECInstruction("LOADI", dest=4, imm=0x100),
        AECInstruction("ST", dtype="u32", src1=4, src2=3, memory_space="gmem"),
        AECInstruction("HALT"),
    ]
    actual = [words_to_msb_hex(encode_instruction(inst)) for inst in instructions]
    expected = (ROOT.parent.parent / "Track-B/testcases/tests/aec_cases/abi/c0_smoke/program.hex").read_text().splitlines()
    assert actual == expected


def test_objdump_round_trip_smoke() -> None:
    blob = instructions_to_bytes([AECInstruction("LOADI", dest=1, imm=40), AECInstruction("HALT")])
    lines = disassemble(blob)
    assert "LOADI R1, 0x00000028" in lines[0]
    assert lines[1].endswith("HALT")


def test_encoder_decoder_field_round_trip() -> None:
    instructions = [
        AECInstruction("LOADI", dest=1, imm=40),
        AECInstruction("ADD", dtype="u32", dest=3, src1=1, src2=2, predicate=1, predicate_negated=True),
        AECInstruction("LD", dtype="b64", dest=2, src1=240, memory_space="pmem"),
        AECInstruction("ST", dtype="f32", src1=8, src2=9, memory_space="gmem"),
        AECInstruction("CMPP", dtype="u32", dest=1, src1=5, src2=6, compare="ge"),
        AECInstruction("BRX", predicate=1, imm=22),
        AECInstruction("CVTFF", dtype="f32", cvt_src_type="f16", dest=4, src1=5),
    ]
    for instruction in instructions:
        assert decode_words_to_instruction(encode_instruction(instruction)) == instruction


def test_public_ptx_01_lowers_to_raw_instructions() -> None:
    ptx = (ROOT / "testcases/PTX-01_vector_add.ptx").read_text()
    lowered = compile_ptx(ptx)
    blob = instructions_to_bytes(lowered.instructions)
    assert len(blob) % 16 == 0
    assert lowered.instructions[-1].opcode == "HALT"
    assert lowered.parameter_offsets == {"param_a": 0, "param_b": 8, "param_c": 16, "param_n": 24}


def test_public_ptx_01_boundary_branch_is_if_converted() -> None:
    ptx = (ROOT / "testcases/PTX-01_vector_add.ptx").read_text()
    lowered = compile_ptx(ptx)
    assert "BRX" not in [inst.opcode for inst in lowered.instructions]
    assert any(inst.predicate == 1 and inst.predicate_negated for inst in lowered.instructions)


def test_public_ptx_01_partial_warp_differential_cases() -> None:
    for n in [1, 2, 15, 31, 32, 33, 63, 64, 65, 127]:
        _assert_vector_add_case(n, seed=n)


def test_public_ptx_01_random_differential_cases() -> None:
    rng = random.Random(20260712)
    for case_index in range(100):
        _assert_vector_add_case(rng.randint(1, 384), seed=case_index)


def test_all_public_ptx_files_lower_to_raw_instructions() -> None:
    for ptx_path in sorted((ROOT / "testcases").glob("PTX-*.ptx")):
        lowered = compile_ptx(ptx_path.read_text())
        blob = instructions_to_bytes(lowered.instructions)
        assert len(blob) % 16 == 0, ptx_path.name
        assert lowered.instructions[-1].opcode == "HALT", ptx_path.name


def _assert_vector_add_case(n: int, seed: int) -> None:
    block_dim = 256
    grid_dim = (n + block_dim - 1) // block_dim
    total_threads = block_dim * grid_dim
    base_a = 0
    base_b = total_threads * 4
    base_c = total_threads * 8
    gmem = bytearray(total_threads * 12)
    sentinel = b"\xa5\xa5\xa5\xa5"

    rng = random.Random(seed)
    a_bits: list[int] = []
    b_bits: list[int] = []
    for index in range(total_threads):
        a_value = f32_to_bits(rng.uniform(-100.0, 100.0))
        b_value = f32_to_bits(rng.uniform(-100.0, 100.0))
        a_bits.append(a_value)
        b_bits.append(b_value)
        _write_u32(gmem, base_a + index * 4, a_value)
        _write_u32(gmem, base_b + index * 4, b_value)
        gmem[base_c + index * 4 : base_c + index * 4 + 4] = sentinel

    ptx = (ROOT / "testcases/PTX-01_vector_add.ptx").read_text()
    lowered = compile_ptx(ptx)
    pmem = bytearray(28)
    _write_u64(pmem, lowered.parameter_offsets["param_a"], base_a)
    _write_u64(pmem, lowered.parameter_offsets["param_b"], base_b)
    _write_u64(pmem, lowered.parameter_offsets["param_c"], base_c)
    _write_u32(pmem, lowered.parameter_offsets["param_n"], n)

    result = TrackBSimulator(
        lowered.instructions,
        pmem,
        gmem,
        block_dim=block_dim,
        grid_dim=grid_dim,
    ).run()

    for index in range(n):
        expected = f32_to_bits(bits_to_f32(a_bits[index]) + bits_to_f32(b_bits[index]))
        actual = int.from_bytes(result.gmem[base_c + index * 4 : base_c + index * 4 + 4], "little")
        assert actual == expected, (n, index, actual, expected)

    for index in range(n, total_threads):
        actual = bytes(result.gmem[base_c + index * 4 : base_c + index * 4 + 4])
        assert actual == sentinel, (n, index, actual)

    assert len(result.accesses) == n * 3
    assert all(access.global_thread < n for access in result.accesses)


def _write_u32(memory: bytearray, offset: int, value: int) -> None:
    memory[offset : offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")


def _write_u64(memory: bytearray, offset: int, value: int) -> None:
    memory[offset : offset + 8] = (value & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
