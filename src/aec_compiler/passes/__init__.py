"""Explicit compiler pass framework."""

from .base import CompilerPass, PassResult
from .manager import PassManager, PassRecord
from .pipelines import build_pipeline
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

__all__ = [
    "BasicBlockLocalCSEPass",
    "BlockSimplificationPass",
    "CompilerPass",
    "ConservativeDeadResultEliminationPass",
    "GlobalConstantPropagationPass",
    "GlobalDeadCodeEliminationPass",
    "LocalConstantFoldingPass",
    "LoopInvariantCodeMotionPass",
    "PassManager",
    "PassRecord",
    "PassResult",
    "RepeatedGlobalLoadReusePass",
    "build_pipeline",
]
