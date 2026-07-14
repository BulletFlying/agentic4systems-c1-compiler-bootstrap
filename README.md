# C1 Compiler — PTX-to-AEC Scalar Compiler

C1 compiler for the Agentic4Systems Summer School Contest (Track C). Compiles a restricted NVIDIA PTX ISA 9.3 scalar subset to AEC 128-bit fixed-width machine code. All M0–M5 milestones are complete at O2 including loop-aware register allocation, DDG scheduling, and FP32 scalar GEMM loop unrolling.

## Active official baseline

The active baseline is the reduced C1 package in `ephonic/Agentic4SystemSummerSchoolContest`. Local `spec.md`, `scoring.md`, `hint.md`, `testcases/` and `aec-cmodel/` are aligned with the reduced C1 package. Later organizer clarifications are recorded in `docs/ORGANIZER_CLARIFICATIONS_20260714.md`.

Key changes from the earlier working plan:

- Input is a restricted NVIDIA PTX ISA 9.3 scalar subset.
- Public tests are manifest-based directories: `kernel.ptx` + `manifest.json`.
- Official scoring invokes `compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json`.
- `.aecbin` is a raw AEC 128-bit instruction stream, not a Header/Data/Reloc/Symbol object container.
- PMEM parameter ABI is defined in the new `spec.md`.
- C1 no longer requires Tensor/TMUL/low-precision GEMM.
- T5 is FP32 scalar GEMM.
- C1 no longer has an official Agent score.
- Cycle Model will not be provided; performance modeling remains participant-side.
- The released `aec-cmodel/` package provides `aec-precise-linux-x86_64` and `aec-precise-macos-arm64`; it reports `steps`, which the public CModel docs describe as a warp-level dynamic execution step count.
- Organizer clarification says compile timeout remains 180 seconds, `compiler/aec-cc` may be a script/Python entry point, and the evaluation environment has `python3`.
- 2026-07-14 erratum: PTX input `shl.b32` must encode as AEC `SHL.u32`; `and/or/xor.b32` remain `.b32`.
- 2026-07-14 branch clarification: C1 does not require warp-internal divergent branch or reconvergence; legal `BRX` paths have a uniform branch condition across currently active lanes.

The root `spec.md`, `scoring.md`, `hint.md`, and `testcases/` directory in this directory are now aligned with the reduced official C1 package. Legacy public PTX-01/PTX-02 regression fixtures live under `tests/fixtures/legacy_ptx/` and must not be treated as the active official package.

See `docs/OFFICIAL_SCOPE_UPDATE_20260713.md` for the migration summary and `docs/ORGANIZER_CLARIFICATIONS_20260714.md` for the latest errata and cross-track scope notes.

## Entry points

Required scoring entry point (Linux x86-64, Python 3.13.5):

```bash
./compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json
```

The compiler default is `-O2` and the official C1 ISA profile (`c1_default`). The legacy `track_b_v1` profile (with C2/B3 extensions) is available via `--profile track_b_v1`.

Development-only tools (not part of the C1 submission):

| Path | Purpose | Submission? |
|---|---|---|
| `compiler/aec-cc` | Scoring entry point | **Required** |
| `src/` | Compiler source | **Required** |
| `disassembler/aec-objdump` | Diagnostic disassembler | No |
| `agent/run_agent` | Optional automation harness | No |
| `aec-cmodel/` | Official CModel binaries (reference only) | No |
| `testcases/` | Public test suite | No |
| `tests/` | Unit/integration tests | No |
| `docs/` | Project documentation | No |

## Project governance

Repository context must be read from the repository rather than reconstructed from chat history:

- `spec.md`: active reduced official C1 language, AEC opcode, ABI and raw `.aecbin` specification.
- `scoring.md`: active reduced official 50/40/10 C1 scoring model.
- `testcases/`: public T1-T5 package from the reduced official archive.
- `aec-cmodel/`: official released `aec-precise` CModel binaries and command documentation.
- `docs/ORGANIZER_CLARIFICATIONS_20260714.md`: latest organizer errata, including `shl.b32 -> SHL.u32` and no divergent-BRX requirement.
- `docs/OFFICIAL_SCOPE_UPDATE_20260713.md`: reduced official package summary and migration priorities.
- `docs/C1_PROJECT_CHARTER.md`: mission, official scoring, architecture constraints, milestones and acceptance matrix.
- `docs/PROJECT_OVERVIEW.md`: short project-level world model and source-of-truth map.
- `docs/ROADMAP.md`: implementation route and phase gates under the reduced C1 scope.
- `docs/ARCHITECTURE.md`: compiler framework boundaries and dependency direction.
- `docs/EVALUATION.md`: official score mapping, evidence tiers and merge-readiness checklist.
- `docs/NON_GOALS.md`: scope boundaries and anti-drift rules.
- `docs/AGENT_ARCHITECTURE.md`: optional deterministic controller boundary after Agent scoring removal.
- `docs/STATUS.md`: mutable implementation state, verification boundary, technical debt and next task.
- `docs/DEVELOPMENT_POLICY.md`: branch naming, PR gate, new-module contract, review and merge rules.
- `docs/ARCHITECTURE_INVARIANTS.md`: enforceable architecture invariants for analysis, passes, backend and simulator roles.
- `docs/PERFORMANCE_MODEL.md`: participant-side performance-model planning.
- `AGENTS.md`: mandatory rules for human and AI-assisted development.
- `.github/PULL_REQUEST_TEMPLATE.md`: structured completion and remote-safety checklist.
- `.github/ISSUE_TEMPLATE/c1-module-change.yml`: planning template for a new module or milestone change.

The official repository `ephonic/Agentic4SystemSummerSchoolContest` must not be configured as a local Git remote. All project development belongs in `BulletFlying/agentic4systems-c1-compiler-bootstrap` and future non-emergency changes use a feature branch plus PR.

## Current scope

The checked-in compiler currently provides:

- Raw 128-bit AEC instruction encoding and raw binary output using `w0,w1,w2,w3` little-endian `uint32_t` order.
- PTX parsing for the current public C1 syntax shape, with official-package coverage still under audit.
- Basic lowering for parameter loads, special-register moves, integer/FP32 arithmetic, predicates, branches and global loads/stores.
- Encoder-level support for the 2026-07-14 `shl.b32 -> SHL.u32` erratum.
- CFG, dominator, loop and conservative uniformity infrastructure.
- Explicit O0/O2/O3 pipelines. O2 (scoring-critical): DRE, BB-local CSE, local CF, global CP, repeated load reuse, global DCE, LICM, block simplification, load hoisting, loop unrolling, loop-aware linear-scan RA, and DDG post-lowering scheduler. All O2 passes have comprehensive unit/negative/mutation test coverage.
- Deterministic reports with static metrics.
- Architecture guardrails and legacy regression fixtures.
- A local simulator subset for bootstrap differential tests.

## Known gaps

- Official `aec-precise` integration: CModel harness is implemented (`tests/cmodel_harness.py`) and ready for Linux x86_64. The harness requires the `aec-precise-linux-x86_64` binary and a platform that can execute it. See `docs/STATUS.md` for the detailed evidence tier table.
- C2/C3 Q&A items are not C1 compiler dependencies; do not add CUDA/CuPy/H200/ONNX/C2 runtime assumptions to `compiler/aec-cc`.

## Verification

Evaluation environment: **Linux x86-64, Python 3.13.5**. Compiler timeout: 180 seconds.

Local verification (any platform with Python 3.10+):

```bash
python -m compileall -q src compiler disassembler agent tests
python -m pytest -q tests                              # 210 fast tests
python -m pytest -q tests/test_manifest_execution.py -m slow -v  # 5 e2e manifest tests
```

Repository CI is configured in `.github/workflows/c1-tests.yml` for Python 3.10 and 3.13.
