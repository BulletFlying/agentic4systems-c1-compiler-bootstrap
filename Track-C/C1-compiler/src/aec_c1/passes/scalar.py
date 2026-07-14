"""Scalar optimization passes — backward-compatibility re-exports.

The pass implementations have been split into focused modules:
  local_scalar.py  — Conservative DRE, BB-local CSE, local constant folding (O2)
  global_dce.py    — Worklist-based global dead code elimination (O2)
  experimental.py  — Global CP, LICM, block simplification, load reuse (O3 only)
  _helpers.py      — Shared constants and helper functions (private)

New code should import from the specific modules.  This file exists so
existing callers don't break.
"""

from .experimental import (
    BlockSimplificationPass,
    GlobalConstantPropagationPass,
    LoopInvariantCodeMotionPass,
    RepeatedGlobalLoadReusePass,
)
from .global_dce import GlobalDeadCodeEliminationPass
from .local_scalar import (
    BasicBlockLocalCSEPass,
    ConservativeDeadResultEliminationPass,
    LocalConstantFoldingPass,
)

__all__ = [
    "BasicBlockLocalCSEPass",
    "BlockSimplificationPass",
    "ConservativeDeadResultEliminationPass",
    "GlobalConstantPropagationPass",
    "GlobalDeadCodeEliminationPass",
    "LocalConstantFoldingPass",
    "LoopInvariantCodeMotionPass",
    "RepeatedGlobalLoadReusePass",
]
