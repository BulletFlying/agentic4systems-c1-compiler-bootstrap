# C1 AEC Scalar Compiler: Project Charter and Acceptance Baseline

This document is the long-term factual baseline for `Track-C/C1-compiler/`. Mutable implementation state lives in `docs/STATUS.md`. The active official baseline is the reduced C1 package observed on 2026-07-13 in `ephonic/Agentic4SystemSummerSchoolContest`; local C1 package files are LF-normalized text-content-equivalent to official `main` (dce818b, 2026-07-14). Raw blob hashes differ due to `.gitattributes` LF enforcement.

## 1. Mission

C1 is now a PTX 9.3 restricted-scalar-subset to AEC scalar-machine-code compiler. The compiler must accept one `.visible .entry` PTX kernel, build compiler facts and transformations, and emit a raw AEC 128-bit instruction stream `.aecbin`.

```text
PTX ISA 9.3 restricted scalar subset
  -> parser / typed source model
  -> basic blocks / CFG / analyses
  -> scalar lowering and control-flow legalization
  -> scalar optimization pass pipeline
  -> GPR / predicate allocation and scheduling
  -> raw AEC 128-bit instruction stream .aecbin
  -> compile report
```

Required scoring entry point:

```bash
compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json
```

`disassembler/aec-objdump` and `agent/run_agent` are repository development tools, not required C1 scoring entry points under the reduced official package.

Correctness gates performance. A faster binary that fails execution or output checking is a scoring failure, not an optimization.

## 2. Source-of-truth priority

When facts conflict, use this order:

1. Official `Track-C/C1-compiler/spec.md` and `Track-C/C1-compiler/scoring.md` at the currently observed official commit.
2. Official public `testcases/*/kernel.ptx` and `manifest.json` in the same C1 package.
3. Official `Track-C/C1-compiler/hint.md` performance reference target parameters.
4. Official `Track-C/C1-compiler/aec-cmodel/` release docs and binaries for local CModel validation.
5. Official organizer clarification messages, only when tied to the new package.
6. This repository's documents, tests and temporary compatibility policies.

Important superseded assumptions:

- `.aecbin` is no longer an unresolved Header/Code/Data/Relocation/Symbol container. It is a raw AEC 128-bit instruction stream.
- PMEM parameter ABI is no longer unresolved; it is defined in the new `spec.md`.
- C1 no longer requires TMUL, Tensor Load/Store, Tensor registers or low-precision FP4/FP8/INT4/BF16/FP16 GEMM support.
- C1 no longer has an official Agent score. Agent code is optional internal tooling.
- C1 Cycle Model will not be provided. Performance modeling is a participant-side responsibility.
- Official `aec-precise` exposes a `steps` count; organizer clarification says performance measurement is closer to warp-level dynamic execution instruction/step count than to a latency-weighted cycle model.

## 3. Repository and remote safety

`BulletFlying/agentic4systems-c1-compiler-bootstrap` is the only writable project repository. `ephonic/Agentic4SystemSummerSchoolContest` is read-only input and must not be configured as a writable local remote.

No branch, commit, tag, release, PR or issue may be created in the official repository without explicit one-time user authorization. Development changes in this repository should continue through feature branches and PRs.

## 4. Official score mapping

The active score model is:

| Category | Points | Engineering meaning |
|---|---:|---|
| Compile and execution correctness | 50 | Generate `.aecbin`, run under the evaluator, match manifest-defined reference output |
| Generated code efficiency | 40 | Correct cases only; compare against official baseline compiler using evaluator metric |
| Generalization and robustness | 10 | 50 mutation variants; no public-case structural assumptions |

There is no official C1 Agent category under the new `scoring.md`.

Correctness hidden tests are T1-T5 with 20 cases each. Performance points are T1/T2/T3/T4/T5 = 0/8/10/10/12. Robustness tests are T1-T5 variants with 10 cases each.

Official mutation dimensions include parameter scale changes, grid/block dimension changes, register renaming, basic-block order changes, loop-count changes, dead-code insertion, irrelevant computation insertion, register-pressure increase, address-computation changes, memory-access-pattern changes and scalar GEMM size changes.

Any semantic dispatch based on filename, public testcase directory, hash, fixed label, fixed register name, fixed instruction index, or public matrix size is invalid project architecture.

## 5. Compiler architecture baseline

Keep production compiler code separate from tests, development tools and documentation.

```text
ptx.py / frontend     source parsing and source locations
ir/                   compiler representation boundary
cfg.py                CFG, dominators, loops, traversal
analysis/             uniformity, def-use, liveness, alias/memory facts
passes/               scalar transforms and legality-preserving rewrites
lowering/             PTX scalar subset -> AEC legal forms
regalloc.py           physical allocation, pair constraints, spill/reload
scheduler.py          DDG and dependency-preserving scheduling
isa.py                profile constants, encoding and decoding
object.py             raw .aecbin stream writer and format checks
reports/              compile report schema and deterministic metrics
sim.py / tools        local semantic checker only, never official oracle
agent                 optional report-driven pass-policy search tool
```

Architecture constraints:

- Analysis produces facts; passes consume facts and declare invalidation.
- CFG-changing transforms must invalidate or recompute dominance, loop, def-use and uniformity facts.
- Unknown uniformity is not uniform. Branch lowering must be safe for the AEC predicate model.
- Kernel-level PTX `ret` lowers to `HALT`.
- PTX `.param` maps to `.pmem` by official declaration-order and natural-alignment rules.
- PTX `.u64/.b64` pointer values map to AEC register pairs; global memory uses the low 32-bit byte address under the official abstract-address rule.
- Raw `.aecbin` writes each 128-bit instruction as four little-endian `uint32_t` words in `w0,w1,w2,w3` order.
- Local simulator tests are bootstrap evidence only; official `aec-precise` evidence must be tracked separately.

## 6. Roadmap

### M0: ISA, CLI and raw stream foundation

Goal: AEC opcode/type/space encoding, raw `.aecbin` writer, objdump development tool, CLI smoke, project hygiene.

Acceptance: output size is a positive multiple of 16 bytes; supported opcode/type/space fields encode deterministically; malformed inputs fail explicitly.

### M1: T1 basic lowering

Goal: PTX 9.3 restricted-scalar syntax, `.visible .entry`, `.target sm_90`, `.address_size 64`, params, special registers, arithmetic, predicates, global load/store, `ret -> HALT`.

Acceptance: public and mutated T1-style kernels compile and execute correctly under local or official checker.

### M2: T2 scalar optimization

Goal: CFG/control correctness plus constant folding/propagation, DCE, CSE, LICM and basic-block simplification as conservative passes.

Acceptance: `-O2` runs truthful implemented passes; each pass has unit, negative, mutation and executable differential tests; no public-case dispatch.

### M3: T3 memory-access optimization

Goal: repeated global load handling, load hoisting where safe, simple memory reuse, address-computation optimization and memory-instruction reduction.

Acceptance: no unsafe hoist across stores/control boundaries; memory metrics and correctness evidence cover renamed and reordered variants.

### M4: T4 register allocation and scheduling

Goal: GPR/predicate allocation, live-range management, register-pressure handling, load/compute interleaving and dependency-preserving scheduling.

Acceptance: no physical-register overlap, pair constraints are respected, scheduling preserves dependencies and memory order.

### M5: T5 FP32 scalar GEMM

Goal: scalar FP32 GEMM lowering and optimization: two-dimensional indexing, K-loop lowering, FP32 global load/store, multiply-add scheduling and scalar loop optimization.

Acceptance: multiple scalar GEMM sizes and edge cases are correct; no Tensor/TMUL/low-precision scope is claimed or required.

### M6: Optional local optimization controller and packaging

Goal: deterministic report-driven pass-policy selection for local development and final packaging checks.

Acceptance: optional tooling remains offline, correctness-gated and truthful. It is not an official score category under the reduced C1 package.

## 7. Development workflow

For each milestone/sub-milestone:

1. Start from a clean branch and record repository SHA/remote safety.
2. Add or update tests before implementation when practical.
3. Keep production code independent from `tests/` and public testcase names.
4. Run compileall, pytest, CLI smoke, report checks and `git diff --check`.
5. Update `docs/STATUS.md` with exact passed/not-run evidence.
6. Do not claim official CModel success until released `aec-precise` has actually been run.

## 8. Final submission gate

Before claiming C1 readiness, the repository must demonstrate:

- `compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json` works for the active public package shape.
- Raw `.aecbin` follows the official instruction-stream format.
- PMEM ABI and address ABI follow the new `spec.md`.
- T1-T5 public categories have executable correctness evidence.
- T2-T5 have non-case-specific optimization evidence aligned to the new score weights.
- Robustness tests cover renaming, reordering, scale, address and GEMM-size variants.
- Official `aec-precise` evidence is recorded when available.
- No stale claims remain for C1 Agent scoring, Cycle Model availability, Tensor ISA, low-precision GEMM or object-container `.aecbin` layout.
