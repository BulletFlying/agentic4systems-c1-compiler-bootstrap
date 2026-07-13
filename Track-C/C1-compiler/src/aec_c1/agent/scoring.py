"""Deterministic static-metric ranking for optimization candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, order=True)
class Score:
    machine_instruction_count: int
    branch_count: int
    estimated_gmem_128b_services_per_warp: int


def score_from_metrics(metrics: dict[str, Any]) -> Score:
    static_metrics = metrics.get("static_metrics", {})
    return Score(
        machine_instruction_count=int(metrics.get("machine_instruction_count", 0)),
        branch_count=int(metrics.get("branch_count", 0)),
        estimated_gmem_128b_services_per_warp=int(
            static_metrics.get("estimated_gmem_128b_services_per_warp", 0)
        ),
    )


def metric_summary(metrics: dict[str, Any]) -> dict[str, int]:
    score = score_from_metrics(metrics)
    return {
        "machine_instruction_count": score.machine_instruction_count,
        "branch_count": score.branch_count,
        "estimated_gmem_128b_services_per_warp": score.estimated_gmem_128b_services_per_warp,
    }
