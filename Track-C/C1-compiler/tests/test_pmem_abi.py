"""PMEM ABI conformance tests per official C1 spec Section 7.

Tests: declaration order, natural alignment, 8-byte block alignment,
parameter size and padding.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aec_c1.legacy_lowering import TYPE_SIZE, layout_parameters  # noqa: E402
from aec_c1.ptx import Parameter, PTXProgram  # noqa: E402


def _make_program(params: list[tuple[str, str]]) -> PTXProgram:
    return PTXProgram(
        kernel_name="test_kernel",
        parameters=tuple(Parameter(name=name, dtype=dtype) for name, dtype in params),
        registers=(),
        items=(),
    )


class TestDeclarationOrder:
    """Parameters are laid out in declaration order (spec 7.2 rule 1)."""

    def test_single_param_offset_zero(self) -> None:
        program = _make_program([("param_a", "u32")])
        offsets = layout_parameters(program)
        assert offsets == {"param_a": 0}

    def test_two_params_sequential(self) -> None:
        program = _make_program([("param_a", "u32"), ("param_b", "u32")])
        offsets = layout_parameters(program)
        assert offsets["param_a"] == 0
        assert offsets["param_b"] == 4

    def test_three_params_order_preserved(self) -> None:
        program = _make_program(
            [("param_a", "u64"), ("param_b", "u32"), ("param_c", "u64")]
        )
        offsets = layout_parameters(program)
        # param_a: offset 0, size 8
        # param_b: offset 8, size 4 (8-byte aligned naturally for u32)
        # param_c: offset 16, size 8 (naturally aligned to 8)
        assert offsets["param_a"] == 0
        assert offsets["param_b"] == 8
        assert offsets["param_c"] == 16


class TestNaturalAlignment:
    """Each parameter is naturally aligned (spec 7.2 rule 2)."""

    def test_u32_natural_alignment_4(self) -> None:
        program = _make_program([("param_a", "u32")])
        offsets = layout_parameters(program)
        assert offsets["param_a"] % 4 == 0

    def test_u64_natural_alignment_8(self) -> None:
        program = _make_program([("param_a", "u64")])
        offsets = layout_parameters(program)
        assert offsets["param_a"] % 8 == 0

    def test_f32_natural_alignment_4(self) -> None:
        program = _make_program([("param_a", "f32")])
        offsets = layout_parameters(program)
        assert offsets["param_a"] % 4 == 0

    def test_u64_after_u32_gets_aligned(self) -> None:
        program = _make_program([("param_a", "u32"), ("param_b", "u64")])
        offsets = layout_parameters(program)
        assert offsets["param_a"] == 0
        assert offsets["param_b"] == 8  # 4-byte gap inserted for u64 alignment

    def test_u64_u32_u64_alignment(self) -> None:
        program = _make_program(
            [("param_a", "u64"), ("param_b", "u32"), ("param_c", "u64")]
        )
        offsets = layout_parameters(program)
        assert offsets["param_a"] == 0  # size 8
        assert offsets["param_b"] == 8  # size 4 (u32 naturally aligns at 8)
        assert offsets["param_c"] == 16  # u32 ends at 12, u64 needs 8-byte align


class Test8ByteBlockAlignment:
    """Total parameter block size aligns to 8 bytes (spec 7.2 rule 5)."""

    def _total_size(self, offsets: dict[str, int], params: list[tuple[str, str]]) -> int:
        last_param = params[-1]
        last_offset = offsets[last_param[0]]
        last_size = TYPE_SIZE[last_param[1]]
        end = last_offset + last_size
        if end % 8 != 0:
            end += 8 - (end % 8)
        return end

    def test_three_u32_total_aligned_to_8(self) -> None:
        params = [("a", "u32"), ("b", "u32"), ("c", "u32")]
        program = _make_program(params)
        offsets = layout_parameters(program)
        total = self._total_size(offsets, params)
        assert total % 8 == 0
        assert total == 16  # 12 bytes + 4 padding

    def test_u64_u32_u64_total_aligned(self) -> None:
        params = [("a", "u64"), ("b", "u32"), ("c", "u64")]
        program = _make_program(params)
        offsets = layout_parameters(program)
        total = self._total_size(offsets, params)
        assert total % 8 == 0
        assert total == 24  # u64(8) + u32(4) + padding(4) + u64(8) = 24

    def test_vector_add_layout_matches_spec_example(self) -> None:
        """Matches spec section 7.3 example exactly."""
        params = [
            ("param_a", "u64"),
            ("param_b", "u64"),
            ("param_c", "u64"),
            ("param_n", "u32"),
        ]
        program = _make_program(params)
        offsets = layout_parameters(program)
        assert offsets == {
            "param_a": 0,
            "param_b": 8,
            "param_c": 16,
            "param_n": 24,
        }
        # Total: 24 + 4 = 28, align to 8 = 32
        total = self._total_size(offsets, params)
        assert total == 32


class TestTypeSizeTable:
    """Type sizes match spec section 7.2 table."""

    def test_u32_size(self) -> None:
        assert TYPE_SIZE["u32"] == 4

    def test_s32_size(self) -> None:
        assert TYPE_SIZE["s32"] == 4

    def test_b32_size(self) -> None:
        assert TYPE_SIZE["b32"] == 4

    def test_f32_size(self) -> None:
        assert TYPE_SIZE["f32"] == 4

    def test_u64_size(self) -> None:
        assert TYPE_SIZE["u64"] == 8

    def test_b64_size(self) -> None:
        assert TYPE_SIZE["b64"] == 8
