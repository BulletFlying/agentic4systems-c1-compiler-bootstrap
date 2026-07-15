# AEC Compiler Architecture

This document defines the compiler architecture. `ARCHITECTURE_INVARIANTS.md` contains enforced invariants; this file explains design rationale and module boundaries.

## Architectural Objective

The compiler is a modular framework organized by ownership, not a collection of per-kernel lowerings.

```text
source PTX
  → frontend parser
  → typed IR module / function / block representation
  → CFG and analysis facts
  → optimization and legalization pass pipeline
  → lowering to AEC legal operations
  → register allocation and scheduling
  → AEC profile-specific encoding and binary output
  → disassembly, local simulation, reports
```

## Module Boundaries

`compiler.py` is a façade and orchestration boundary. It must not absorb lowering, register allocation, pass implementations, scheduling, or GEMM logic.

`legacy_lowering.py` is a quarantine boundary for established bootstrap lowering behavior. It may be fixed for correctness, but new optimization behavior should not be added there unless classified as a legality fix with regression coverage.

`ir/` provides the compiler representation boundary — intentionally minimal, growing toward typed operands, blocks, and def-use as needed.

`analysis/` owns read-only facts and cache invalidation through `AnalysisManager`. CFG, uniformity, liveness, memory, alias, and dominance facts belong here.

`passes/` owns pass interfaces, pass ordering, and pass records. Foundation pipelines are non-optimizing; scalar transforms enter through this package.

`reports/` owns deterministic compilation report output. The report must be truthful and reproducible.

`isa.py` owns target profiles and encoding/decoding. Extended profiles are isolated and must not pollute the default path.

`sim.py` is a local semantic checker. It must not share transform logic with the compiler.

## Dependency Direction

Allowed dependencies:

```text
compiler facade → frontend/ptx → ir → analysis → passes → lowering → backend
reports may read metrics from compiler outputs
```

Forbidden patterns:

```text
analysis → compiler
analysis → isa/backend/lowering
passes → filename/kernel-name dispatch
backend → frontend parser policy
simulator → compiler transform logic
compiler.py → optimization implementation ownership
```

## Optimization Pass Contract

Every optimization pass must satisfy:

```text
Pass.run(module, analyses) → PassResult
```

The pass must declare whether it changed the module and which analyses it invalidated. It must be testable in isolation and must not use kernel identity, filename, hash, register number, or fixed instruction position as a semantic trigger.

## Backend and Binary Output

`.aecbin` is a raw AEC 128-bit instruction stream — no header, no sections, no symbol table. Binary writing must remain isolated from instruction selection and encoding.
