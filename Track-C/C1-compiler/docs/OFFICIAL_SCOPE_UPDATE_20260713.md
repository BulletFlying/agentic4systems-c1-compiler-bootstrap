# 2026-07-13 Official C1 Scope Update

This document records the reduced official C1 requirement baseline observed in `ephonic/Agentic4SystemSummerSchoolContest` at commit `68a4aea16e69045e397d12333244f7974245d49c` and in the uploaded `C1编译器赛题.zip` package.

## Source snapshot

```text
Official repository: ephonic/Agentic4SystemSummerSchoolContest
Observed commit: 68a4aea16e69045e397d12333244f7974245d49c
Updated files:
- Track-C/C1-compiler/spec.md
- Track-C/C1-compiler/scoring.md
- Track-C/C1-compiler/testcases/*/kernel.ptx
- Track-C/C1-compiler/testcases/*/manifest.json
```

The new package is the active C1 baseline. Older references to Tensor ISA, multi-precision GEMM, C1 Agent scoring, C1 Cycle Model availability, and object-container `.aecbin` layout are superseded unless the official repository changes again.

## Main deltas from the previous internal plan

| Area | Previous working assumption | New official scope |
|---|---|---|
| Input PTX | PTX-like IR, earlier public syntax | PTX ISA 9.3 restricted scalar subset |
| Kernel form | Earlier `.kernel` style accepted locally | `.visible .entry`, `.target sm_90`, `.address_size 64` |
| Binary format | Header/Code/Data/Reloc/Symtab unresolved | `.aecbin` is raw AEC 128-bit instruction stream |
| Parameter ABI | PMEM ABI unresolved | `.param` maps to `.pmem` by declaration order, natural alignment, 8-byte block alignment |
| Tensor/TMUL | Possible T5 tensor profile / low precision | Not required |
| GEMM | Multi-precision GEMM concern | FP32 scalar GEMM only |
| Cycle Model | Expected but unavailable | Will not be provided; teams build their own performance model |
| Golden Model | Unavailable | Organizers plan to release an ARM AEC Golden Model for correctness self-test |
| Agent scoring | Previously 10 points | Removed from new scoring |
| Evaluation opt level | Unclear / O0-O3 discussed | Evaluator compiles with `-O2` |
| Submission | Compiler + objdump + agent under older assumption | Official text now requires compiler source and `compiler/aec-cc` |

## New score model

The new official scoring is:

```text
correctness_score <= 50
performance_score <= 40
robustness_score  <= 10
total_score       <= 100
```

There is no C1 Agent score in the new `scoring.md`. Agent code in this repository is now optional development infrastructure only. It must not be described as an official-scoring requirement.

Performance is correctness-gated. The evaluator uses official baseline compiler results as the reference and computes category-level geometric-mean speedups. T1 has no performance points; T2/T3/T4/T5 carry 8/10/10/12 performance points respectively.

## New milestone interpretation

The repository milestones are retained for engineering continuity but must be reinterpreted:

- M0/M1/M2.1/M2.2 remain useful for parser, CFG, scalar-pass and report foundation.
- M3 now targets global-memory load reuse, load hoisting, simple reuse and address-computation optimization. Shared-memory promotion is optional unless justified by the new scalar-only workload.
- M4 still targets GPR/predicate allocation, live-range management, register pressure, load/compute interleaving and dependency scheduling.
- M5 is now FP32 scalar GEMM only. Remove Tensor, TMUL, tensor load/store, FP4/FP8/INT4/INT8/BF16/FP16 scope from C1 plans.
- M6 Agent is no longer an official C1 milestone. Keep deterministic optimization-loop work only as optional tooling for pass-policy search and report analysis.

## Immediate implementation implications

The next engineering task should not be Agent-first. It should be official package alignment:

1. Add new public testcase package support without deleting old regression fixtures.
2. Extend parser/frontend for `.visible .entry`, `.target sm_90`, `.address_size 64`, `.s32/.b32/.b64`, `ld.global.*`, `mul.lo.u32`, `mad.lo.u32`, `mul.wide.u32`, `mad.rn.f32` and `fma.rn.f32` where not already supported.
3. Make PMEM parameter layout follow the official ABI.
4. Make raw `.aecbin` output the official default and remove any blocker language implying Header/Data/Reloc/Symtab are still required.
5. Add manifest-aware local test harness structure for public T1-T5 examples.
6. Ensure `-O2` is the scoring-critical pipeline while keeping `-O0` as a local regression baseline.
7. Reprioritize code work toward T3/T4/T5 scalar workloads after the parser/ABI/test-harness alignment passes.

## Boundary

This update changes project planning and documentation only. It does not by itself prove the compiler supports the new public package. It also does not authorize testcase-name dispatch, fixed-register hacks, or performance claims without correctness evidence.
