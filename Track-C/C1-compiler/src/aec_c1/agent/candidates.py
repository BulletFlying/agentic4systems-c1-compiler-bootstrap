"""Finite optimization candidates for the deterministic controller."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateConfig:
    name: str
    passes: tuple[str, ...]


DEFAULT_CANDIDATES = (
    CandidateConfig(name="baseline", passes=()),
    CandidateConfig(name="dre", passes=("conservative-dead-result-elimination",)),
    CandidateConfig(
        name="dre_cse",
        passes=("conservative-dead-result-elimination", "basic-block-local-cse"),
    ),
    CandidateConfig(
        name="dre_cse_cf",
        passes=(
            "conservative-dead-result-elimination",
            "basic-block-local-cse",
            "local-constant-folding",
        ),
    ),
)
