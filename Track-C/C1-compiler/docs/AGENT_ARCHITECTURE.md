# C1 Agent Architecture

This document defines the target Agent design for C1. It deliberately separates an optimization Agent from a chat assistant or code-writing LLM.

## Agent goal

The Agent exists to improve generated-code performance through an automated, correctness-gated feedback loop. It should observe compiler reports and benchmark results, propose a compilation configuration, recompile, verify correctness, compare performance, and record the final decision.

The Agent is part of the C1 scoring path only when it changes compiler configuration based on measured evidence. Returning a static JSON object is a command stub, not an optimizing Agent.

## Required loop

The final Agent loop should be:

```text
input workload / report
  -> read current compiler capabilities
  -> select candidate configuration
  -> run compiler
  -> run validator / local or official checker
  -> reject incorrect candidate
  -> read cycle/performance report
  -> compare against default
  -> update search state
  -> emit final config and optimization report
```

The official loop-completeness expectation is: independent run, read performance report, recompile with adjusted configuration, verify result, and generate final optimization report.

## Components

Planner: chooses the search scope for the current benchmark family and optimization level.

Pass selector: enables or disables implemented passes only. It must not claim `DCE`, `CSE`, `LICM`, scheduling, or GEMM passes until those passes exist and are wired into the compiler.

Parameter selector: chooses safe compiler parameters such as optimization level, pass order, tiling options, unroll limits, or scheduling policies after those options are implemented.

Benchmark runner: invokes `aec-cc`, captures reports, invokes validation, and records failure reasons.

Analyzer: reads deterministic compilation reports, correctness status, and performance metrics such as cycles, instruction count, spill count, dual issue rate, memory transactions, and stalls when available.

Knowledge base: stores candidate outcomes and avoids retrying known-bad configurations.

Final reporter: emits a reproducible summary of selected configuration, evidence, rejected candidates, correctness status, and performance comparison.

## LLM policy

Online LLM inference is not required for correctness. It may be useful outside the evaluation loop for planning or human-assisted exploration, but the evaluated Agent must be reproducible and must not depend on network access.

A valid Agent may be a deterministic search program. An LLM wrapper that cannot run, verify, and compare compiler outputs is not sufficient.

## Current stub contract

Until real optimization passes and performance reports exist, the Agent must remain truthful:

```json
{
  "pipeline": "foundation-only",
  "enabled_passes": [],
  "status": "bootstrap-default-no-optimization"
}
```

It must not return flags implying that constant propagation, DCE, CSE, LICM, scheduling, or GEMM optimization are active.

## Future configuration surface

The Agent may eventually control:

```json
{
  "opt_level": "O2",
  "enabled_passes": ["constant-fold", "dce"],
  "pass_order": ["constant-fold", "dce", "simplify-cfg"],
  "licm": {"enabled": true, "max_loop_depth": 2},
  "scheduler": {"policy": "latency-aware-list"},
  "gemm": {"tile_m": 16, "tile_n": 16, "tile_k": 32}
}
```

This schema is illustrative only. A field becomes legal only after the compiler implements it, tests it, and reports it truthfully.

## Safety rules

The Agent must never select behavior from public filenames or test IDs. It must never accept a faster candidate that fails correctness. It must never mutate compiler source code during evaluation. It must not hide failed candidates; failures are part of the optimization report.
