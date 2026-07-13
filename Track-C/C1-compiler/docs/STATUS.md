# C1 Compiler Status

This file is the mutable implementation ledger for `Track-C/C1-compiler/`. Long-term goals and scoring constraints live in `C1_PROJECT_CHARTER.md`; operating rules live in `../AGENTS.md` and `DEVELOPMENT_POLICY.md`.

## Snapshot

Status date: 2026-07-13

Writable repository: `BulletFlying/agentic4systems-c1-compiler-bootstrap`

Local Git remote policy: only `origin` pointing to `BulletFlying/agentic4systems-c1-compiler-bootstrap`

Official repository remote: not configured

Organizer performance clarification recorded in `docs/PERFORMANCE_MODEL.md`: Track-C performance optimization should build a model from NVIDIA-like target-hardware indicators and use it to reason about compute, memory and data-movement bottlenecks. Slide-derived target-hardware indicators are now recorded; the official Cycle Model schema is still unavailable.

## Milestone state

| Milestone | State | Evidence boundary |
|---|---|---|
| M0 ISA/CLI/encoder baseline | Locally complete | Track-B raw encoder, decoder, objdump and smoke checks exist |
| M1 PTX-01 correctness loop | Locally complete | Partial-warp and randomized differential tests exist |
| M2.1 PTX-02 CFG/uniform-loop correctness | Locally complete | CFG, dominators, uniformity analysis and executable tests exist |
| M2.2 architecture foundation | Locally complete | IR facade, analysis manager, pass manager, reports, foundation pipelines, architecture guardrails and O0 binary golden fixtures exist |
| M2.2 scalar optimization | Not started | No real constant propagation, CSE, DCE, LICM or block merge optimization transforms |
| M3 PTX-03 memory optimization | Not started | No memory optimization pass |
| M4 PTX-04 regalloc/scheduling | Not started | Bootstrap allocation only |
| M5 PTX-05 GEMM | Not started | No validated GEMM lowering |
| M6 Agent/final packaging | Stub only | No report-driven closed loop |

## Current architecture

Implemented framework modules:

- `ir/`: compiler representation boundary.
- `analysis/`: analysis facts and analysis manager.
- `passes/`: explicit foundation pass pipelines and pass records.
- `reports/`: deterministic compilation reports.
- `legacy_lowering.py`: quarantined compatibility lowering boundary.
- `compiler.py`: public compiler facade and pipeline orchestration.
- `isa.py`: target profiles, encoder/decoder and disassembly helpers.
- `sim.py`: local Track-B subset simulator.

## Pipeline status

`-O0`, `-O2` and `-O3` now select explicit non-optimizing foundation pipelines. Scalar optimization transforms are still not implemented.

The current pipeline records validation and analysis stages only. It does not claim DCE, CSE, LICM, constant propagation, scheduling or GEMM optimization support.

## Regression and guardrail status

- PTX-01 and PTX-02 `-O0` Track-B raw binaries are guarded by fixed SHA256 golden fixtures.
- Architecture guardrails cover the compiler facade, legacy lowering, future lowering/backend directories and pass implementations.
- Guardrails use AST-level semantic dispatch checks rather than broad string matching.

## Performance-model status

- `docs/PERFORMANCE_MODEL.md` records the 2026-07-13 organizer guidance and slide-derived target-hardware indicators.
- Current recorded indicators include warp width, CTA limit, register file size, predicate register count, memory spaces, SMEM/LMEM capacity and memory-service assumptions.
- Future compilation reports should expose static instruction, memory-line, memory-space, register, local-memory and dependency metrics, plus official Cycle Model metrics when available.
- Missing official metrics must be represented as unavailable or `null`; they must not be fabricated.

## Technical-debt register

### High priority

1. `legacy_varying_branch_items` remains a temporary compatibility escape hatch and is not a general correctness solution for future PTX-03/04/05 claims.
2. Uniformity analysis still has source-order limitations and must evolve toward CFG fixed-point dataflow before arbitrary block transformations.
3. New optimization functionality must not expand `compiler.py`; ownership belongs to IR, analysis, passes and lowering boundaries.

### Medium priority

1. Temporary registers R240-R255 currently rely on instruction-local lifetime assumptions. Future multi-instruction expansion requires explicit lifetime management or virtual-register IR.
2. PTX 64-bit pointer handling needs an explicit address legalization contract.
3. The simulator is a local semantic checker only and is not the official competition oracle.

## Organizer clarification

Still unresolved from public materials:

- Exact C1 `.aecbin` Header/Code/Data/Relocation/Symbol Table layout.
- Formal PMEM kernel-parameter ABI.
- Whether C1 T5 uses Track-B scalar ISA, C2/B3 tensor extensions, or another frozen profile.
- Availability and interface of the official C1 validator, Golden Model, Cycle Model and scoring script.
- Machine-readable official NVIDIA-like target-hardware parameter file beyond the supplied slide screenshots.
- Official Cycle Model report schema and how it should be consumed by `agent/run_agent`.

Recorded organizer guidance:

- C performance optimization should stay aligned with the Track-B architecture direction and future A/B/C integration, even though full integration is not required at the current stage.
- Current-stage optimization may use NVIDIA-like GPGPU performance parameters as target-hardware indicators.
- Teams are encouraged to build a Performance Model, quantify compute, memory and data-movement bottlenecks, and correct the model with realistic application measurements.
- C1 performance scoring is correctness-gated; wrong programs do not receive performance score.
- C1 Agent scoring focuses on closed-loop optimization evidence, not whether a large language model is called.

## Verification boundary

Local completion does not mean official Golden Model, Cycle Model or grader approval.

## Next single main task

M2.2 scalar optimization preparation and model-facing report foundation:

1. Add a machine-readable compilation report skeleton that exposes static metrics needed by `docs/PERFORMANCE_MODEL.md`, including 128-byte line traffic, memory-space traffic, register pressure and local-memory pressure.
2. Improve IR contracts where required by the first scalar pass.
3. Keep architecture guardrails enforced.
4. Upgrade uniformity to CFG worklist/fixed-point analysis before relying on block reordering.
5. Remove or tightly quarantine unsafe legacy varying-branch fallback.
6. Introduce optimization transforms only through pass abstractions with unit, mutation and executable differential tests.
7. Keep PTX-03/04/05 out of scope until the M2.2 correctness gate passes.
