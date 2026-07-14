from pathlib import Path
import random
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aec_c1.analysis import Uniformity, analyze_uniformity
from aec_c1.analysis.cfg import build_cfg
from aec_c1.compiler import compile_ptx
from aec_c1.ptx import parse_ptx
from aec_c1.sim import TrackBSimulator, bits_to_f32, f32_to_bits


PTX02 = ROOT / "tests" / "fixtures" / "legacy_ptx" / "PTX-02_invariant_poly.ptx"


def test_ptx02_cfg_identifies_loop_and_edges() -> None:
    program = parse_ptx(PTX02.read_text())
    cfg = build_cfg(program)

    assert cfg.entry in cfg.blocks
    assert "LOOP" in cfg.label_to_block
    assert "DONE" in cfg.label_to_block

    loop_block = cfg.label_to_block["LOOP"]
    done_block = cfg.label_to_block["DONE"]
    entry_block = cfg.blocks[cfg.entry]

    assert done_block in entry_block.branch_successors
    assert entry_block.fallthrough_successor is not None
    assert entry_block.fallthrough_successor != done_block

    loop = cfg.blocks[loop_block]
    assert loop_block in loop.branch_successors
    assert loop.fallthrough_successor is not None
    assert loop.fallthrough_successor != loop_block

    natural_loops = cfg.natural_loops()
    loop = next(nl for nl in natural_loops if nl.header == loop_block and nl.tail == loop_block)
    assert loop is not None
    # Self-loop: natural loop body must contain ONLY the loop block itself
    assert loop.blocks == {loop_block}, f"expected {{{loop_block}}}, got {loop.blocks}"


def test_ptx02_uniformity_classifies_boundary_and_loop_branches() -> None:
    program = parse_ptx(PTX02.read_text())
    facts = analyze_uniformity(program)
    branch_by_target = _branch_states_by_target(program, facts.branch_states)

    assert branch_by_target["DONE"].state is Uniformity.VARYING
    assert branch_by_target["DONE"].result == "proven_varying"
    assert branch_by_target["LOOP"].state is Uniformity.UNIFORM
    assert branch_by_target["LOOP"].result == "proven_uniform"


def test_ptx02_generated_code_uses_only_uniform_loop_brx() -> None:
    lowered = compile_ptx(PTX02.read_text())
    brx_indices = [index for index, inst in enumerate(lowered.instructions) if inst.opcode == "BRX"]

    assert brx_indices == [len(lowered.instructions) - 3]
    brx = lowered.instructions[brx_indices[0]]
    assert brx.imm < brx_indices[0]
    assert lowered.instructions[-1].opcode == "HALT"


def test_ptx02_boundary_differential_cases() -> None:
    for n in [0, 1, 2, 15, 31, 32, 33, 63, 64, 65, 127, 128, 129, 255, 256]:
        _assert_invariant_poly_case(n, seed=n)


def test_ptx02_random_differential_cases() -> None:
    rng = random.Random(20260713)
    for case_index in range(100):
        _assert_invariant_poly_case(rng.randint(0, 256), seed=case_index + 1000)


def _branch_states_by_target(program, branch_states):
    states = {}
    for index, state in branch_states.items():
        item = program.items[index]
        assert not isinstance(item, str)
        states[item.operands[0]] = state
    return states


def _assert_invariant_poly_case(n: int, seed: int) -> None:
    block_dim = 256
    grid_dim = 1
    rng = random.Random(seed)
    gap_x = rng.randrange(0, 8) * 4
    gap_y = rng.randrange(0, 8) * 4
    base_x = gap_x
    base_y = base_x + block_dim * 4 + gap_y
    gmem = bytearray(base_y + block_dim * 4)
    sentinel = b"\xa5\xa5\xa5\xa5"

    x_bits: list[int] = []
    for index in range(block_dim):
        value = _random_finite_f32_bits(rng)
        x_bits.append(value)
        _write_u32(gmem, base_x + index * 4, value)
        gmem[base_y + index * 4 : base_y + index * 4 + 4] = sentinel

    param_a = _random_finite_f32_bits(rng)
    param_b = _random_finite_f32_bits(rng)
    lowered = compile_ptx(PTX02.read_text())
    pmem = bytearray(28)
    _write_u64(pmem, lowered.parameter_offsets["param_x"], base_x)
    _write_u64(pmem, lowered.parameter_offsets["param_y"], base_y)
    _write_u32(pmem, lowered.parameter_offsets["param_n"], n)
    _write_u32(pmem, lowered.parameter_offsets["param_a"], param_a)
    _write_u32(pmem, lowered.parameter_offsets["param_b"], param_b)

    result = TrackBSimulator(
        lowered.instructions,
        pmem,
        gmem,
        block_dim=block_dim,
        grid_dim=grid_dim,
    ).run()

    for index in range(n):
        expected = _reference_invariant_poly_bits(x_bits[index], param_a, param_b)
        actual = int.from_bytes(result.gmem[base_y + index * 4 : base_y + index * 4 + 4], "little")
        assert actual == expected, (n, index, actual, expected)

    for index in range(n, block_dim):
        actual = bytes(result.gmem[base_y + index * 4 : base_y + index * 4 + 4])
        assert actual == sentinel, (n, index, actual)

    assert len(result.accesses) == 2 * n
    assert all(access.global_thread < n for access in result.accesses)
    assert result.non_uniform_branch_failures == 0
    assert result.brx_execution_count == 8 * 32
    assert len(result.branch_trace) == result.brx_execution_count
    assert sum(1 for trace in result.branch_trace if trace.taken) == 8 * 31
    assert all(trace.uniform for trace in result.branch_trace)


def _reference_invariant_poly_bits(x_bits: int, a_bits: int, b_bits: int) -> int:
    acc = f32_to_bits(0.0)
    for _ in range(32):
        f5 = _f32_add(a_bits, b_bits)
        f6 = _f32_add(a_bits, b_bits)
        f7 = _f32_mul(x_bits, f5)
        f8 = _f32_add(f7, f6)
        _dead = _f32_mul(a_bits, b_bits)
        acc = _f32_add(acc, f8)
    return acc


def _f32_add(lhs_bits: int, rhs_bits: int) -> int:
    return f32_to_bits(bits_to_f32(lhs_bits) + bits_to_f32(rhs_bits))


def _f32_mul(lhs_bits: int, rhs_bits: int) -> int:
    return f32_to_bits(bits_to_f32(lhs_bits) * bits_to_f32(rhs_bits))


def _random_finite_f32_bits(rng: random.Random) -> int:
    if rng.randrange(16) == 0:
        return f32_to_bits(0.0)
    return f32_to_bits(rng.uniform(-1000.0, 1000.0))


def _write_u32(memory: bytearray, offset: int, value: int) -> None:
    memory[offset : offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")


def _write_u64(memory: bytearray, offset: int, value: int) -> None:
    memory[offset : offset + 8] = (value & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
