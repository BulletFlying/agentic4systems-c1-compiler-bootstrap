# C1 Compiler Architecture

This document defines the intended compiler architecture for C1. `ARCHITECTURE_INVARIANTS.md` contains the enforced invariants; this file explains the design rationale and long-term module boundaries.

## Architectural objective

The compiler must remain a compiler framework, not a collection of per-testcase lowerings. The target flow is:

```text
source PTX-style IR
  -> frontend parser
  -> typed IR module / function / block representation
  -> CFG and analysis facts
  -> optimization and legalization pass pipeline
  -> lowering to AEC legal operations
  -> register allocation and scheduling
  -> AEC profile-specific encoding and object packaging
  -> disassembly, local simulation, reports, and optional tooling feedback
```

The key design constraint is separation of ownership. Analysis computes facts. Passes transform IR through declared contracts. Lowering enforces target legality. Backend code encodes the official raw `.aecbin` instruction stream. Optional report-driven tooling may select configurations from reports and validation results, but it must not rewrite compiler internals at evaluation time and is not an official C1 scoring category.

## Current M2.2-A architecture

The current foundation intentionally keeps legacy lowering isolated while introducing the framework needed for real passes.

```text
compiler.py
  -> parse_ptx
  -> module_from_program
  -> build_default_analysis_manager
  -> build_pipeline(-O0/-O2/-O3)
  -> pipeline.run(module, analyses)
  -> legacy_lowering.Lowerer(...).lower()
  -> CompilationReport
  -> write_binary
```

`compiler.py` is a façade and orchestration boundary. It must not reabsorb `Lowerer`, `RegisterAllocator`, `ControlPlan`, pass implementations, scheduling, or GEMM logic.

`legacy_lowering.py` is a quarantine boundary for established bootstrap lowering behavior. It may be fixed for correctness, but new optimization behavior should not be added there unless the change is explicitly classified as a legality fix with regression coverage.

`ir/` provides the compiler representation boundary. In the current foundation it is intentionally minimal. As scalar optimization begins, it must grow toward typed operands, blocks, def-use, and eventually SSA only when the pass actually requires them.

`analysis/` owns read-only facts and cache invalidation through `AnalysisManager`. Existing CFG and uniformity facts live here. Future liveness, memory, alias, and dominance facts belong here, not inside `compiler.py`.

`passes/` owns pass interfaces, pass ordering, and pass records. Foundation pipelines are non-optimizing; scalar transforms must later enter through this package.

`reports/` owns deterministic compilation report output. The report is the participant-side performance-model and optional tooling observation surface, so it must be truthful and reproducible.

`isa.py` owns target profiles and encoding/decoding. The default C1 path follows the current official C1 `spec.md`; any historical Track-B or C2/B3 profile facts must remain isolated and must not reintroduce Tensor/TMUL scope into C1.

`sim.py` is a local semantic checker. It must not share transform logic with the compiler and is not a replacement for the official `aec-precise` CModel.

## Dependency direction

Allowed high-level dependencies:

```text
compiler facade -> frontend/ptx -> ir -> analysis -> passes -> lowering -> backend/target
reports may read metrics from compiler outputs
agent may read reports and invoke compiler entry points
```

Forbidden dependency patterns:

```text
analysis -> compiler
analysis -> isa/backend/lowering
passes -> filename/testcase dispatch
backend -> frontend parser policy
simulator -> compiler transform logic
compiler.py -> optimization implementation ownership
```

Relative imports must preserve the same direction as absolute imports. A relative import such as `from ..isa import X` inside `analysis/` is still an analysis-to-backend dependency violation.

## Control-flow legality

AEC `BRX` cannot be treated as an arbitrary PTX branch replacement when the condition may vary across lanes. The compiler must prove a branch predicate uniform before generating direct `BRX`, or else convert the region to predicated instructions / if-conversion when it is semantically safe. Unknown uniformity is not uniformity.

The current `legacy_varying_branch_items` path is a compatibility escape hatch, not a general correctness strategy. It must be removed or tightly bounded before correctness claims expand to PTX-03, PTX-04, and PTX-05.

## Optimization pass contract

Every real optimization pass must satisfy this contract:

```text
Pass.run(module, analyses) -> PassResult
```

The pass must declare whether it changed the module and which analyses it invalidated. It must be testable in isolation, and it must not use public testcase identity, filename, hash, register number, or fixed instruction position as a semantic trigger.

The order for adding a new optimization is:

```text
IR capability if needed
analysis fact if needed
pass implementation
unit and negative tests
executable differential tests
report metrics
status update
```

## Backend and binary packaging

The reduced official C1 `.aecbin` format is now defined as a raw AEC 128-bit instruction stream. There is no Header, Data section, Relocation section or Symbol Table in the current C1 format.

Binary writing must remain isolated from instruction selection and encoding so legality checks stay reviewable: file size must be a nonzero multiple of 16 bytes, labels must be resolved before writeout, branch targets must be in range, and encoded opcode/type/space/register/predicate fields must stay within the official C1 limits.

## Optional tooling boundary

Agent/controller code is not part of official C1 scoring after the 2026-07-13 reduction. If retained, it is optional development tooling: it may observe reports and validation results, propose a configuration, invoke the compiler, verify correctness, compare local static/performance-model metrics, and record the result. It must not become a required evaluation entry point or distract from the scoring-critical `-O2` compiler path.
