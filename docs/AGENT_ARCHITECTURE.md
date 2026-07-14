# C1 Optional Optimization Controller

The reduced official C1 scoring package no longer includes an Agent score. This document therefore defines Agent/controller code as optional repository tooling, not as an official C1 requirement.

## Current role

A deterministic controller may still be useful to compare compiler pass configurations, run local correctness gates and emit decision logs. It must not be used to claim an official Agent score, and it must not distract from the scoring-critical `-O2` compiler path.

The official evaluator invokes:

```bash
compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json
```

Therefore any optional controller work is valuable only when it helps improve or validate the normal compiler pipeline.

## Valid optional loop

A safe local controller may:

```text
read a PTX kernel and manifest context if available
  -> compile baseline and candidate pass configurations
  -> run local/official correctness gates where available
  -> reject incorrect candidates
  -> compare deterministic static metrics or auxiliary performance data
  -> emit a machine-readable decision log
```

It must not mutate compiler source code during evaluation. It must not require network access or online LLM inference. It must not use public testcase names, filenames, fixed registers, fixed labels, hashes or public matrix sizes as semantic triggers.

## LLM boundary

Online LLM inference is not required for C1. It may be useful outside the evaluated compiler path for human planning, but the repository baseline should remain deterministic and offline.

A wrapper that calls an LLM but cannot compile, verify and compare outputs is not meaningful compiler optimization infrastructure.

## Truthfulness contract

The controller may enable only passes that actually exist and are wired into the compiler. It must not claim general DCE, global CSE, LICM, scheduling, register allocation, memory optimization or GEMM optimization until those components are implemented and tested.

Valid pass labels should correspond to implemented pass records such as:

```json
{
  "enabled_passes": [
    "conservative-dead-result-elimination",
    "basic-block-local-cse",
    "local-constant-folding"
  ]
}
```

When no optimization is selected or no safe candidate improves the chosen metric, the controller should say so explicitly rather than fabricating progress.

## Relationship to open work

Any PR that implements a deterministic optimization loop should be reviewed as optional development tooling. It should not be treated as completing an official M6 milestone, because the new C1 `scoring.md` has no Agent category.
