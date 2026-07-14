"""Scalar optimization passes — backward-compatibility re-exports.

The pass implementations have been split into focused modules:
  local_scalar.py   — Conservative DRE, BB-local CSE, local constant folding (O2)
  global_dce.py     — Worklist-based global dead code elimination (O2)
  global_cp.py      — Global constant propagation (O2)
  block_simplify.py — Block simplification (O2)
  licm.py           — Loop-invariant code motion (O2)
  experimental.py   — Repeated global load reuse (O2)
  _helpers.py       — Shared constants and helper functions (private)

New code should import from the specific modules.  This file exists so
existing callers don't break.
"""

from .block_simplify import BlockSimplificationPass
from .experimental import RepeatedGlobalLoadReusePass
from .global_cp import GlobalConstantPropagationPass
from .global_dce import GlobalDeadCodeEliminationPass
from .licm import LoopInvariantCodeMotionPass
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
