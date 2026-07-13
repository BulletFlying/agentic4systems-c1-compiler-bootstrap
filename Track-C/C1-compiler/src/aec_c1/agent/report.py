"""Stable decision-log serialization for the deterministic controller."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def decision_log_json(decision: dict[str, Any]) -> str:
    return json.dumps(decision, indent=2) + "\n"


def write_decision_log(decision: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(decision_log_json(decision), encoding="utf-8")
