"""Pass contracts shared by the explicit compiler pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..analysis import AnalysisManager
from ..ir import IRModule


@dataclass(frozen=True)
class PassResult:
    changed: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    invalidated_analyses: frozenset[str] = frozenset()


class CompilerPass(Protocol):
    name: str

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        """Run the pass without using global compiler state."""
