"""Explicit compiler pass framework."""

from .base import CompilerPass, PassResult
from .manager import PassManager, PassRecord
from .pipelines import build_pipeline
from .scalar import (
    BasicBlockLocalCSEPass,
    ConservativeDeadResultEliminationPass,
    LocalConstantFoldingPass,
)

__all__ = [
    "BasicBlockLocalCSEPass",
    "CompilerPass",
    "ConservativeDeadResultEliminationPass",
    "LocalConstantFoldingPass",
    "PassManager",
    "PassRecord",
    "PassResult",
    "build_pipeline",
]
