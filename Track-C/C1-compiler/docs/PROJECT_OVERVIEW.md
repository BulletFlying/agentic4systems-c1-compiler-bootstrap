# C1 Project Overview

This document gives the short project-level world model for `Track-C/C1-compiler/`. It is intentionally higher level than `STATUS.md` and lower level than the contest statement. The authoritative long-form charter is `C1_PROJECT_CHARTER.md`.

## Mission

C1 is an AEC IR compiler project. The deliverable is not a collection of hard-coded answers for the public PTX files. The deliverable is a reproducible compiler toolchain that accepts the official restricted PTX 9.3 scalar subset, builds compiler representations and analyses, emits valid AEC machine code, and reports enough static information to guide participant-side performance modeling.

```text
PTX-style IR
  -> frontend parser
  -> IR / CFG / analyses
  -> optimization and legalization passes
  -> backend lowering / register allocation / scheduling
  -> AEC 128-bit instruction encoding and .aecbin packaging
  -> disassembly and verification
  -> optional report-driven tooling
```

The current repository is a bootstrap compiler workspace. It has local correctness coverage for legacy PTX-01 and PTX-02 regression fixtures, a foundation pass/report framework, architecture guardrails, and official-path 2026-07-13 public T1-T5 testcases. It is not yet a complete contest solution.

## Official alignment

The reduced official C1 task requires a compiler from the specified PTX 9.3 scalar subset to AEC ISA machine code. The scoring-critical invocation is `compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json`. The official `.aecbin` format is a raw AEC 128-bit instruction stream with no Header, Data, Relocation or Symbol Table sections.

The scoring model is correctness-first. Generated code is executed against manifest-defined inputs and compared with reference output; only correct cases enter performance scoring. The new `scoring.md` has 50 correctness points, 40 performance points and 10 robustness points. C1 no longer has an Agent score, and the organizers stated that a Cycle Model will not be provided to participants. The current local simulator is only a local semantic checker and must not be treated as official `aec-precise` CModel evidence.

## Repository roles

`C1_PROJECT_CHARTER.md` defines the mission, scoring map, architecture constraints, milestone route, and acceptance matrix. `STATUS.md` is the mutable implementation ledger and must reflect the current branch truth. `ROADMAP.md` defines the ordered development plan. `ARCHITECTURE.md` defines module boundaries and allowed dependencies. `EVALUATION.md` maps code and tests to the official score. `NON_GOALS.md` prevents scope drift. `AGENT_ARCHITECTURE.md` defines what the Agent is and is not.

When these documents disagree, the resolution order is: official `spec.md` / `scoring.md`, then `C1_PROJECT_CHARTER.md`, then the specialized docs, then `STATUS.md` for current implementation state. A status update may never turn an unverified inference into a confirmed fact.

## Current strategic risk

The project can fail even if individual public PTX files compile. The primary risks are: hard-coding public test structure, growing `compiler.py` back into a monolith, optimizing before correctness is locked, or ignoring the new PTX subset, manifest shape, PMEM ABI, raw `.aecbin` legality and official `aec-precise` integration.

The engineering policy is therefore simple: first restore correctness against the reduced official package and architecture boundaries; then add scoring-aligned optimization passes with regression tests and reports; then use optional tooling only when it directly improves the normal `-O2` compiler path.
