# C1 Compiler Status

This file is the mutable implementation ledger for `Track-C/C1-compiler/`. Long-term goals and scoring constraints live in `C1_PROJECT_CHARTER.md`; operating rules live in `../AGENTS.md` and `DEVELOPMENT_POLICY.md`.

## Snapshot

Status date: 2026-07-13

Writable repository: `BulletFlying/agentic4systems-c1-compiler-bootstrap`

Local Git remote policy: only `origin` pointing to `BulletFlying/agentic4systems-c1-compiler-bootstrap`

Official repository remote: not configured

Observed official C1 baseline: `ephonic/Agentic4SystemSummerSchoolContest` commit `68a4aea16e69045e397d12333244f7974245d49c`, including updated `Track-C/C1-compiler/spec.md`, `scoring.md` and manifest-based public testcase structure.

The reduced official package supersedes older assumptions: raw `.aecbin` stream is defined, PMEM ABI is defined, C1 Agent scoring is removed, C1 Cycle Model will not be provided, Tensor/TMUL/low-precision GEMM are not required, T5 is FP32 scalar GEMM, and evaluation uses `-O2`.

Local repository alignment now records the active official package directly: root `spec.md` and `scoring.md` have been replaced with the reduced official versions, and the public manifest-based T1-T5 package is mirrored under `official_testcases/20260713/` without deleting legacy regression fixtures.

## Milestone state

| Milestone | State | Evidence boundary |
|---|---|---|
| M0 ISA/CLI/encoder baseline | Locally complete, needs official-rescope audit | Raw encoder/decoder and smoke checks exist; must be audited against the new opcode/type/space table now copied into root `spec.md` |
| M1/T1 basic lowering | Partially complete under old executable harness | New public T1 fixture is mirrored; parser/lowering and `-O2` compile/report smoke have not yet been proven on the new package |
| M2.1 CFG/uniform-loop correctness | Locally complete under old PTX-02 shape | CFG, dominators, uniformity analysis and executable tests exist; must be revalidated on new T2 public package |
| M2.2 architecture foundation | Locally complete | IR facade, analysis manager, pass manager, reports, foundation pipelines, architecture guardrails and O0 binary fixtures exist |
| M2.2 scalar optimization | In progress | O2/O3 include conservative DRE, basic-block-local CSE and basic-block-local constant folding; no general DCE, global CSE, LICM or block merge |
| M3/T3 memory access optimization | Not started | New T3 public fixture is mirrored; no memory optimization pass or manifest-aware execution harness |
| M4/T4 register allocation and scheduling | Not started | New T4 public fixture is mirrored; bootstrap allocation only |
| M5/T5 FP32 scalar GEMM | Not started | New T5 public fixture is mirrored; no validated scalar GEMM lowering under new package |
| Optional controller/tooling | Optional, not official scoring | Open Agent/controller work must be reviewed as development tooling only |

## Current architecture

Implemented framework modules:

- `ir/`: compiler representation boundary.
- `analysis/`: analysis facts and analysis manager.
- `passes/`: explicit foundation and conservative scalar pass pipelines with pass records.
- `reports/`: deterministic compilation reports with static metrics.
- `legacy_lowering.py`: quarantined compatibility lowering boundary.
- `compiler.py`: public compiler facade and pipeline orchestration.
- `isa.py`: target profiles, encoder/decoder and disassembly helpers.
- `sim.py`: local Track-B subset simulator.

## Pipeline status

`-O2` is now the official scoring-critical path. Local `-O0` remains useful as a regression baseline, but official evaluation uses `compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json`.

The current O2/O3 pass sequence includes `conservative-dead-result-elimination`, `basic-block-local-cse` and `local-constant-folding` before rebuilding CFG/uniformity facts and lowering from the pass-updated `module.function.program`.

The scalar transforms remain local and conservative. They do not claim general DCE, global CSE, LICM, block merge, scheduling, register allocation, memory optimization or GEMM optimization.

## Official package alignment status

Aligned in repository facts:

- Root `spec.md` has been replaced with the reduced official PTX 9.3 scalar-subset and AEC opcode/binary/ABI specification.
- Root `scoring.md` has been replaced with the reduced 50 correctness / 40 performance / 10 robustness scoring model.
- Agent scoring is removed from C1.
- Tensor/TMUL/low-precision GEMM scope is removed from C1.
- T5 is FP32 scalar GEMM.
- Cycle Model will not be provided; participant-side performance model remains useful.
- Raw `.aecbin` format and PMEM ABI are now defined in official `spec.md`.
- Public T1-T5 package is mirrored at `official_testcases/20260713/` for local alignment work.

Not yet aligned in implementation:

- Manifest-aware local compile/run harness.
- `-O2` compile/report smoke over all mirrored public T1-T5 kernels.
- Full official PTX subset coverage for `.b32/.b64/.s32`, `or.b32`, `xor.b32`, `shl.b32`, `mul.lo.u32`, `mad.lo.u32`, `mad.rn.f32`, `fma.rn.f32`, negated branch handling and every x/y/z special-register form under the new package.
- PMEM ABI tests for declaration order, natural alignment and 8-byte block alignment.
- Address ABI tests for 64-bit PTX pointers lowered to the low 32-bit AEC abstract address rule.
- Public T1-T5 executable validation.
- ARM Golden Model self-test integration once organizers release the binary.

## Performance-model status

- `docs/PERFORMANCE_MODEL.md` is updated to the reduced package: no participant Cycle Model, no Tensor model requirement, no official Agent loop requirement.
- `docs/performance_targets/track_c_hint_20260713.json` remains a local transcription of official `Track-C/hint.md` target parameters.
- Compile reports should converge toward the new official diagnostic fields: instruction/register/predicate/spill/branch/load/store counts, memory-instruction ratio and dependency-depth estimates.
- Missing estimates or official measurements must be represented as unavailable or `null`; they must not be fabricated.

## Technical-debt register

### High priority

1. Parser/frontend must be audited against the new restricted PTX 9.3 subset and manifest-based package shape.
2. PMEM parameter layout must be made explicitly spec-conformant and covered by tests.
3. `legacy_varying_branch_items` remains a temporary compatibility escape hatch and is not a general correctness solution for new T2/T3/T4/T5 claims.
4. Uniformity analysis still has source-order limitations and must evolve toward CFG fixed-point dataflow before arbitrary block transformations.
5. New optimization functionality must not expand `compiler.py`; ownership belongs to IR, analysis, passes and lowering boundaries.
6. Conservative dead-result elimination uses a whole-program read set rather than SSA/liveness. This is intentionally safe but leaves many removable definitions in place.

### Medium priority

1. Temporary registers R240-R255 currently rely on instruction-local lifetime assumptions. Future multi-instruction expansion requires explicit lifetime management or virtual-register IR.
2. PTX 64-bit pointer handling needs an audit against the official 32-bit abstract address rule and register-pair constraints.
3. The simulator is a local semantic checker only and is not the official competition oracle.
4. Existing docs/tests may still mention old PTX-01..PTX-05 filenames; those should be retained only as legacy regression fixtures, not as the active official public package names.

## Organizer clarification

Resolved or changed by the reduced package:

- C1 `.aecbin` format is raw AEC 128-bit instruction stream.
- PMEM ABI is defined by declaration order, natural alignment and 8-byte block alignment.
- Tensor/TMUL/low-precision GEMM are not required.
- Cycle Model will not be provided to participants.
- Agent automatic optimization is no longer a C1 scoring category.
- Evaluation invokes `aec-cc` with `-O2`.

Still unresolved or pending:

- ARM AEC Golden Model release and exact local invocation contract.
- Official baseline performance numbers are not public; evaluation compares against an internal baseline compiler.
- Official machine-readable schema for `Track-C/hint.md` target parameters does not exist; current local JSON is a project transcription.

## Verification boundary

Local completion does not mean official Golden Model or grader approval. Once the ARM Golden Model is released, every correctness claim must say whether it was not run, failed, or passed with exact command evidence.

## Next single main task

Official package implementation alignment before more optional tooling:

1. Add a manifest-aware compile-smoke harness over `official_testcases/20260713/*/kernel.ptx`.
2. Run the harness through `compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json` and record exact failures.
3. Fix parser/lowering gaps in scoring order, starting with public T1/T2 coverage.
4. Add PMEM ABI and address ABI tests tied directly to the new root `spec.md`.
5. Integrate the ARM Golden Model as soon as it is released.
6. Only after T1/T2 public package correctness is restored, resume T3 memory optimization planning.
