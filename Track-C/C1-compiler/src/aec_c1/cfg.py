"""Compatibility exports for the migrated CFG analysis.

New code imports :mod:`aec_c1.analysis.cfg`. This wrapper is retained only so
existing callers and the frozen bootstrap lowering continue to work during
M2.2-A.
"""

from .analysis.cfg import BasicBlock, CFG, CFGError, NaturalLoop, build_cfg, terminator_kind

__all__ = [
    "BasicBlock",
    "CFG",
    "CFGError",
    "NaturalLoop",
    "build_cfg",
    "terminator_kind",
]
