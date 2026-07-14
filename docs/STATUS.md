# C1 Compiler Status

This file is the mutable implementation ledger for the C1 compiler repository. Long-term goals and scoring constraints live in `C1_PROJECT_CHARTER.md`; operating rules live in `AGENTS.md` and `DEVELOPMENT_POLICY.md`.

## Snapshot

Status date: 2026-07-14

Writable repository: `BulletFlying/agentic4systems-c1-compiler-bootstrap`

Local Git remote policy: only `origin` pointing to `BulletFlying/agentic4systems-c1-compiler-bootstrap`

Official repository remote: not configured

Official repository checked: `ephonic/Agentic4SystemSummerSchoolContest` latest observed `main` commit `c30b3f9eed11183fee8e33735e82cdf72a50cbe8` (2026-07-14). C1 package alignment was previously established against `dce818b`; the newer upstream commits add C1 CModel files and C2/C3 updates but do not remove the reduced C1 scalar scope.

The reduced official package supersedes older assumptions: raw `.aecbin` stream is defined, PMEM ABI is defined, C1 Agent scoring is removed, C1 Cycle Model will not be provided, Tensor/TMUL/low-precision GEMM are not required, T5 is FP32 scalar GEMM, and evaluation uses `-O2`.

Local repository alignment now records the active official package directly: root `spec.md`, `scoring.md`, `hint.md`, the public manifest-based T1-T5 package under `testcases/`, and released `aec-cmodel/` files match the reduced official package. Legacy PTX regression fixtures are retained under `tests/fixtures/legacy_ptx/`.

Organizer errata recorded on 2026-07-14:

- PTX input remains `shl.b32`, but legal AEC output encoding must be `SHL.u32`.
- C1 does not require warp-internal divergent branch or reconvergence. `BRX` is legal only when currently active lanes in a warp agree on the branch condition; `aec-precise` returning `non-uniform branch` for divergent input is expected.
- C2/C3 Q&A items are cross-track context only and must not introduce CUDA/CuPy/H200/C2-runtime assumptions into the C1 compiler path.

## Milestone state

| Milestone | State | Evidence boundary |
|---|---|---|
| M0 ISA/CLI/encoder baseline | Complete, with 2026-07-14 errata patch | Raw encoder/decoder audited against official C1 opcode/type/space table; `shl.b32` output encoding is patched to `SHL.u32`; T1-T5 -O2 compile smoke passes |
| M1/T1 basic lowering | Complete (local simulator, slow-test gate only) | All public T1-T5 manifests execute correctly via local simulator (`pytest -q tests/test_manifest_execution.py -m slow`, 5 passed in 3:30 on 2026-07-14; not in default `pytest`). Lowering covers or/xor/shl/fma/negated-branch; SHL encoding erratum is covered by a dedicated test. PMEM ABI tests pass. y/z special registers work. Official `aec-precise` not yet integrated into repository tests. |
| M2.1 CFG/uniform-loop correctness | Locally complete under uniform-BRX assumption | CFG, dominators, uniformity analysis and executable tests exist; T2 manifest executes correctly under local simulator. Official clarification confirms no reconvergence support is required, but any varying-BRX fallback remains debt. |
| M2.2 architecture foundation | Locally complete | IR facade, analysis manager, pass manager, reports, foundation pipelines, architecture guardrails and O0 binary fixtures exist |
| M2.2 scalar optimization | Complete (O2, 2026-07-14) | O2: DRE (8 tests) + CSE (15 tests) + Local CF (10 tests) + Global CP (7 tests) + LoadReuse (10 tests) + Global DCE (8 tests) + LICM (9 tests) + BlockSimplification (8 tests). LICM includes domination and single-def safety checks. BlockSimplification includes unreachable block removal and side-effect preservation. Global CP includes join-point safety and unlabeled CFG-boundary reset. T2: 37→35 AEC instructions (-5.4%). All M2 scalar passes are O2 proven-safe with comprehensive unit/negative/mutation tests. |
| M3/T3 memory access optimization | Complete (O2, 2026-07-14) | O2: RepeatedGlobalLoadReusePass (10 tests) + LoadHoistingPass (8 tests). LoadHoisting includes domination, single-def, alias, predicated, and conditional-load safety checks. |
| M4/T4 register allocation and scheduling | Complete (O2, 2026-07-14) | O2: Linear-scan RA with loop-aware liveness extension — registers used inside loops have their live ranges extended to the loop tail, preventing physical-register reuse across back edges (fixes T5 GEMM loop-carried corruption). Pair-assignment uses even-aligned bases. 6 tests. DDG List Scheduler (closest-def DDG, STORE→LOAD barrier, 5 tests) runs post-lowering. |
| M5/T5 FP32 scalar GEMM | Complete (O2, 2026-07-14) | O2: LoopUnrolling (even-trip-count check, loop-carried register preservation, counter-dedup in renamed body, predicate/store filtering, 6 tests + 4 GEMM sizes). Unroller runs before RA; RA handles unrolled-body register naming. |
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

The scoring-critical O2 pipeline (all passes proven-safe with unit/negative/mutation tests; loop-aware RA 2026-07-14):

1. Validation + conservative DRE + BB-local CSE + local CF
2. Global CP (forward dataflow, join-point safe, unlabeled CFG-boundary reset)
3. Repeated global load reuse (conservative alias model)
4. CFG/uniformity rebuild
5. Global DCE (worklist-based, multi-def aware)
6. Record loop analysis
7. LICM (domination check, single-def safety, side-effect/predicated filtering)
8. CFG/uniformity rebuild
9. Block simplification (empty/jump merge, unreachable removal, side-effect preservation, branch remapping)
10. Load hoisting (speculative load safety, domination/alias/predicate checks)
11. CFG/uniformity rebuild
12. Loop unrolling (even-trip-count check, loop-carried register preservation)
13. CFG/uniformity rebuild
14. Linear-scan RA (loop-aware liveness extension prevents cross-iteration corruption)
15. CFG/uniformity rebuild
16. [post-lowering] DDG list scheduler (STORE→LOAD barrier)

O2 effects: T2 37→35 instructions (-5.4%), T3 redundant global loads eliminated, T4 register pressure reduced, T5 GEMM loop unrolled.
O2 public manifest pass rate: 5/5 (T1-T5), verified 2026-07-14.
- DRE: 8 tests (5 positive + 3 negative)
- BB-local CSE: 15 tests (2 positive + 13 negative boundary)
- Local CF: 10 tests (2 positive + 5 negative + 3 integration)
- Global CP: 7 tests (3 original + 4 safety: join-point, memory, convergence, rename)
- Repeated Load Reuse: 10 tests (3 positive + 7 negative)
- Global DCE: 8 tests (2 positive + 6 negative)
- LICM: 9 tests (3 original + 6 safety: hoist, vary, store, nondom, predicated, rename)
- Block Simplification: 8 tests (2 original + 6 safety: merge, unreachable, side-effect, branch-remap, no-change, entry-preserve)

O2 effects: T2 37→35 instructions (-5.4%), T3 redundant global loads eliminated.
O3 adds experimental passes (LinearScanRA, DDG Scheduler, LoopUnrolling) which are still hardening for O2.
LoadHoisting is now O2 proven-safe (M3 complete).

## Official package alignment status

Aligned in repository facts:

- Root `spec.md`, `scoring.md`, `hint.md`, `testcases/` and `aec-cmodel/` are LF-normalized text-content-equivalent to the reduced official package baseline, with local errata overlay recorded in `docs/ORGANIZER_CLARIFICATIONS_20260714.md`.
- Agent scoring is removed from C1.
- Tensor/TMUL/low-precision GEMM scope is removed from C1.
- T5 is FP32 scalar GEMM.
- Cycle Model will not be provided; participant-side performance model remains useful.
- Official `aec-precise` CModel is present under `aec-cmodel/`; the public docs expose stdout JSON `steps` as a warp-level dynamic execution step count.
- Organizer clarification: performance metric is closer to warp-level dynamic instruction/step count than a latency-weighted cycle model, compile timeout remains 180 seconds, Python/script entry points are allowed, and the evaluation environment has `python3`.
- Organizer clarification: `shl.b32` must encode as `SHL.u32`; input syntax and bit result are unchanged.
- Organizer clarification: warp-divergent `BRX` / reconvergence is not required; legal hidden paths have uniform branch condition across active lanes.
- Raw `.aecbin` format and PMEM ABI are now defined in official `spec.md`.
- ld.param.u64/b64 lowered as two LD.pmem.u32 per spec §7.4.
- Public T1-T5 package is present at the official path `testcases/`.
- `-O2` compile/report smoke over all mirrored public T1-T5 kernels: `tests/test_official_package.py`.
- Manifest-aware local execution harness: `tests/official_harness.py` (stdlib-only); e2e tests gated behind `@pytest.mark.slow`.

Remaining work (non-blocking for O2 submission):

- Address ABI negative tests for 64-bit PTX pointers lowered to the low 32-bit AEC abstract address rule (dedicated negative tests needed).
- Official `aec-precise` self-test integration — CModel harness implemented (`tests/cmodel_harness.py`) but gated on platform (Linux/macOS only; Windows evaluation host not yet available).
- Performance model integration with pass pipeline feedback.
- Robustness variant tests (ACCEPTANCE_CRITERIA.md X.4).

## Performance-model status

- `docs/PERFORMANCE_MODEL.md` is updated to the reduced package: no participant Cycle Model, no Tensor model requirement, no official Agent loop requirement.
- `docs/performance_targets/track_c_hint_20260713.json` remains a local transcription of official `hint.md` target parameters.
- Compile reports should converge toward the new official diagnostic fields: instruction/register/predicate/spill/branch/load/store counts, memory-instruction ratio and dependency-depth estimates.
- Missing estimates or official measurements must be represented as unavailable or `null`; they must not be fabricated.

## Technical-debt register

### High priority

1. Parser/frontend must be audited against the new restricted PTX 9.3 subset and manifest-based package shape.
2. PMEM parameter layout must be made explicitly spec-conformant and covered by tests.
3. `legacy_varying_branch_items` remains a temporary compatibility escape hatch. After the 2026-07-14 clarification, it must be treated as debt to remove or tightly quarantine; C1 does not need divergent-BRX semantics.
4. Uniformity analysis still has source-order limitations and must evolve toward CFG fixed-point dataflow before arbitrary block transformations.
5. New optimization functionality must not expand `compiler.py`; ownership belongs to IR, analysis, passes and lowering boundaries.
6. Conservative dead-result elimination uses a whole-program read set rather than SSA/liveness. This is intentionally safe but leaves many removable definitions in place.
7. Global CP, LICM, and BlockSimplification are now O2 proven-safe (2026-07-14). Their implementations include domination/single-def/join-point safety checks. Move implementation out of `passes/experimental.py` into a dedicated O2 module.

### Medium priority

1. Temporary registers R240-R255 currently rely on instruction-local lifetime assumptions. Future multi-instruction expansion requires explicit lifetime management or virtual-register IR.
2. PTX 64-bit pointer handling needs an audit against the official 32-bit abstract address rule and register-pair constraints.
3. The simulator is a local semantic checker only and is not the official competition oracle.
4. Existing docs/tests may still mention old PTX-01..PTX-05 filenames; those should be retained only as legacy regression fixtures, not as the active official public package names.
5. C3 H200/CuPy and C2 runtime-library Q&A must remain out of C1 compiler dependencies.

## Organizer clarification

Resolved or changed by the reduced package and later 2026-07-14 errata:

- C1 `.aecbin` format is raw AEC 128-bit instruction stream.
- PMEM ABI is defined by declaration order, natural alignment and 8-byte block alignment.
- Tensor/TMUL/low-precision GEMM are not required.
- Cycle Model will not be provided to participants.
- Agent automatic optimization is no longer a C1 scoring category.
- Evaluation invokes `aec-cc` with `-O2`.
- `shl.b32` lowers/encodes as `SHL.u32`.
- Warp-divergent branch / reconvergence is not required; `BRX` assumes uniform condition over currently active lanes.

Still unresolved or pending:

- Official `aec-precise` integration: harness implemented but gated on platform (Linux/macOS required; Windows evaluation host cannot run the shipped binaries). See `tests/cmodel_harness.py`.
- Official baseline performance numbers are not public; evaluation compares against an internal baseline compiler.

## Evaluation environment

- **Platform**: Linux x86-64 (confirmed by organizer, 2026-07-14)
- **Python**: 3.13.5 (`python3` on PATH)
- **Compiler timeout**: 180 seconds
- **Entry point**: `./compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json`

## Verification boundary

Local completion does not mean official CModel or grader approval. Every correctness claim must say whether official `aec-precise` was not run, failed, or passed with exact command evidence.

## Next tasks (post-submission hardening)

1. Integrate `aec-precise` for public T1-T5 on a Linux x86-64 host; compare output dumps against reference computations.
2. Add robustness variant tests (parameter scale, grid/block dim changes, register renaming, GEMM size variants).
3. Add Address ABI negative tests for 64-bit PTX pointers with the 32-bit abstract address rule.
