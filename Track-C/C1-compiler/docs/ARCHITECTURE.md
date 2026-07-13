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
  -> disassembly, local simulation, reports, and Agent feedback
```

The key design constraint is separation of ownership. Analysis computes facts. Passes transform IR through declared contracts. Lowering enforces target legality. Backend code encodes or packages instructions. The Agent selects configurations from reports and validation results; it must not rewrite compiler internals at evaluation time.

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

`reports/` owns deterministic compilation report output. The report is the future Agent observation surface, so it must be truthful and reproducible.

`isa.py` owns target profiles and encoding/decoding. Track-B and C2/B3 profile facts must remain separate.

`sim.py` is a local semantic checker. It must not share transform logic with the compiler and is not a replacement for the official Golden Model.

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

## Backend and object packaging

The encoder currently supports Track-B raw 128-bit instruction bytes and keeps a C2/B3 profile boundary. The official C1 `.aecbin` container is still an unresolved requirement because the public spec says the output must include Header, Code, Data, Relocation, and Symbol Table, but the precise layout is not yet implemented in this bootstrap branch.

Object packaging must eventually be isolated from instruction encoding. A future `object.py` or `backend/object_writer.py` should support raw Track-B compatibility, any C2 image form used for reference, and the final C1 container once clarified.

## Agent boundary

The Agent is not part of core lowering. It observes reports and validation results, proposes a configuration, invokes the compiler, verifies correctness, compares performance, and records the result. It may use an LLM for exploration outside the correctness boundary, but the evaluated Agent loop must be reproducible and must not depend on online LLM availability.
