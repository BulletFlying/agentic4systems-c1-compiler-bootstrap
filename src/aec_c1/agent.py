"""Bootstrap agent interface for C1.

The public C1 materials do not define the final request/report schema yet. This
module keeps the command stable without claiming optimization capabilities that
are not implemented by the compiler.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def choose_config(request: dict[str, Any] | None = None) -> dict[str, Any]:
    request = request or {}
    opt_level = request.get("opt_level", "O2")
    return {
        "compiler": "aec-cc",
        "profile": "track_b_v1",
        "opt_level": opt_level,
        "pipeline": "foundation-only",
        "enabled_passes": [],
        "status": "bootstrap-default-no-optimization",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_agent")
    parser.add_argument("--input-json", type=str, default="")
    args = parser.parse_args(argv)

    try:
        if args.input_json:
            request = json.loads(args.input_json)
        else:
            raw = sys.stdin.read().strip()
            request = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        print(f"run_agent: error: invalid JSON: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(choose_config(request), sort_keys=True))
    return 0
