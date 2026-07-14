"""Read-only compiler analyses and their cache manager."""

from .cfg import BasicBlock, CFG, CFGError, NaturalLoop, build_cfg, terminator_kind
from .liveness import LivenessFacts, LiveRange, analyze_liveness
from .manager import AnalysisError, AnalysisManager, build_default_analysis_manager
from .uniformity import (
    BranchUniformity,
    Uniformity,
    UniformityFacts,
    analyze_uniformity,
    merge_uniformity,
)

__all__ = [
    "AnalysisError",
    "AnalysisManager",
    "BasicBlock",
    "BranchUniformity",
    "CFG",
    "CFGError",
    "LivenessFacts",
    "LiveRange",
    "NaturalLoop",
    "Uniformity",
    "UniformityFacts",
    "analyze_liveness",
    "analyze_uniformity",
    "build_cfg",
    "build_default_analysis_manager",
    "merge_uniformity",
    "terminator_kind",
]
