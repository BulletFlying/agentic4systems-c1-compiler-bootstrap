"""Named pass pipelines selected by the public optimization level."""

from __future__ import annotations

from .foundation import (
    MaterializeCFGPass,
    RecordLoopAnalysisPass,
    RecordUniformityPass,
    ValidateProgramPass,
)
from .manager import PassManager


def build_pipeline(opt_level: str) -> PassManager:
    if opt_level == "0":
        return PassManager(
            "O0-foundation",
            [ValidateProgramPass(), MaterializeCFGPass()],
        )
    if opt_level == "2":
        return PassManager(
            "O2-analysis-foundation",
            [ValidateProgramPass(), MaterializeCFGPass(), RecordUniformityPass()],
        )
    if opt_level == "3":
        return PassManager(
            "O3-analysis-foundation",
            [
                ValidateProgramPass(),
                MaterializeCFGPass(),
                RecordUniformityPass(),
                RecordLoopAnalysisPass(),
            ],
        )
    raise ValueError(f"unsupported optimization level: O{opt_level}")
