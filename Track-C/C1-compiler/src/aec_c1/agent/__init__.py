"""Deterministic C1 optimization controller entry points."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from ..isa import PROFILES, TRACK_B_V1
from ..reports import PERFORMANCE_TARGETS
from .controller import choose_config, run_optimization_loop
from .report import decision_log_json, write_decision_log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_agent")
    parser.add_argument("input", nargs="?", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--profile", choices=sorted(PROFILES), default=TRACK_B_V1.name)
    parser.add_argument("--performance-target", choices=PERFORMANCE_TARGETS, default="aec_slide_constraints")
    parser.add_argument("--input-json", type=str, default="")
    args = parser.parse_args(argv)

    try:
        if args.input is None:
            request = _read_config_request(args.input_json)
            print(json.dumps(choose_config(request), sort_keys=True))
            return 0

        profile = PROFILES[args.profile]
        decision = run_optimization_loop(
            args.input.read_text(encoding="utf-8"),
            input_name=args.input.as_posix(),
            profile=profile,
            performance_target=args.performance_target,
        )
        if args.output is None:
            print(decision_log_json(decision), end="")
        else:
            write_decision_log(decision, args.output)
    except (OSError, ValueError) as exc:
        print(f"run_agent: error: {exc}", file=sys.stderr)
        return 1
    return 0


def _read_config_request(input_json: str) -> dict[str, object] | None:
    if input_json:
        return json.loads(input_json)
    try:
        raw = sys.stdin.read().strip()
    except OSError:
        return None
    return json.loads(raw) if raw else None


__all__ = [
    "choose_config",
    "decision_log_json",
    "main",
    "run_optimization_loop",
    "write_decision_log",
]
