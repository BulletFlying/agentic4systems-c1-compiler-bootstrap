# AEC Compiler Toolchain — Project Overview

This document provides the high-level world model for the AEC Compiler Toolchain repository. The authoritative architecture documentation is `ARCHITECTURE.md`.

## Mission

The AEC Compiler Toolchain is a reproducible compiler that accepts a restricted NVIDIA PTX ISA 9.3 scalar subset, builds compiler representations and analyses, emits valid AEC 128-bit machine code, and reports static metrics for performance modeling.

```text
PTX 9.3 scalar subset
  → frontend parser
  → IR / CFG / analyses
  → optimization and legalization passes
  → backend lowering / register allocation / scheduling
  → AEC 128-bit instruction encoding and .aecbin output
  → disassembly and verification
  → compilation report
```

## Supported Input

- NVIDIA PTX ISA 9.3 restricted scalar subset
- Single `.visible .entry` kernel per compilation unit
- Types: `.pred`, `.b32`, `.b64`, `.u32`, `.s32`, `.u64`, `.f32`
- Operations: parameter loads, special registers, integer/FP32 arithmetic, bitwise/shift, comparisons, branches, global memory load/store

## Supported Output

- Raw AEC 128-bit instruction stream (`.aecbin`)
- 18-opcode default ISA profile (arithmetic, logic, memory, control flow, data movement)
- Extended ISA profile with 50+ opcodes available via `--profile track_b_v1`
- Deterministic JSON compilation report with static metrics

## Repository Roles

| Document | Purpose |
|---|---|
| `docs/ARCHITECTURE.md` | Module boundaries and allowed dependencies |
| `docs/ARCHITECTURE_INVARIANTS.md` | Enforceable architecture constraints |
| `docs/ROADMAP.md` | Development plan and phase gates |
| `docs/STATUS.md` | Mutable implementation ledger |
| `docs/PERFORMANCE_MODEL.md` | Performance modeling and target platform parameters |
| `docs/DEVELOPMENT_POLICY.md` | Branch naming, PR gates, and review rules |
| `AGENTS.md` | Development rules for human and AI-assisted contributions |

When these documents disagree, the resolution order is: `ARCHITECTURE_INVARIANTS.md`, then `ARCHITECTURE.md`, then specialized docs, then `STATUS.md` for current implementation state.
