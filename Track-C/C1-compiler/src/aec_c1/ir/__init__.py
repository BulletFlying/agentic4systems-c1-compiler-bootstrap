"""Minimal executable compiler IR used by the M2.2 pass framework."""

from .model import IRBlock, IRFunction, IRModule, module_from_program

__all__ = ["IRBlock", "IRFunction", "IRModule", "module_from_program"]
