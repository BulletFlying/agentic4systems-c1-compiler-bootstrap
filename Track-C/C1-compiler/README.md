# C1 Compiler Workspace

This directory contains the current C1 PTX-style IR to AEC ISA compiler workspace. It is a bootstrap implementation, not a complete contest solution.

## Entry Points

- `compiler/aec-cc`: PTX-style IR to AEC binary.
- `disassembler/aec-objdump`: raw AEC binary disassembler.
- `agent/run_agent`: conservative offline optimization-agent stub.

Run them from this directory:

```bash
python compiler/aec-cc testcases/PTX-01_vector_add.ptx -O0 -o build/PTX-01.aecbin
python disassembler/aec-objdump build/PTX-01.aecbin
python agent/run_agent
```

## Project Governance

Repository context must be read from the repository rather than reconstructed from chat history:

- `docs/C1_PROJECT_CHARTER.md`: mission, official scoring, architecture constraints, milestones and acceptance matrix.
- `docs/PROJECT_OVERVIEW.md`: short project-level world model and source-of-truth map.
- `docs/ROADMAP.md`: M0-M6 implementation route and phase gates.
- `docs/ARCHITECTURE.md`: compiler framework boundaries and dependency direction.
- `docs/EVALUATION.md`: official score mapping, evidence tiers and merge-readiness checklist.
- `docs/NON_GOALS.md`: scope boundaries and anti-drift rules.
- `docs/AGENT_ARCHITECTURE.md`: report-driven Agent design and LLM boundary.
- `docs/STATUS.md`: mutable implementation state, verification boundary, technical debt and next task.
- `docs/DEVELOPMENT_POLICY.md`: branch naming, PR gate, new-module contract, review and merge rules.
- `docs/ARCHITECTURE_INVARIANTS.md`: enforceable architecture invariants for analysis, passes, backend and simulator roles.
- `AGENTS.md`: mandatory rules for human and AI-assisted development.
- `.github/PULL_REQUEST_TEMPLATE.md`: structured completion and remote-safety checklist.
- `.github/ISSUE_TEMPLATE/c1-module-change.yml`: planning template for a new module or milestone change.

The official repository `ephonic/Agentic4SystemSummerSchoolContest` must not be configured as a local Git remote. All project development belongs in `BulletFlying/agentic4systems-c1-compiler-bootstrap` and future non-emergency changes use a feature branch plus PR.

## Current Scope

The checked-in compiler provides:

- Track-B Appendix A raw 128-bit instruction encoding.
- A separated `c2_b3_v2` ISA profile boundary for the C2 tensor encoding.
- PTX parsing for the public C1 syntax shape.
- Basic lowering for parameter loads, special-register moves, integer/FP32 arithmetic, predicates, branches, global loads/stores, f16-to-f32 conversion and aligned u16 load expansion.
- A CFG model with basic blocks, predecessor/successor edges, reverse-postorder traversal, dominators, backedge detection and natural-loop records.
- A conservative uniformity lattice (`UNKNOWN`, `UNIFORM`, `VARYING`) used to prove PTX-02's fixed-count loop backedge is uniform while legalizing its varying boundary exit.
- Raw binary output using `w0,w1,w2,w3` little-endian `uint32_t` order.
- Disassembly for generated raw binaries and C2-style images with a 64-byte `AECI` header.
- A small Track-B semantic simulator for PTX-01 and PTX-02 executable differential tests, including BRX uniformity checks and branch traces.
- PTX-01 and PTX-02 local differential coverage, including partial-warp and invalid-lane global-memory side-effect checks.
- Explicit non-optimizing foundation pipelines and deterministic compilation reports.
- Architecture guardrails and fixed O0 golden hashes for PTX-01/PTX-02.

## Known Gaps

- PTX-02 is locally correctness-validated, but no real CSE, DCE, LICM, basic-block merge or performance scheduling pass is active.
- Uniformity is currently a linear source-order analysis, not a CFG fixed-point analysis for arbitrary block reorder and joins.
- `legacy_varying_branch_items` remains an unsafe compatibility escape hatch for unlegalized varying control and must not underpin later correctness claims.
- PTX-03, PTX-04 and PTX-05 have not been executable-validated.
- No C1 official binary container layout is published, so `aec-cc` defaults to Track-B raw binary.
- Register-pressure handling, spill code, DDG/list scheduling and tensor GEMM lowering are not implemented.
- There is no public C1 Golden Model or Cycle Model in this repository, so current verification is local semantic simulation plus static encoding and CLI smoke testing.

See `docs/STATUS.md` for the detailed debt register and next single main task.

## Verification

Local baseline on the requested Windows environment:

```powershell
C:\Users\HP\anaconda3\envs\zhang\python.exe -m compileall -q src compiler disassembler agent tests
C:\Users\HP\anaconda3\envs\zhang\python.exe -m pytest -q tests
```

Repository CI is configured in `.github/workflows/c1-tests.yml` for Python 3.10 and 3.13. A workflow file existing is not itself evidence that CI passed; check the actual GitHub Actions run before making that claim.
