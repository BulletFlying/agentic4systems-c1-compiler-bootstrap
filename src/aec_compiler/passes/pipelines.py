"""Named pass pipelines selected by the public optimization level.

O2 is the production default: only passes with proven correctness (unit,
negative, and manifest e2e coverage) are enabled. O3 enables experimental
passes that may improve performance but carry higher miscompile risk.
"""

from __future__ import annotations

from .foundation import (
    MaterializeCFGPass,
    RecordLoopAnalysisPass,
    RecordUniformityPass,
    ValidateProgramPass,
)
from .manager import PassManager
from .register_allocation import LinearScanRegisterAllocationPass
from .gemm import LoopUnrollingPass
from .memory import LoadHoistingPass
from .scalar import (
    BasicBlockLocalCSEPass,
    BlockSimplificationPass,
    ConservativeDeadResultEliminationPass,
    GlobalConstantPropagationPass,
    GlobalDeadCodeEliminationPass,
    LocalConstantFoldingPass,
    LoopInvariantCodeMotionPass,
    RepeatedGlobalLoadReusePass,
)


def build_pipeline(opt_level: str) -> PassManager:
    if opt_level == "0":
        return PassManager(
            "O0-foundation",
            [ValidateProgramPass(), MaterializeCFGPass()],
        )
    if opt_level == "2":
        # O2 pipeline (M2-M5 complete, loop-aware RA 2026-07-14):
        #   Validate → DRE → CSE → LocalCF → GlobalCP → LoadReuse
        #   → CFG → Uniformity → GlobalDCE → LoopAnalysis → LICM
        #   → CFG → Uniformity → BlockSimp → CFG → LoadHoisting(M3)
        #   → CFG → Uniformity → LoopUnrolling(M5) → CFG → Uniformity
        #   → LinearScanRA(M4, loop-aware) → CFG → Uniformity
        #   → [post-lowering: Scheduler(M4)]
        #
        # The RA extends loop-used register live ranges to the loop tail
        # to prevent physical-register reuse across back edges.
        return PassManager(
            "O2-conservative-scalar",
            [
                ValidateProgramPass(),
                ConservativeDeadResultEliminationPass(),
                BasicBlockLocalCSEPass(),
                LocalConstantFoldingPass(),
                GlobalConstantPropagationPass(),
                RepeatedGlobalLoadReusePass(),
                MaterializeCFGPass(),
                RecordUniformityPass(),
                GlobalDeadCodeEliminationPass(),
                RecordLoopAnalysisPass(),
                LoopInvariantCodeMotionPass(),
                MaterializeCFGPass(),
                RecordUniformityPass(),
                BlockSimplificationPass(),
                MaterializeCFGPass(),
                RecordUniformityPass(),
                LoadHoistingPass(),
                MaterializeCFGPass(),
                RecordUniformityPass(),
                LoopUnrollingPass(),
                MaterializeCFGPass(),
                RecordUniformityPass(),
                LinearScanRegisterAllocationPass(),
                MaterializeCFGPass(),
                RecordUniformityPass(),
            ],
        )
    if opt_level == "3":
        # O3 derives from the O2 production baseline and adds experimental
        # reordering: LinearScanRA runs before LoopUnrolling (instead of after),
        # and CFG/Uniformity rebuilds between passes are reduced.  When a new
        # pass is added to O2, it should also be considered for O3 — or
        # explicitly excluded with a comment here.
        _o2_passes = {
            ValidateProgramPass,
            ConservativeDeadResultEliminationPass,
            BasicBlockLocalCSEPass,
            LocalConstantFoldingPass,
            GlobalConstantPropagationPass,
            RepeatedGlobalLoadReusePass,
            GlobalDeadCodeEliminationPass,
            RecordLoopAnalysisPass,
            LoopInvariantCodeMotionPass,
            BlockSimplificationPass,
            LoadHoistingPass,
            LoopUnrollingPass,
            LinearScanRegisterAllocationPass,
        }
        o3_base = [
            ValidateProgramPass(),
            ConservativeDeadResultEliminationPass(),
            BasicBlockLocalCSEPass(),
            LocalConstantFoldingPass(),
            RepeatedGlobalLoadReusePass(),
            MaterializeCFGPass(),
            RecordUniformityPass(),
            GlobalConstantPropagationPass(),
            GlobalDeadCodeEliminationPass(),
            MaterializeCFGPass(),
            RecordUniformityPass(),
            RecordLoopAnalysisPass(),
            BlockSimplificationPass(),
            LoopInvariantCodeMotionPass(),
            LoadHoistingPass(),
            # ---- experimental reordering: RA before Unroll (not yet production-safe) ----
            LinearScanRegisterAllocationPass(),
            LoopUnrollingPass(),
            MaterializeCFGPass(),
            RecordUniformityPass(),
        ]
        # Assert O3 covers all O2-required pass classes (defensive against drift).
        o3_classes = {type(p) for p in o3_base}
        missing_from_o3 = _o2_passes - o3_classes
        if missing_from_o3:
            names = sorted(c.__name__ for c in missing_from_o3)
            raise RuntimeError(f"O3 pipeline missing O2 passes: {names}")
        return PassManager("O3-experimental", o3_base)
    raise ValueError(f"unsupported optimization level: O{opt_level}")
