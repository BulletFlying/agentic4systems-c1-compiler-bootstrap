"""Deterministic pass execution and recording."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ..analysis import AnalysisManager
from ..ir import IRModule
from .base import CompilerPass


@dataclass(frozen=True)
class PassRecord:
    name: str
    changed: bool
    details: dict[str, Any]
    invalidated_analyses: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "changed": self.changed,
            "details": dict(sorted(self.details.items())),
            "invalidated_analyses": list(self.invalidated_analyses),
        }


class PassManager:
    def __init__(self, name: str, passes: Iterable[CompilerPass]) -> None:
        self.name = name
        self._passes = tuple(passes)

    @property
    def pass_names(self) -> tuple[str, ...]:
        return tuple(compiler_pass.name for compiler_pass in self._passes)

    def run(self, module: IRModule, analyses: AnalysisManager) -> tuple[PassRecord, ...]:
        records: list[PassRecord] = []
        for compiler_pass in self._passes:
            result = compiler_pass.run(module, analyses)
            invalidated = tuple(sorted(result.invalidated_analyses))
            if invalidated:
                analyses.invalidate(invalidated)
            records.append(
                PassRecord(
                    name=compiler_pass.name,
                    changed=result.changed,
                    details=dict(result.details),
                    invalidated_analyses=invalidated,
                )
            )
        return tuple(records)
