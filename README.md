# C1 Compiler — PTX-to-AEC Scalar Compiler

This repository contains the current C1 PTX-to-AEC scalar compiler implementation and development evidence for the Agentic4Systems Summer School Contest (Track C). All M0–M5 milestones are complete at the O2 scoring level including loop-aware register allocation, DDG scheduling, and FP32 scalar GEMM loop unrolling. Official aec-precise output comparison is pending; see Evidence Tiers below.

## Track C structure

Track C consists of three independent sub-tasks:

| Task | Scope | Relationship to C1 |
|---|---|---|
| **C1** | PTX-to-AEC scalar compiler | This repository |
| **C2** | AEC device runtime library | Separate; C1 does not depend on C2 |
| **C3** | Operator scheduling and model deployment | Separate; C1 does not depend on C3 |

A complete Track C submission package requires C1/C2/C3 directories. The C1 compiler itself has no dependency on CUDA, CuPy, H200, ONNX, PyTorch, C2 runtime, or libaec.so. The `agent/run_agent` script is optional C1 development tooling, not a C1 scoring entry point. Do not confuse it with C2 agents/.

## Active official baseline

The active baseline is the reduced C1 package in `ephonic/Agentic4SystemSummerSchoolContest`. Local `spec.md`, `scoring.md`, `hint.md`, `testcases/` and `aec-cmodel/` are aligned with the reduced C1 package. Later organizer clarifications are recorded in `docs/ORGANIZER_CLARIFICATIONS_20260714.md`.

Key facts for the current scoring package:

- Input is a restricted NVIDIA PTX ISA 9.3 scalar subset.
- Public tests are manifest-based directories: `kernel.ptx` + `manifest.json`.
- Official scoring invokes `compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json`.
- `.aecbin` is a raw AEC 128-bit instruction stream, not a Header/Data/Reloc/Symbol object container.
- PMEM parameter ABI is defined in `spec.md` §7.
- C1 no longer requires Tensor/TMUL/low-precision GEMM. T5 is FP32 scalar GEMM.
- C1 no longer has an official Agent score.
- Cycle Model will not be provided; performance modeling remains participant-side.
- The released `aec-cmodel/` package provides `aec-precise-linux-x86_64` and `aec-precise-macos-arm64`; it reports `steps` as a warp-level dynamic execution step count.
- Official C1 evaluation environment: **Linux x86-64, Python 3.13.5**. Compiler timeout: 180 seconds. `compiler/aec-cc` may be a Linux x86-64 ELF or a script with a `#!/usr/bin/env python3` shebang.
- Windows is a supported local development platform but is NOT the official evaluation environment.
- 2026-07-14 erratum: PTX input `shl.b32` must encode as AEC `SHL.u32`; `and/or/xor.b32` remain `.b32`.
- 2026-07-14 branch clarification: C1 does not require warp-internal divergent branch or reconvergence; legal `BRX` paths have a uniform branch condition across currently active lanes.

The root `spec.md`, `scoring.md`, `hint.md`, and `testcases/` directory are aligned with the reduced official C1 package. Legacy public PTX-01/PTX-02 regression fixtures live under `tests/fixtures/legacy_ptx/` and must not be treated as the active official package.

See `docs/OFFICIAL_SCOPE_UPDATE_20260713.md` for the migration summary and `docs/ORGANIZER_CLARIFICATIONS_20260714.md` for the latest errata and cross-track scope notes.

## Entry points

Official scoring entry point (Linux x86-64):

```bash
compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json
```

For local development smoke tests, the Python interpreter may be called explicitly:

```bash
python compiler/aec-cc kernel.ptx -O2 -o test.aecbin --report test.json
```

Development-only tools (not part of the C1 submission):

| Path | Purpose |
|---|---|
| `disassembler/aec-objdump` | Diagnostic AEC binary disassembler |
| `agent/run_agent` | Optional C1 development automation (not a scoring entry point; not related to C2 agents/) |

## Evidence tiers

Every correctness claim must state which evidence tier was actually exercised:

| Tier | Name | Meaning | Current C1 status |
|---|---|---|---|
| 0 | Static | compileall, import graph, architecture guardrails | All passing |
| 1 | Unit | Parser, encoder, analysis cache, pass ordering, report determinism | 169+ unit/integration tests passing |
| 2 | Local simulator | O0/O2 binary regression, public manifest harness | 5/5 T1-T5 manifests passing (local simulator only) |
| 3 | Official CModel smoke | `aec-precise` runs without error | Harness implemented (`tests/cmodel_harness.py`); pending Linux x86-64 execution |
| 4 | Official CModel dump/reference | `aec-precise` output dump compared against reference | **Not yet run** — highest-priority remaining task |

Do not write "official CModel pass" or "grader pass" until Tier 4 evidence exists.

## Current scope

The checked-in compiler provides:

- Raw 128-bit AEC instruction encoding and raw binary output using `w0,w1,w2,w3` little-endian `uint32_t` order.
- PTX parsing for the official C1 syntax subset.
- Lowering for parameter loads, special-register moves, integer/FP32 arithmetic, predicates, branches and global loads/stores.
- Encoder-level support for the 2026-07-14 `shl.b32 -> SHL.u32` erratum.
- CFG, dominator, loop and conservative uniformity infrastructure.
- Explicit O0/O2/O3 pipelines. O2 (scoring-critical): DRE, BB-local CSE, local CF, global CP, repeated load reuse, global DCE, LICM, block simplification, load hoisting, loop unrolling, loop-aware linear-scan RA, and DDG post-lowering scheduler.
- Deterministic reports with static metrics and null cycle-model placeholders.
- Architecture guardrails and legacy regression fixtures.
- A local simulator subset for differential testing (NOT the official oracle).

## Known gaps

- **Official aec-precise output comparison**: CModel harness is implemented and ready for Linux x86-64. Requires the `aec-precise-linux-x86_64` binary. This is the highest-priority remaining work item.
- **Robustness variant tests**: Parameter scale, grid/block dimension changes, register renaming, GEMM size variants are not yet automated.
- **Address ABI negative tests**: Dedicated tests for the 32-bit abstract address rule are not yet implemented.
- **Final submission packaging**: The Track C submission package structure (C1/C2/C3 directories) is out of scope for the C1 compiler repository and will be handled separately.

## Verification

Official evaluation environment: **Linux x86-64, Python 3.13.5**.

Local verification (any platform with Python 3.10+):

```bash
python -m compileall -q src compiler disassembler agent tests
python -m pytest -q tests                              # fast unit/integration tests
python -m pytest -q tests/test_manifest_execution.py -m slow -v  # T1-T5 e2e manifest tests
```

Repository CI (`.github/workflows/c1-tests.yml`) runs Python 3.10/3.13 for development compatibility. The official environment is Python 3.13.5 specifically. The CModel smoke step in CI is non-blocking and is NOT correctness evidence.

## Project governance

Repository context must be read from the repository rather than reconstructed from chat history:

- `spec.md`: active official C1 language, AEC opcode, ABI and raw `.aecbin` specification.
- `scoring.md`: active official 50/40/10 C1 scoring model.
- `testcases/`: public T1-T5 package from the official archive.
- `aec-cmodel/`: official released `aec-precise` CModel binaries and command documentation.
- `docs/ORGANIZER_CLARIFICATIONS_20260714.md`: latest organizer errata (`shl.b32 -> SHL.u32`, no divergent-BRX).
- `docs/OFFICIAL_SCOPE_UPDATE_20260713.md`: reduced official package summary.
- `docs/C1_PROJECT_CHARTER.md`: mission, scoring, constraints, milestones and acceptance matrix.
- `docs/PROJECT_OVERVIEW.md`: project-level world model and source-of-truth map.
- `docs/ROADMAP.md`: implementation route and phase gates.
- `docs/ARCHITECTURE.md`: compiler framework boundaries and dependency direction.
- `docs/EVALUATION.md`: official score mapping, evidence tiers and merge-readiness checklist.
- `docs/NON_GOALS.md`: scope boundaries and anti-drift rules.
- `docs/STATUS.md`: mutable implementation state, verification boundary, technical debt and next tasks.
- `docs/DEVELOPMENT_POLICY.md`: branch naming, PR gate, new-module contract, review and merge rules.
- `docs/ARCHITECTURE_INVARIANTS.md`: enforceable architecture invariants.
- `docs/PERFORMANCE_MODEL.md`: participant-side performance-model planning.
- `AGENTS.md`: mandatory rules for human and AI-assisted development.

The official repository `ephonic/Agentic4SystemSummerSchoolContest` must not be configured as a local Git remote. All project development belongs in `BulletFlying/agentic4systems-c1-compiler-bootstrap` and non-emergency changes use a feature branch plus PR.
