# Legacy Regression PTX Fixtures

This directory contains earlier single-file PTX regression fixtures kept for continuity of local compiler tests. They predate the current manifest-based test structure under `testcases/`.

The current test package (`../../../testcases/`) uses one directory per category with `kernel.ptx` + `manifest.json`.

## Legacy Fixtures

| File | Role |
|---|---|
| `PTX-01_vector_add.ptx` | Vector-add lowering regression |
| `PTX-02_invariant_poly.ptx` | CFG/scalar optimization regression |
| `PTX-03_repeated_reuse.ptx` | Memory-reuse fixture |
| `PTX-04_reg_schedule.ptx` | Register/scheduling fixture |
| `PTX-05_gemm_f16.ptx` | Pre-reduction GEMM fixture |

## Current Test Categories

Use `testcases/` for new test work. Categories:
- T1: basic lowering
- T2: scalar optimization
- T3: memory reuse
- T4: register allocation and scheduling
- T5: FP32 scalar GEMM

The scope excludes Tensor/TMUL, Tensor load/store, and low-precision (FP4/FP8/BF16/INT4/INT8) GEMM. Do not use this legacy directory to infer current test structure.
