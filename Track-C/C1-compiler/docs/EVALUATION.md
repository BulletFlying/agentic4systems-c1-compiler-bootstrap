# C1 Evaluation Mapping

This document maps repository work to official C1 scoring. It prevents work that looks useful but does not improve the contest deliverable.

## Official score model

The official C1 score is 100 points:

| Official category | Points | Engineering meaning |
|---|---:|---|
| A. Compile and execution correctness | 50 | Generate valid AEC binary and match Golden Model output |
| B. Generated code efficiency | 35 | Reduce AEC Cycle Model `total_cycles` on correct cases only |
| C. Generalization and robustness | 5 | Survive automatic mutation variants, not only public PTX shape |
| D. Agent optimization | 10 | Use an automated loop to improve performance and report the result |

Correctness gates performance. If a compiled binary fails validation or Golden Model comparison, that case contributes no performance score.

The C1 slide-deck scoring details are:

```text
correctness = T1*4 + T2*8 + T3*10 + T4*12 + T5*16
performance = 35 points, main metric AEC Cycle Model total cycles
robustness = 5 points across 50 mutation tests
agent = 8 performance points + 2 loop-completeness points
```

## Correctness mapping

Official correctness uses 100 hidden tests across five categories.

| Category | Hidden tests | Public representative | Required compiler capabilities |
|---|---:|---|---|
| T1 basic lowering | 20 | PTX-01 vector_add | parser, parameter ABI, arithmetic, global load/store, predicates, binary encoding |
| T2 control/scalar | 20 | PTX-02 invariant_poly | CFG, predicates, uniformity, DCE, CSE, LICM, block simplification |
| T3 memory | 20 | PTX-03 repeated_reuse | memory facts, reuse, coalescing, shared-memory legality |
| T4 register/scheduling | 20 | PTX-04 reg_schedule | liveness, register allocation, spill, DDG, list scheduling, dual issue |
| T5 Tensor/GEMM | 20 | PTX-05 gemm_f16 | GEMM detection, precision handling, tiling, tensor load/store or scalar fallback |

Current local tests are not equivalent to official correctness. They are necessary bootstrap evidence only. Official Golden Model, Cycle Model, validator, and final object format remain external blockers unless later added to the repository.

The public C1 benchmark set shown in the slide deck is:

```text
PTX-01 vector_add
PTX-02 invariant_poly
PTX-03 repeated_reuse
PTX-04 reg_schedule
PTX-05 gemm_f16
```

## Performance mapping

Official performance uses the AEC Cycle Model `total_cycles`. Diagnostic metrics such as `instruction_count`, `spill_count`, `dual_issue_rate`, `memory_transactions`, and `stall_cycles` are useful for debugging but are not themselves the final score.

| Category | Performance points | What must eventually improve |
|---|---:|---|
| T1 | 0 | correctness only |
| T2 | 5 | scalar redundancy, loop invariants, block simplification |
| T3 | 9 | memory transactions and reuse |
| T4 | 10 | register pressure, spills, latency hiding, dual issue |
| T5 | 11 | GEMM tiling, tensor/scalar mapping, precision and boundary handling |

No performance claim is valid unless the same case is correct. A faster wrong binary is a regression.

The slide-deck normalization formula is:

```text
r_{g,i} = T^{base}_i / T_{g,i}
p(r) = clip((log r - log 0.5) / (log 2 - log 0.5), 0, 1)
```

Interpretation:

```text
<= 0.5x baseline speed -> 0%
1.0x baseline speed    -> 50%
>= 2.0x baseline speed -> 100%
```

## Robustness mapping

Official robustness uses 50 mutation variants. Mutations include parameter changes, register renaming, basic-block reorder, loop-trip changes, dead-code insertion, register-pressure increase, PTX-05 data-type changes, and memory-reuse pattern changes.

Repository guardrails and tests must therefore reject hard-coded public-case behavior. The following are forbidden as semantic dispatch triggers in compiler, lowering, backend, and pass logic:

```text
filename / testcase / PTX-01..PTX-05 / source hash / fixed register / fixed label / fixed instruction index
```

Tests and docs may mention public case names. Compiler logic may not use them to choose semantics.

## Agent mapping

Official Agent score is 10 points: 8 for performance improvement and 2 for loop completeness. The Agent must independently run, read a performance report, adjust compilation configuration, recompile, verify results, and generate a final optimization report.

The slide-deck Agent performance metric is:

```text
GM_agent = (product r_i^agent)^(1/10)
```

`GM_agent >= 1.25` receives the full Agent performance score. The remaining loop-completeness points require independent execution, report reading, recompilation, verification, and final report generation.

The Agent does not need online LLM inference for correctness. LLM-assisted exploration is optional and outside the reproducible evaluation boundary. The evaluated behavior must be deterministic enough to reproduce and must not claim unimplemented passes.

Current status: the Agent is a truthful bootstrap stub with `enabled_passes: []` and `pipeline: foundation-only`. It is not yet an optimizing Agent.

## Evidence tiers

Use the following evidence tiers when writing PR descriptions or status updates.

Tier 0: static evidence. Examples: `compileall`, import graph checks, architecture guardrails, line-count checks.

Tier 1: unit evidence. Examples: parser behavior, encoder fields, analysis cache, pass manager ordering, report determinism.

Tier 2: executable local evidence. Examples: simulator differential tests for PTX-01/PTX-02, invalid-lane GMEM side-effect checks, O0 golden binary hash.

Tier 3: official-model evidence. Examples: official binary validator, Golden Model comparison, Cycle Model `total_cycles`. This tier is currently not available in the public bootstrap repository.

Tier 4: Agent-loop evidence. Examples: report-driven candidate search, correctness-gated recompile, measured performance comparison, final optimization report.

A merge can improve local engineering state without increasing official readiness. The PR must state which tier was actually run.

## Merge readiness checklist

A change is not score-aligned unless it answers these questions:

1. Which official category and testcase family does it target?
2. What correctness evidence exists?
3. What mutation/generalization evidence exists?
4. Does it change O0 behavior or only O2/O3 behavior?
5. Does it update deterministic reports and status docs truthfully?
6. Does it preserve architecture guardrails?
7. Does it avoid public-case semantic dispatch?
8. Was the official Golden/Cycle Model unavailable, not run, or passed?
