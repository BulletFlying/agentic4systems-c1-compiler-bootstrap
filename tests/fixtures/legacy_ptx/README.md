# Legacy C1 Regression PTX Files

This directory contains the earlier single-file PTX regression fixtures kept for
continuity of local compiler tests. They are not the active official public
package after the 2026-07-13 C1 scope reduction.

The active official package is mirrored at:

```text
../../../testcases/
```

That package uses one directory per category, with:

```text
kernel.ptx
manifest.json
```

## Legacy Fixtures

| File | Legacy role |
|---|---|
| `PTX-01_vector_add.ptx` | Earlier T1 vector-add lowering regression |
| `PTX-02_invariant_poly.ptx` | Earlier T2 CFG/scalar optimization regression |
| `PTX-03_repeated_reuse.ptx` | Earlier T3 memory-reuse planning fixture |
| `PTX-04_reg_schedule.ptx` | Earlier T4 register/scheduling planning fixture |
| `PTX-05_gemm_f16.ptx` | Earlier pre-reduction GEMM fixture |

## Current Official Scope

Use `testcases/` for new public-package alignment work. The
current official `scoring.md` defines:

- T1: basic lowering
- T2: scalar optimization
- T3: memory reuse
- T4: register allocation and scheduling
- T5: FP32 scalar GEMM

The reduced C1 task does not require Tensor/TMUL, Tensor load/store, FP16 GEMM,
FP4/FP8/BF16/INT4/INT8/INT32 GEMM, or multi-precision hidden GEMM matrices.

Do not use this legacy directory to infer active official testcase names,
manifest shape, scoring weights, precision coverage, or hidden-test structure.
