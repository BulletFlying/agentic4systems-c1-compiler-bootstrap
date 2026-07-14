"""Explicit, per-compilation analysis cache with invalidation."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from ..ir import IRModule
from .cfg import build_cfg
from .liveness import analyze_liveness
from .uniformity import analyze_uniformity


class AnalysisError(RuntimeError):
    """Raised when a pass requests an unregistered analysis."""


AnalysisProvider = Callable[[IRModule], Any]


class AnalysisManager:
    """Own analysis facts for exactly one IR module.

    Analyses are pure producers of facts. They must not mutate the module.
    Transform passes explicitly invalidate facts after changing source IR.
    """

    def __init__(self, module: IRModule, providers: Mapping[str, AnalysisProvider]) -> None:
        self._module = module
        self._providers = dict(providers)
        self._cache: dict[str, Any] = {}

    def get(self, name: str) -> Any:
        if name not in self._providers:
            raise AnalysisError(f"analysis is not registered: {name}")
        if name not in self._cache:
            self._cache[name] = self._providers[name](self._module)
        return self._cache[name]

    def invalidate(self, names: Iterable[str] | None = None) -> None:
        if names is None:
            self._cache.clear()
            return
        for name in names:
            self._cache.pop(name, None)

    @property
    def cached_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._cache))


def build_default_analysis_manager(module: IRModule) -> AnalysisManager:
    return AnalysisManager(
        module,
        {
            "cfg": lambda current: build_cfg(current.function.program),
            "liveness": lambda current: analyze_liveness(current.function.program),
            "uniformity": lambda current: analyze_uniformity(current.function.program),
        },
    )
