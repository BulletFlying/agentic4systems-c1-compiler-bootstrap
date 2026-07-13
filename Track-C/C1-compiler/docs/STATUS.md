# C1 Compiler Status

This file is the mutable implementation ledger for `Track-C/C1-compiler/`. Long-term goals and scoring constraints live in `C1_PROJECT_CHARTER.md`; operating rules live in `../AGENTS.md` and `DEVELOPMENT_POLICY.md`.

## Snapshot

Status date: 2026-07-13

Writable repository: `BulletFlying/agentic4systems-c1-compiler-bootstrap`

Local Git remote policy: only `origin` pointing to `BulletFlying/agentic4systems-c1-compiler-bootstrap`

Official repository remote: not configured

Organizer performance clarification recorded in `docs/PERFORMANCE_MODEL.md`: Track-C performance optimization should build a model from NVIDIA-like target-hardware indicators and use it to reason about compute, memory and data-movement bottlenecks. The official `ephonic/Agentic4SystemSummerSchoolContest` repository now contains `Track-C/hint.md` with human-readable Platform A/B target parameters; a local machine-readable transcription is stored in `docs/performance_targets/track_c_hint_20260713.json`. The official Cycle Model schema is still unavailable.

## Milestone state

| Milestone | State | Evidence boundary |
|---|---|---|
| M0 ISA/CLI/encoder baseline | Locally complete | Track-B raw encoder, decoder, objdump and smoke checks exist |
| M1 PTX-01 correctness loop | Locally complete | Partial-warp and randomized differential tests exist |
| M2.1 PTX-02 CFG/uniform-loop correctness | Locally complete | CFG, dominators, uniformity analysis and executable tests exist |
| M2.2 architecture foundation | Locally complete | IR facade, analysis manager, pass manager, reports, foundation pipelines, architecture guardrails and O0 binary golden fixtures exist |
| M2.2 scalar optimization | In progress | O2/O3 include one conservative never-read pure-result elimination pass; no general DCE, CSE, LICM or block merge |
| M3 PTX-03 memory optimization | Not started | No memory optimization pass |
| M4 PTX-04 regalloc/scheduling | Not started | Bootstrap allocation only |
| M5 PTX-05 GEMM | Not started | No validated GEMM lowering |
| M6 Agent/final packaging | Stub only | No report-driven closed loop |

## Current architecture

Implemented framework modules:

- `ir/`: compiler representation boundary.
- `analysis/`: analysis facts and analysis manager.
- `passes/`: explicit foundation and conservative scalar pass pipelines with pass records.
- `reports/`: deterministic compilation reports.
- `legacy_lowering.py`: quarantined compatibility lowering boundary.
- `compiler.py`: public compiler facade and pipeline orchestration.
- `isa.py`: target profiles, encoder/decoder and disassembly helpers.
- `sim.py`: local Track-B subset simulator.

## Pipeline status

`-O0` keeps the validation/analysis foundation path and preserves the fixed PTX-01/PTX-02 O0 binary goldens. `-O2` and `-O3` now run `conservative-dead-result-elimination` before rebuilding CFG/uniformity facts and lower from the pass-updated `module.function.program`.

The first transform removes only unpredicated, well-formed, explicitly whitelisted pure scalar instructions whose destination register is never read anywhere in source operands, address expressions or predicates. It does not claim general DCE, CSE, LICM, constant propagation, scheduling, register allocation or GEMM optimization support.

For PTX-02, O2/O3 remove the never-read `mul.f32 %f15, %f1, %f2` while deliberately retaining the duplicate `%f5`/`%f6` adds for the next basic-block-local CSE step.

## Regression and guardrail status

- PTX-01 and PTX-02 `-O0` Track-B raw binaries are guarded by fixed SHA256 golden fixtures.
- O2/O3 PTX-02 machine code removes one instruction and reports `removed_instruction_count: 1` plus `optimization_transforms_applied: 1`.
- Local simulator differential coverage compares O0 and O2 behavior for PTX-02.
- Mutation coverage renames the kernel, dead register and labels to prove the transform is not public-testcase-specific.
- Negative coverage preserves memory, control, predicated, predicate-result, carry-setting and unknown operations.
- Architecture guardrails cover the compiler facade, legacy lowering, future lowering/backend directories and pass implementations.
- Guardrails use AST-level semantic dispatch checks rather than broad string matching.

## Performance-model status

- `docs/PERFORMANCE_MODEL.md` records the 2026-07-13 organizer guidance, the official `Track-C/hint.md` target platform table and the earlier slide-derived AEC implementation indicators.
- `docs/performance_targets/track_c_hint_20260713.json` records a local machine-readable transcription of the official human-readable table.
- Official Platform A/B indicators now recorded include per-SM register file, unified L1/Shared-Memory pool, max Shared Memory, bank organization, L2 cache, HBM memory/bandwidth, host interconnect, GPU interconnect and reference access latencies.
- Slide-derived AEC indicators remain useful for C1 legality and local report estimates: warp width, CTA limit, predicate register count, AEC memory spaces, fixed AEC Shared Memory and LMEM capacity, and 128-byte memory-service assumptions.
- Compilation reports expose an explicit `performance_target`, static instruction/memory-space metrics, warp-level 32-lane global-memory byte estimates and 128-byte service estimates, plus null placeholders for unavailable official Cycle Model metrics.
- Pass reports and top-level metrics now expose the first observable optimization effect instead of hard-coding zero transforms.
- Missing official Cycle Model metrics must be represented as unavailable or `null`; they must not be fabricated.

## Technical-debt register

### High priority

1. `legacy_varying_branch_items` remains a temporary compatibility escape hatch and is not a general correctness solution for future PTX-03/04/05 claims.
2. Uniformity analysis still has source-order limitations and must evolve toward CFG fixed-point dataflow before arbitrary block transformations.
3. New optimization functionality must not expand `compiler.py`; ownership belongs to IR, analysis, passes and lowering boundaries.
4. Conservative dead-result elimination uses a whole-program read set rather than SSA/liveness. This is intentionally safe but leaves many removable definitions in place.

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
- Official machine-readable schema for Track-C target hardware parameters; the current official table is human-readable in `Track-C/hint.md` and locally transcribed for project use.
- Official Cycle Model report schema and how it should be consumed by `agent/run_agent`.

Recorded organizer guidance:

- C performance optimization should stay aligned with the Track-B architecture direction and future A/B/C integration, even though full integration is not required at the current stage.
- Current-stage optimization may use NVIDIA-like GPGPU performance parameters as target-hardware indicators.
- Teams are encouraged to build a Performance Model, quantify compute, memory and data-movement bottlenecks, and correct the model with realistic application measurements.
- Official `Track-C/hint.md` says teams may map PTX to real GPGPU hardware for auxiliary performance evaluation with `nvcc`, `ncu` and `nsys`, but this remains auxiliary model calibration rather than a C1 runtime dependency.
- C1 performance scoring is correctness-gated; wrong programs do not receive performance score.
- C1 Agent scoring focuses on closed-loop optimization evidence, not whether a large language model is called.

## Verification boundary

Local completion does not mean official Golden Model, Cycle Model or grader approval.

## Next single main task

Implement basic-block-local CSE as the next narrow observable optimization:

1. Match only unpredicated, side-effect-free expressions with identical opcode and operands inside one basic block.
2. Invalidate an expression when any source operand is redefined.
3. Rewrite later uses of the redundant destination to the dominating local value and remove only the redundant instruction.
4. Keep memory, predicate, unknown and cross-block cases out of scope.
5. Preserve O0 goldens and require executable differential, mutation and negative tests before merge.
