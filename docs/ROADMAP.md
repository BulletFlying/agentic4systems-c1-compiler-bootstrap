# Roadmap

This roadmap converts the project scope into an ordered engineering plan. Implementation truth belongs in `docs/STATUS.md`.

## Phase 0: Foundation — Complete

- ISA encoding/decoding, raw `.aecbin` writer, CLI entry point
- PTX 9.3 restricted scalar subset parser
- IR module/function/block representation
- CFG, dominator, loop, and uniformity analysis
- Analysis manager with invalidation
- Pass framework with deterministic records
- Compilation report generation

## Phase 1: Basic Lowering — Complete

- `.version 9.3`, `.target sm_90`, `.address_size 64` directives
- `.visible .entry` kernel parsing
- Parameter loading through `.pmem` offsets
- Special register reads
- Integer, bitwise, shift, and FP32 scalar operations
- Global memory loads/stores
- Predicate comparisons and uniform/negated-uniform branches
- `ret` → `HALT` lowering

## Phase 2: Scalar Optimization — Complete

- Dead result elimination (conservative, per basic block)
- Basic-block-local common subexpression elimination
- Local constant folding and propagation
- Worklist-based global dead code elimination
- Global constant propagation
- Loop-invariant code motion
- Block simplification (merge, unreachable removal)
- Load hoisting and repeated load reuse
- Loop unrolling for GEMM patterns

## Phase 3: Register Allocation and Scheduling — Complete

- Virtual-to-physical GPR allocation (loop-aware linear scan)
- Predicate allocation
- Live-range tracking with multi-def splitting
- 64-bit register pair constraints
- DDG construction and dependency-preserving list scheduling

## Phase 4: FP32 Scalar GEMM — Complete

- Two-dimensional index calculation and K-loop lowering
- FP32 global load/store with multiply-add / FMA lowering
- Scalar loop optimization with register pressure management

## Phase 5: Future Work

- Spill/reload support for high register pressure
- Shared memory optimization
- Additional loop optimizations (fusion, interchange)
- Profile-guided optimization
- IDE integration / language server

## Merge Policy

A phase is complete only when implementation, tests, status ledger, and documentation agree.
