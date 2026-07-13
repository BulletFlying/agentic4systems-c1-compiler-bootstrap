"""Named pass pipelines selected by the public optimization level."""

from __future__ import annotations

from .foundation import (
    MaterializeCFGPass,
    RecordLoopAnalysisPass,
    RecordUniformityPass,
    ValidateProgramPass,
)
from .manager import PassManager
from .scalar import BasicBlockLocalCSEPass, ConservativeDeadResultEliminationPass


def build_pipeline(opt_level: str) -> PassManager:
    if opt_level == "0":
        return PassManager(
            "O0-foundation",
            [ValidateProgramPass(), MaterializeCFGPass()],
        )
    if opt_level == "2":
        return PassManager(
            "O2-conservative-scalar",
            [
                ValidateProgramPass(),
                ConservativeDeadResultEliminationPass(),
                BasicBlockLocalCSEPass(),
                MaterializeCFGPass(),
                RecordUniformityPass(),
            ],
        )
    if opt_level == "3":
        return PassManager(
            "O3-conservative-scalar",
            [
                ValidateProgramPass(),
                ConservativeDeadResultEliminationPass(),
                BasicBlockLocalCSEPass(),
                MaterializeCFGPass(),
                RecordUniformityPass(),
                RecordLoopAnalysisPass(),
            ],
        )
    raise ValueError(f"unsupported optimization level: O{opt_level}")
