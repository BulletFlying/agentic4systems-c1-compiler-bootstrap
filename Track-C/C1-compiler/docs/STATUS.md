# C1 Compiler Status

This file is the mutable implementation ledger for `Track-C/C1-compiler/`. Long-term goals and scoring constraints live in `C1_PROJECT_CHARTER.md`; operating rules live in `../AGENTS.md` and `DEVELOPMENT_POLICY.md`.

## Snapshot

Status date: 2026-07-13

Writable repository: `BulletFlying/agentic4systems-c1-compiler-bootstrap`

Local Git remote policy: only `origin` pointing to `BulletFlying/agentic4systems-c1-compiler-bootstrap`

Official repository remote: not configured

## Milestone state

| Milestone | State | Evidence boundary |
|---|---|---|
| M0 ISA/CLI/encoder baseline | Locally complete | Track-B raw encoder, decoder, objdump and smoke checks exist |
| M1 PTX-01 correctness loop | Locally complete | Partial-warp and randomized differential tests exist |
| M2.1 PTX-02 CFG/uniform-loop correctness | Locally complete | CFG, dominators, uniformity analysis and executable tests exist |
| M2.2 architecture foundation | Locally complete | IR facade, analysis manager, pass manager, reports and foundation pipelines exist |
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
- Availability and interface of the official C1 Golden Model, Cycle Model, validator and scoring script.

## Verification boundary

Local completion does not mean official Golden Model, Cycle Model or grader approval.

## Next single main task

M2.2 scalar optimization preparation:

1. Improve IR contracts where required.
2. Keep architecture guardrails enforced.
3. Introduce optimization transforms only through pass abstractions with regression tests.
4. Do not bypass the M2.2 correctness gate for PTX-03/04/05 work.
