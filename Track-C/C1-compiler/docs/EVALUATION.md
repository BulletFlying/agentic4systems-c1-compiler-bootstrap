# C1 Evaluation Mapping

This document maps repository work to the active reduced official C1 scoring package observed on 2026-07-13. Local C1 package files are LF-normalized text-content-equivalent to official `main` (dce818b, 2026-07-14).

## Official score model

The active C1 score is 100 points:

| Official category | Points | Engineering meaning |
|---|---:|---|
| A. Compile and execution correctness | 50 | Produce a valid raw `.aecbin`, execute it under the evaluator, and match the manifest-defined output |
| B. Generated code efficiency | 40 | Improve correct cases against the official baseline compiler |
| C. Generalization and robustness | 10 | Survive 50 mutation variants without public-case assumptions |

There is no official C1 Agent score in the new `scoring.md`.

The evaluator runs:

```bash
compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json
```

`-O2` is therefore the scoring-critical pipeline. `-O0` may remain as a local regression baseline, but it is not the official scoring invocation.

Organizer clarification on 2026-07-13 adds that the compiler timeout remains 180 seconds, `compiler/aec-cc` may be a script/Python entry point, and the evaluation environment has `python3`.

## Correctness mapping

Correctness is evaluated on 100 hidden tests, 20 per family:

| Category | Hidden tests | Public package family | Required capabilities |
|---|---:|---|---|
| T1 basic lowering | 20 | `T1_basic_lowering` | PTX 9.3 restricted scalar parsing, params, special registers, arithmetic, global load/store, branch, `ret -> HALT` |
| T2 scalar optimization | 20 | `T2_scalar_optimization` | constants, dead-code deletion, CSE, LICM, basic-block merge/simplification |
| T3 memory access optimization | 20 | `T3_memory_reuse` | global memory access, repeated loads, load hoisting, simple reuse, address-computation optimization |
| T4 register allocation and scheduling | 20 | `T4_register_scheduling` | GPR/predicate allocation, live-range management, register pressure, load/compute interleaving, dependency scheduling |
| T5 FP32 scalar GEMM | 20 | `T5_scalar_gemm` | FP32 scalar GEMM, 2D indexing, K-loop lowering, address computation, scalar multiply-add scheduling |

Each testcase is described by `kernel.ptx` plus `manifest.json`. The manifest specifies kernel name, grid/block dimensions, parameters, buffers and output checking. Repository tests should therefore move from single-file assumptions toward manifest-aware execution scaffolding.

## Performance mapping

Performance is computed only for correctness-passing cases. The official evaluator compares participant output to the official baseline compiler:

```text
r_i = baseline_i / participant_i
```

The lower participant metric is better. Category performance uses geometric-mean speedup and maps to score bands. Performance weights are:

| Category | Performance points | What must improve |
|---|---:|---|
| T1 | 0 | correctness only |
| T2 | 8 | scalar redundancy, loop invariants, block simplification |
| T3 | 10 | memory-instruction reduction, load reuse, hoisting, address optimization |
| T4 | 10 | register pressure, live ranges, dependency scheduling, load/compute interleaving |
| T5 | 12 | FP32 scalar GEMM address/loop/multiply-add optimization |

The public `Track-C/C1-compiler/hint.md` target table and local static report metrics are guidance for building a performance model. They are not an official Cycle Model replacement. Organizer clarification says the official performance metric is closer to warp-level dynamic execution instruction/step count than to a latency-weighted cycle simulation. The released `aec-precise` docs expose stdout JSON `steps` for this purpose.

## Diagnostic report fields

The new scoring document lists these non-direct-scoring diagnostics:

```text
instruction_count
register_count
predicate_count
spill_count
branch_count
load_count
store_count
memory_instruction_ratio
estimated_dependency_depth
```

Repository compile reports should prioritize these fields, while keeping older static metrics only when useful and clearly labeled.

## Robustness mapping

Robustness uses 50 variants: 10 variants per T1-T5 family. The new official mutation dimensions include:

```text
parameter scale changes
grid/block dimension changes
register renaming
basic-block order changes
loop-count changes
dead-code insertion
irrelevant computation insertion
register-pressure increase
address-computation changes
memory-access-pattern changes
scalar GEMM size changes
```

Forbidden semantic dispatch triggers in compiler, lowering, backend and pass code remain:

```text
filename / public testcase directory / source hash / fixed register / fixed label / fixed instruction index / fixed public matrix size
```

Tests and docs may mention public cases. Production compiler logic may not use them to select semantics.

## Removed or downgraded old evaluation assumptions

These are no longer active C1 scoring requirements under the reduced package:

- Agent performance score and loop-completeness score.
- AEC Cycle Model availability for participants.
- TMUL, Tensor Load/Store, tensor registers, tensor tiling and low-precision GEMM.
- FP4, FP8, BF16, FP16, INT4, INT8 or INT32 GEMM hidden precision matrix.
- Header/Data/Relocation/Symbol object container for `.aecbin`.

Agent work may still be useful as optional local automation, but it is not score-aligned unless it improves the normal `-O2` compiler pipeline and does not become a separate required entry point.

## Evidence tiers

Tier 0: static evidence. Examples: `compileall`, import graph checks, architecture guardrails, line-count checks.

Tier 1: unit evidence. Examples: parser behavior, encoder fields, analysis cache, pass manager ordering, report determinism.

Tier 2: executable local evidence. Examples: local simulator differential tests, O0/O2 binary regression, public manifest harness.

Tier 3: official CModel evidence. The released `aec-cmodel/` package contains `aec-precise-linux-x86_64`, `aec-precise-macos-arm64`, `USAGE.md` and `PUBLIC_AEC_PRECISE_COMMANDS.md`. Record exact command, binary path and result when used.

Tier 4: performance-model evidence. Examples: static report comparison, baseline-vs-candidate comparison, auxiliary real-GPU profiling clearly labeled as non-official.

A PR must say which tier was actually run. Do not write “official correctness passed” until official `aec-precise` has actually run.

## Merge readiness checklist

A change is score-aligned only if it answers:

1. Which T1-T5 family does it target?
2. Does it affect the official `-O2` path?
3. What correctness evidence exists?
4. What mutation/generalization evidence exists?
5. Does it update deterministic reports truthfully?
6. Does it preserve architecture guardrails?
7. Does it avoid public-case semantic dispatch?
8. Was official `aec-precise` unavailable, not run, failed, or passed?
