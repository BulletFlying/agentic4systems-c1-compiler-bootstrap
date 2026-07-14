"""Public C1 compiler façade and explicit pass-pipeline orchestration."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys

from .analysis import build_default_analysis_manager
from .ir import module_from_program
from .isa import PROFILES, TRACK_B_V1, ISAProfile
from .legacy_lowering import CompileError, LoweredProgram, Lowerer
from .legacy_lowering import write_binary as _write_binary
from .passes import build_pipeline
from .ptx import PTXParseError, parse_ptx
from .reports import CompilationReport, PERFORMANCE_TARGETS, build_metrics


@dataclass(frozen=True)
class CompilationResult:
    lowered: LoweredProgram
    report: CompilationReport


def compile_ptx_detailed(
    text: str,
    profile: ISAProfile = TRACK_B_V1,
    *,
    opt_level: str = "0",
    input_name: str = "<memory>",
    output_name: str = "",
    performance_target: str = "aec_slide_constraints",
) -> CompilationResult:
    if performance_target not in PERFORMANCE_TARGETS:
        raise ValueError(f"unsupported performance target: {performance_target}")

    program = parse_ptx(text)
    module = module_from_program(text, program)
    analyses = build_default_analysis_manager(module)
    pipeline = build_pipeline(opt_level)
    pass_records = pipeline.run(module, analyses)

    # The pass-updated IR program is authoritative for lowering. O0 leaves it
    # unchanged; O2/O3 may apply explicitly recorded conservative transforms.
    reg_mapping = module.metadata.get("register_mapping")
    lowered = Lowerer(module.function.program, profile=profile,
                      register_mapping=reg_mapping).lower()
    # Post-lowering scheduler (O2 proven-safe — STORE→LOAD barrier prevents alias violations)
    if opt_level in ("2", "3"):
        try:
            from .passes.scheduler import schedule_lowered
            lowered = schedule_lowered(lowered, module)
        except Exception:
            pass
    report = CompilationReport(
        input=input_name,
        output=output_name,
        optimization=opt_level,
        profile=profile.name,
        pipeline=pipeline.name,
        passes=pass_records,
        metrics=build_metrics(module, lowered, pass_records),
        performance_target=performance_target,
    )
    return CompilationResult(lowered=lowered, report=report)


def compile_ptx(
    text: str,
    profile: ISAProfile = TRACK_B_V1,
    *,
    opt_level: str = "0",
) -> LoweredProgram:
    """Compile PTX while preserving the established public Python API."""

    return compile_ptx_detailed(text, profile, opt_level=opt_level).lowered


def write_binary(lowered: LoweredProgram, output: Path, profile: ISAProfile) -> None:
    _write_binary(lowered, output, profile)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aec-cc")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    parser.add_argument("-O", "--opt-level", default="0", choices=["0", "2", "3"])
    parser.add_argument("--profile", choices=sorted(PROFILES), default=TRACK_B_V1.name)
    parser.add_argument("--performance-target", choices=PERFORMANCE_TARGETS, default="aec_slide_constraints")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    try:
        profile = PROFILES[args.profile]
        result = compile_ptx_detailed(
            args.input.read_text(encoding="utf-8"),
            profile,
            opt_level=args.opt_level,
            input_name=args.input.as_posix(),
            output_name=args.output.as_posix(),
            performance_target=args.performance_target,
        )
        write_binary(result.lowered, args.output, profile)
        if args.report is not None:
            result.report.write(args.report)
    except (OSError, CompileError, PTXParseError, ValueError) as exc:
        print(f"aec-cc: error: {exc}", file=sys.stderr)
        return 1
    return 0
