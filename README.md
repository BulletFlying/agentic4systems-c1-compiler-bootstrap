# AEC Compiler Toolchain

A compiler toolchain that lowers NVIDIA PTX ISA 9.3 scalar programs to AEC (Advanced Execution Core) 128-bit fixed-width machine code. Features a modular optimization pipeline with scalar passes, loop-aware register allocation, and instruction scheduling.

```text
PTX 9.3 (restricted scalar subset)
    → parser / typed source model
    → CFG / dominators / loops / uniformity analysis
    → scalar optimization pass pipeline (O0 / O2 / O3)
    → GPR + predicate allocation and DDG scheduling
    → raw AEC 128-bit instruction stream (.aecbin)
    → deterministic compilation report
```

## Quick Start

```bash
# Compile a PTX kernel with default optimization (O2)
./compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json

# Disassemble the output for inspection
./disassembler/aec-objdump output.aecbin
```

**Requirements:** Python 3.10+. No external dependencies — stdlib only.

## Features

### Compiler Pipeline

| Stage | O2 (default) | Description |
|---|---|---|
| Dead Result Elimination | ✓ | Conservative DRE per basic block |
| Local CSE | ✓ | Basic-block-local common subexpression elimination |
| Constant Folding | ✓ | Local constant propagation and folding |
| Global Constant Propagation | ✓ | Cross-block constant propagation |
| Load Reuse | ✓ | Repeated global load reuse |
| Global DCE | ✓ | Worklist-based dead code elimination |
| LICM | ✓ | Loop-invariant code motion |
| Block Simplification | ✓ | Merge and unreachable-block removal |
| Load Hoisting | ✓ | Safe load hoisting across control |
| Loop Unrolling | ✓ | GEMM loop unrolling (factor 2) |
| Register Allocation | ✓ | Loop-aware linear-scan GPR + predicate allocation |
| Scheduling | ✓ | Post-lowering DDG list scheduler |

### ISA Profiles

- **Default** (`c1_default`): 18 AEC opcodes covering arithmetic, logic, memory, control flow, and data movement
- **Extended** (`track_b_v1`): 50+ opcodes with additional math, conversion, atomics, and synchronization — available via `--profile track_b_v1`

### AEC Binary Format

Raw 128-bit instruction stream (`.aecbin`) — no header, no sections, no symbol table. Each instruction is stored as four little-endian `uint32_t` words. See `docs/spec.md` for the complete ISA reference.

### Compilation Report

Deterministic JSON report with static metrics: instruction counts, register usage, spill stats, pass execution records, and scheduler warnings.

## Repository Structure

```
compiler/aec-cc         — Compiler entry point
src/aec_compiler/       — Compiler source package
  analysis/             — CFG, liveness, uniformity analysis
  ir/                   — Internal representation
  passes/               — Optimization and lowering passes
  reports/              — Compilation report generation
disassembler/           — Diagnostic disassembler (aec-objdump)
aec-cmodel/             — Reference CModel binaries and docs
tests/                  — Unit, integration, and e2e test suite
testcases/              — Public test kernels (PTX + manifest)
docs/                   — Architecture and development docs
```

## Verification

```bash
# Syntax check all Python sources
python -m compileall -q src compiler disassembler tests

# Run fast test suite (~210 tests)
python -m pytest -q tests

# Run end-to-end manifest tests
python -m pytest -q tests/test_manifest_execution.py -m slow -v
```

CI runs on Python 3.10 and 3.13 via GitHub Actions.

## Documentation

- `docs/spec.md` — Input language, AEC ISA, ABI, and binary format specification
- `docs/ARCHITECTURE.md` — Module boundaries and dependency direction
- `docs/ARCHITECTURE_INVARIANTS.md` — Enforceable architecture constraints
- `docs/ROADMAP.md` — Development plan and phase gates
- `docs/STATUS.md` — Current implementation state and verification evidence
- `docs/PERFORMANCE_MODEL.md` — Performance modeling and target platform parameters

## License

MIT License. See `LICENSE` for details.
