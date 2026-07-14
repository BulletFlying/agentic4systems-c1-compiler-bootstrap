# C1 Roadmap

This roadmap converts the active reduced C1 package into an ordered engineering plan. Implementation truth belongs in `docs/STATUS.md`.

## Roadmap principle

The new official package is simpler than the previous working assumptions, but it is still correctness-gated and hidden-test oriented. The roadmap prioritizes official syntax/ABI alignment, generalized scalar compiler analyses, and `-O2` performance improvements. A public-case filename, fixed register, fixed label, fixed loop count or fixed matrix size is never a valid implementation shortcut.

The 2026-07-14 clarifications add two active route constraints: PTX `shl.b32` must encode as AEC `SHL.u32`, and C1 does not require warp-internal divergent branch or reconvergence. Treat divergent branch programs as negative/unsupported cases, not as a feature backlog.

## Phase 0: Official package realignment

Goal: update project assumptions to the new official `spec.md`, `scoring.md`, `hint.md`, `aec-cmodel/` and manifest-based public tests.

Required work:

- Treat PTX as a restricted NVIDIA PTX 9.3 scalar subset.
- Accept `.visible .entry`, `.target sm_90` and `.address_size 64`.
- Treat `.aecbin` as raw AEC 128-bit instruction stream.
- Implement official PMEM parameter ABI and 32-bit abstract global address rule.
- Apply the 2026-07-14 `shl.b32 -> SHL.u32` output-encoding erratum.
- Treat BRX as a uniform active-lane branch; do not implement reconvergence for C1.
- Remove scoring assumptions for C1 Agent, Cycle Model, tensor ISA and low-precision GEMM.
- Make `-O2` the scoring-critical pipeline.

Status: repository/package alignment is complete; remaining work is official `aec-precise` execution evidence and deeper optimization correctness.

## Phase 1: T1 basic lowering

Goal: support public and hidden T1-style scalar kernels.

Required compiler functionality:

- PTX directives and kernel signature parsing.
- `.pred`, `.b32`, `.b64`, `.u32`, `.s32`, `.u64`, `.f32` registers.
- `ld.param.*` through official `.pmem` offsets.
- special registers including x/y/z dimensions and `%laneid`.
- integer, bitwise, shift and FP32 scalar ops.
- `shl.b32` source accepted and encoded as `SHL.u32`; `and/or/xor.b32` remain `.b32`.
- `ld.global.*`, `st.global.*`, predicates, uniform/negated-uniform branches and `ret -> HALT`.

Required evidence: manifest-aware public T1 harness, local simulator differential, `aec-precise` run when host binary is runnable, mutation coverage for parameter/grid/block/register changes, and explicit divergent-branch negative coverage.

Status: official public package lowering exists and T1-T5 execute correctly via local simulator (`pytest -m slow`). Official `aec-precise` self-test integration remains pending.

## Phase 2: T2 scalar optimization

Goal: improve scalar code on the official `-O2` path without losing correctness.

Subphase M2.1: CFG/control correctness and safe branch lowering.

Subphase M2.2-A: framework foundation: IR boundary, analysis manager, pass manager, reports, guardrails and truthful pipelines.

Subphase M2.2-B: scalar optimization passes: conservative DRE, local CSE, local constant folding, and worklist Global DCE on the scoring `-O2` path. Broader constant propagation, LICM and block simplification remain experimental until tests justify them.

Required evidence: pass-level unit tests, negative tests, mutation tests and executable differential tests; report metrics must show real pass effects. Branch-related passes must assume only uniform legal `BRX` and must not rely on divergent reconvergence semantics.

Status: M2.1 and M2.2-A are locally established. Conservative DRE, basic-block-local CSE, local constant folding and conservative worklist Global DCE exist on `-O2`. Global constant propagation, block simplification, LICM and repeated-load reuse are O3-only experimental passes with known limitations. Global CSE, scheduler, register allocation and GEMM-specific optimization are not implemented.

## Phase 3: T3 memory-access optimization

Goal: improve global-memory-heavy scalar kernels under the new T3 scope.

Required functionality:

- memory def-use and conservative alias facts.
- repeated global load detection and safe reuse.
- load hoisting where no intervening write/control hazard exists.
- simple memory reuse and address-computation optimization.
- report fields for load/store counts, memory instruction ratio and static traffic estimates.

Required evidence: public `T3_memory_reuse` harness, randomized memory-access variants, negative alias/control tests and no unsafe hoisting across stores.

Status: experimental repeated-load reuse exists only on O3 and has known boundary gaps; do not treat it as scoring-ready.

## Phase 4: T4 register allocation and scheduling

Goal: support moderate register pressure and dependency scheduling.

Required functionality:

- virtual-to-physical GPR allocation.
- predicate allocation.
- live-range tracking.
- 64-bit pair constraints.
- spill/reload contract if pressure exceeds available registers.
- DDG construction and dependency-preserving list scheduling.
- load/compute interleaving.

Required evidence: conflict checks, live-range mutation tests, pressure tests, memory-order preservation and scheduled-output correctness.

Status: not started beyond bootstrap allocation and liveness scaffolding.

## Phase 5: T5 FP32 scalar GEMM

Goal: lower and optimize scalar FP32 GEMM only. Tensor and low-precision scope is removed for C1.

Required functionality:

- two-dimensional index calculation.
- K-loop lowering.
- FP32 global load/store.
- FP32 multiply-add or FMA lowering according to source operation.
- scalar loop optimization and scheduling.
- register-pressure management for loop temporaries.

Required evidence: public `T5_scalar_gemm` harness, multiple matrix sizes, edge/boundary variants, no out-of-bounds accesses and no fixed-size pattern dispatch.

Status: public T5 compiles and passes local simulator; no GEMM-specific optimization is implemented.

## Phase 6: Optional deterministic optimization tooling and final packaging

Goal: keep useful local tooling without treating it as official scoring.

Allowed work:

- deterministic pass-policy search.
- report comparison.
- correctness-gated candidate rejection.
- final packaging checks.

This phase is optional for C1 scoring. It should not displace T1-T5 compiler implementation work.

Status: an Agent-loop PR was closed after official scope reduction; future tooling must directly improve or validate the normal `-O2` compiler path.

## Merge policy for roadmap progress

A phase is merge-ready only when implementation, tests, status ledger and documentation agree. Any unrun official `aec-precise` step must be marked as not run. No milestone may use public-case structure as a substitute for generalized compiler reasoning.
