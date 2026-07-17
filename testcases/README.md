# Testcases

Public test kernels for the AEC Compiler Toolchain. Each test case consists of two files:

```text
kernel.ptx      # Input PTX program
manifest.json   # Test run configuration
```

The manifest describes kernel name, grid/block dimensions, parameters, input/output buffers, and correctness check rules. The PTX file contains only kernel code.

## Categories

| Directory | Focus |
|---|---|
| `T1_basic_lowering/` | PTX parsing, parameter loading, special registers, basic arithmetic, load/store, branch, ret lowering |
| `T2_scalar_optimization/` | Constant propagation, dead code elimination, CSE, LICM, block merging |
| `T3_memory_reuse/` | Repeated global load, load hoisting, memory reuse, address optimization |
| `T4_register_scheduling/` | GPR/predicate allocation, live range management, register pressure, instruction scheduling |
| `T5_scalar_gemm/` | FP32 scalar GEMM, 2D indexing, K-loop, multiply-add scheduling |
