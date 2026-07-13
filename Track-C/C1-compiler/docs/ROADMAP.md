# C1 Roadmap

This roadmap converts the C1 contest requirements into an ordered engineering plan. It is not a promise that every phase is complete; implementation truth belongs in `STATUS.md`.

## Roadmap principle

The official scoring is correctness-gated and hidden-test oriented. The roadmap therefore prioritizes semantic correctness, architecture stability, and generalized analyses before performance-specific transformations. A pass that only works for a public filename, fixed register number, fixed label, fixed loop trip count, or fixed instruction index is not acceptable.

## Phase 0: Repository and ISA foundation

Goal: establish a reproducible workspace, Track-B compatible encoder/decoder, command entry points, raw binary writer, disassembler, CI, governance, and architecture guardrails.

Required evidence: `aec-cc`, `aec-objdump`, and `run_agent` exist; encoder/decoder round trip exists; Track-B raw instruction smoke tests exist; official repository is not a writable remote; CI and local test commands are documented.

Status: locally established. This does not imply official `.aecbin` container compliance.

## Phase 1: M1 PTX-01 executable correctness loop

Goal: support public vector add semantics without relying on full-warp assumptions. Required compiler functionality includes parameter load layout, special registers, address computation, FP32 global load/add/store, `ret -> HALT`, partial-warp predicate handling, and no boundary-condition mixed-lane `BRX`.

Required evidence: fixed boundary sizes, random differential cases, invalid lanes produce no GMEM load/store side effects, no boundary `BRX`, and stable O0 golden binary regression.

Status: locally complete for the current bootstrap scope.

## Phase 2: M2 compiler core and T2 scalar foundation

Goal: make PTX-02 and hidden T2-style control/scalar tests a real compiler problem rather than a public-case lowering patch. Required functionality includes explicit CFG, dominators, backedges, natural loops, uniformity facts, control legalization, foundation pass pipeline, deterministic compilation report, and architecture guardrails.

Subphase M2.1: local CFG/uniform-loop correctness for PTX-02.

Subphase M2.2-A: framework foundation. `-O0`, `-O2`, and `-O3` must select explicit non-optimizing foundation pipelines, reports must list the passes actually run, and `compiler.py` must remain a façade.

Subphase M2.2-B: scalar optimization. Introduce constant folding/propagation, DCE, CSE, basic block simplify/merge, and LICM only as pass implementations with unit tests, negative tests, and executable differential tests.

Required evidence: pass-by-pass correctness tests; mutation tests for register renaming, block reorder, dead code insertion, and loop count changes; optimization metrics in reports; O0 remains a stable baseline.

Status: framework foundation is locally established; scalar optimization transforms are not implemented.

## Phase 3: M3 memory optimization

Goal: cover PTX-03 and hidden memory reuse variants. Required functionality includes memory def-use facts, alias conservatism, repeated load reuse, loop-invariant load handling, memory transaction accounting, and eventually shared-memory promotion with synchronization legality.

Required evidence: randomized reuse patterns, negative alias tests, no unsafe hoist across stores or barriers, memory metrics in reports, and local differential execution. Public PTX-03 support is not sufficient without mutation coverage.

Status: not started.

## Phase 4: M4 register allocation and scheduling

Goal: cover PTX-04 and hidden register-pressure/scheduling variants. Required functionality includes liveness, live intervals, allocation with 32/64-bit constraints, spill/reload, dependency graph construction, latency-aware list scheduling, and dual-issue pairing legality.

Required evidence: high-pressure tests, physical register conflict checks, spill address legality, dependency-preserving schedule tests, memory-order preservation, and cycle/report metrics.

Status: not started.

## Phase 5: M5 Tensor/GEMM

Goal: cover PTX-05 and hidden GEMM precision/shape variants. Required functionality includes semantic GEMM recognition, scalar fallback, f16/u16 legalization, tile selection, boundary handling, and after official clarification, tensor-profile lowering for TMUL/TLDA/TSTA if required.

Required evidence: multiple matrix sizes including non-16 boundaries, multiple precisions, no out-of-bounds access, fallback correctness, and no filename/register-based pattern detection.

Status: not started. The final Track-B scalar versus C2/B3 tensor profile boundary remains an organizer clarification item.

## Phase 6: Agent and final packaging

Goal: produce a reproducible offline Agent optimization loop and final package. The Agent must read reports/performance data, choose a configuration, recompile, verify correctness, compare performance, and emit a final optimization report.

Required evidence: independent Agent execution, report-driven configuration changes, correctness-gated candidate selection, deterministic fallback, and no claim that online LLM inference is required for correctness.

Status: stub only. Current Agent must report `foundation-only` with `enabled_passes: []` until real optimization knobs exist.

## Merge policy for roadmap progress

A phase is merge-ready only when the implementation, tests, status ledger, and documentation agree. Any unrun official Golden/Cycle Model step must be marked as not run. No future milestone may use public-case structure as a shortcut around generalized compiler reasoning.
