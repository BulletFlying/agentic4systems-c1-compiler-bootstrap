# C1 Compiler Workspace

This directory contains the current C1 PTX-to-AEC scalar compiler workspace. It is a bootstrap implementation, not a complete contest solution.

## Active official baseline

The active baseline is the reduced C1 package observed on 2026-07-13 in `ephonic/Agentic4SystemSummerSchoolContest` commit `68a4aea16e69045e397d12333244f7974245d49c`.

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

See `docs/OFFICIAL_SCOPE_UPDATE_20260713.md` for the migration summary.

## Entry points

Required scoring entry point:

```bash
python compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json
```

Development tools retained in this repository:

```bash
python disassembler/aec-objdump output.aecbin
python agent/run_agent
```

`agent/run_agent` is now optional tooling, not an official C1 scoring entry point.

## Project governance

Repository context must be read from the repository rather than reconstructed from chat history:

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
- PTX parsing for the earlier public C1 syntax shape.
- Basic lowering for parameter loads, special-register moves, integer/FP32 arithmetic, predicates, branches and global loads/stores.
- CFG, dominator, loop and conservative uniformity infrastructure.
- Explicit O0/O2/O3 pipelines with conservative scalar passes: DRE, basic-block-local CSE and local constant folding.
- Deterministic reports with static metrics.
- Architecture guardrails and legacy regression fixtures.
- A local simulator subset for bootstrap differential tests.

## Known gaps

- The compiler has not yet been realigned to the new `.visible .entry`, `.target sm_90`, `.address_size 64`, manifest-based public package shape.
- Official public T1-T5 package executable validation has not been performed.
- Parser/lowering coverage for the full new restricted PTX subset needs audit.
- PMEM ABI and address ABI need explicit new-spec tests.
- T3, T4 and T5 official-family implementations are not complete.
- ARM Golden Model self-test integration is pending organizer release.
- Optional Agent/controller work is no longer official-score critical.

See `docs/STATUS.md` for the detailed debt register and next single main task.

## Verification

Local baseline on the requested Windows environment:

```powershell
C:\Users\HP\anaconda3\envs\zhang\python.exe -m compileall -q src compiler disassembler agent tests
C:\Users\HP\anaconda3\envs\zhang\python.exe -m pytest -q tests
```

Repository CI is configured in `.github/workflows/c1-tests.yml` for Python 3.10 and 3.13. A workflow file existing is not itself evidence that CI passed; check the actual GitHub Actions run before making that claim.
