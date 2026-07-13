# C1 Project Overview

This document gives the short project-level world model for `Track-C/C1-compiler/`. It is intentionally higher level than `STATUS.md` and lower level than the contest statement. The authoritative long-form charter is `C1_PROJECT_CHARTER.md`.

## Mission

C1 is an AEC IR compiler project. The deliverable is not a collection of hard-coded answers for the public PTX files. The deliverable is a reproducible compiler toolchain that accepts PTX-style IR, builds compiler representations and analyses, emits valid AEC machine code, and eventually supports an offline Agent that can choose optimization configurations from measured feedback.

```text
PTX-style IR
  -> frontend parser
  -> IR / CFG / analyses
  -> optimization and legalization passes
  -> backend lowering / register allocation / scheduling
  -> AEC 128-bit instruction encoding and .aecbin packaging
  -> disassembly and verification
  -> report-driven Agent optimization loop
```

The current repository is a bootstrap compiler workspace. It has local correctness coverage for PTX-01 and PTX-02, a foundation pass/report framework, architecture guardrails, and an Agent stub that truthfully reports no enabled optimization passes. It is not yet a complete contest solution.

## Official alignment

The official C1 task requires a compiler from PTX-style IR to AEC ISA machine code, including scheduling, register allocation, and multi-precision GEMM optimization passes. It also requires the `aec-cc` CLI with `-O0`, `-O2`, and `-O3`, a legal `.aecbin` output, and a human-readable `aec-objdump` disassembler. The official output format is described as containing Header, Code, Data, Relocation, and Symbol Table sections; the code section uses 128-bit fixed AEC instructions.

The scoring model is correctness-first. A binary is validated, executed by the AEC Golden Model, compared against reference output, and only correct cases enter cycle-model performance scoring. The current local simulator is only a local semantic checker and must not be treated as the official Golden Model.

## Repository roles

`C1_PROJECT_CHARTER.md` defines the mission, scoring map, architecture constraints, milestone route, and acceptance matrix. `STATUS.md` is the mutable implementation ledger and must reflect the current branch truth. `ROADMAP.md` defines the ordered development plan. `ARCHITECTURE.md` defines module boundaries and allowed dependencies. `EVALUATION.md` maps code and tests to the official score. `NON_GOALS.md` prevents scope drift. `AGENT_ARCHITECTURE.md` defines what the Agent is and is not.

When these documents disagree, the resolution order is: official `spec.md` / `scoring.md`, then `C1_PROJECT_CHARTER.md`, then the specialized docs, then `STATUS.md` for current implementation state. A status update may never turn an unverified inference into a confirmed fact.

## Current strategic risk

The project can fail even if individual public PTX files compile. The primary risks are: hard-coding public test structure, growing `compiler.py` back into a monolith, implementing Agent as a chat/config stub rather than a feedback loop, optimizing before correctness is locked, or ignoring `.aecbin`, PMEM ABI, Golden Model, and Cycle Model gaps.

The engineering policy is therefore simple: first preserve correctness and architecture boundaries; then add optimization passes with regression tests and reports; then build an Agent that searches over those passes using measured feedback.
