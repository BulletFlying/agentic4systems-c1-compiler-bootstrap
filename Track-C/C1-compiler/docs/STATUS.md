# C1 Compiler Status

This file is the mutable implementation ledger for `Track-C/C1-compiler/`. Long-term goals and scoring constraints live in `C1_PROJECT_CHARTER.md`; operating rules live in `../AGENTS.md` and `DEVELOPMENT_POLICY.md`.

## Snapshot

Status date: 2026-07-14

Writable repository: `BulletFlying/agentic4systems-c1-compiler-bootstrap`

Local Git remote policy: only `origin` pointing to `BulletFlying/agentic4systems-c1-compiler-bootstrap`

Official repository remote: not configured

Official C1 baseline: `ephonic/Agentic4SystemSummerSchoolContest`. Local `spec.md`/`scoring.md` text-content-equivalent (LF-normalized) to current official `main` (dce818b, 2026-07-14). Raw blob hashes differ due to .gitattributes LF enforcement.

The reduced official package supersedes older assumptions: raw `.aecbin` stream is defined, PMEM ABI is defined, C1 Agent scoring is removed, C1 Cycle Model will not be provided, Tensor/TMUL/low-precision GEMM are not required, T5 is FP32 scalar GEMM, and evaluation uses `-O2`.

Local repository alignment now records the active official package directly: root `spec.md`, `scoring.md`, `hint.md`, the public manifest-based T1-T5 package under `testcases/`, and released `aec-cmodel/` files match the reduced official package. Legacy PTX regression fixtures are retained under `tests/fixtures/legacy_ptx/`.

## Milestone state

| Milestone | State | Evidence boundary |
|---|---|---|
| M0 ISA/CLI/encoder baseline | Complete | Raw encoder/decoder audited against official C1 opcode/type/space table; T1-T5 -O2 compile smoke passes |
| M1/T1 basic lowering | Complete (local simulator, slow-test gate only) | All public T1-T5 manifests execute correctly via local simulator (`pytest -q tests/test_manifest_execution.py -m slow`, 5 passed in 3:30 on 2026-07-14; not in default `pytest`). Lowering covers or/xor/shl/fma/negated-branch. PMEM ABI tests pass. y/z special registers work. Official `aec-precise` not yet integrated into repository tests. |
| M2.1 CFG/uniform-loop correctness | Locally complete | CFG, dominators, uniformity analysis and executable tests exist; T2 manifest executes correctly under local simulator |
| M2.2 architecture foundation | Locally complete | IR facade, analysis manager, pass manager, reports, foundation pipelines, architecture guardrails and O0 binary fixtures exist |
| M2.2 scalar optimization | In progress / experimental | O2 enables conservative DRE, BB-local CSE, local constant folding, and worklist-based Global DCE. Global CP, LICM, block simplification, and repeated-load reuse are O3-only (experimental, known limitations). Manifest e2e correctness verified via local simulator only — not official `aec-precise`. |
| M3/T3 memory access optimization | Experimental | RepeatedGlobalLoadReusePass (O3-only) eliminates duplicate loads but has known control-flow boundary gaps. No validated load hoisting or alias analysis. T3 passes under local simulator. |
| M4/T4 register allocation and scheduling | Not started | T4 passes under bootstrap (next-register) allocator. Liveness analysis module scaffolded but not integrated into lowering. No linear-scan RA or scheduler. |
| M5/T5 FP32 scalar GEMM | Not started | T5 passes local simulator (within FP32 tolerance, max error ~2.3e-05). No GEMM-specific loop scheduling, load/compute interleaving, or register-pressure optimization. |
| Optional controller/tooling | Optional, not official scoring | Not an official scoring category |

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

The scoring-critical O2 pipeline enables only passes with direct correctness evidence:
1. Validation + conservative DRE + BB-local CSE + local constant folding
2. CFG/uniformity rebuild
3. Global DCE (worklist-based, multi-def aware)
4. CFG/uniformity rebuild

O3 adds experimental passes (RepeatedGlobalLoadReuse, GlobalCP, BlockSimplification, LICM) which have known correctness limitations and are NOT proven safe for scoring use.

Current public T2 O2 smoke effect: official `testcases/T2_scalar_optimization` reduces from 37→35 AEC instructions (5.4%, 2 transforms). Legacy PTX-02 regression fixtures remain separate under `tests/fixtures/legacy_ptx/`.

## Official package alignment status

Aligned in repository facts:

- Root `spec.md`, `scoring.md`, `hint.md`, `testcases/` and `aec-cmodel/` are LF-normalized text-content-equivalent to current official `main` (dce818b, 2026-07-14).
- Agent scoring is removed from C1.
- Tensor/TMUL/low-precision GEMM scope is removed from C1.
- T5 is FP32 scalar GEMM.
- Cycle Model will not be provided; participant-side performance model remains useful.
- Official `aec-precise` CModel is present under `aec-cmodel/`; the public docs expose stdout JSON `steps` as a warp-level dynamic execution step count.
- Organizer clarification: performance metric is closer to warp-level dynamic instruction/step count than a latency-weighted cycle model, compile timeout remains 180 seconds, Python/script entry points are allowed, and the evaluation environment has `python3`.
- Raw `.aecbin` format and PMEM ABI are now defined in official `spec.md`.
- ld.param.u64/b64 lowered as two LD.pmem.u32 per spec §7.4.
- Public T1-T5 package is present at the official path `testcases/`.
- `-O2` compile/report smoke over all mirrored public T1-T5 kernels: `tests/test_official_package.py`.
- Manifest-aware local execution harness: `tests/official_harness.py` (stdlib-only); e2e tests gated behind `@pytest.mark.slow`.

Not yet aligned in implementation:

- Address ABI tests for 64-bit PTX pointers lowered to the low 32-bit AEC abstract address rule (dedicated negative tests needed).
- Official `aec-precise` self-test integration. Current release includes macOS arm64 and Linux x86_64 binaries; organizer chat says evaluation machine is ARM, but this release package does not include Linux ARM.
- Linear-scan register allocation (liveness analysis module exists, not yet integrated into lowering).
- Load hoisting (loop-invariant loads moved out of loops).
- GEMM-specific loop scheduling and register pressure optimization.
- Performance model integration with pass pipeline feedback.

## Performance-model status

- `docs/PERFORMANCE_MODEL.md` is updated to the reduced package: no participant Cycle Model, no Tensor model requirement, no official Agent loop requirement.
- `docs/performance_targets/track_c_hint_20260713.json` remains a local transcription of official `Track-C/C1-compiler/hint.md` target parameters.
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
7. `passes/scalar.py` is now an aggregation point for local scalar passes plus experimental global passes. Before adding another optimization, split it into focused pass modules so review does not degrade into a single large pass file.

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

- Official Linux ARM CModel availability for reproducing the stated ARM evaluation host locally.
- Official baseline performance numbers are not public; evaluation compares against an internal baseline compiler.
- Official machine-readable schema for `Track-C/C1-compiler/hint.md` target parameters does not exist; current local JSON is a project transcription.

## Verification boundary

Local completion does not mean official CModel or grader approval. Every correctness claim must say whether official `aec-precise` was not run, failed, or passed with exact command evidence.

## Next single main task

Prove correctness of experimental passes before promoting them to O2:

1. Write negative/mutation tests for RepeatedGlobalLoadReusePass (control-flow boundaries, aliasing).
2. Fix GlobalConstantPropagationPass to reset constants at unlabeled CFG boundaries.
3. Fix LICM to verify dominance/single-definition safety before hoisting.
4. After each pass has standalone correctness evidence, promote one pass at a time to O2.
5. Official `aec-precise` integration using `aec-cmodel/PUBLIC_AEC_PRECISE_COMMANDS.md`.
6. Linear-scan register allocation (liveness module scaffolded).
