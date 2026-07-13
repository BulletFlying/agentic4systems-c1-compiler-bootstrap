"""Minimal module/function/block IR for analysis and pass orchestration.

This is intentionally not advertised as SSA. It preserves the parsed PTX
program while the framework is established, and gives later transforms a
stable ownership boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..ptx import PTXProgram


@dataclass(frozen=True)
class IRBlock:
    name: str
    instruction_count: int
    predecessors: tuple[str, ...]
    successors: tuple[str, ...]


@dataclass
class IRFunction:
    name: str
    program: PTXProgram
    blocks: tuple[IRBlock, ...] = ()


@dataclass
class IRModule:
    source_text: str
    function: IRFunction
    metadata: dict[str, Any] = field(default_factory=dict)


def module_from_program(source_text: str, program: PTXProgram) -> IRModule:
    return IRModule(
        source_text=source_text,
        function=IRFunction(name=program.kernel_name, program=program),
    )
