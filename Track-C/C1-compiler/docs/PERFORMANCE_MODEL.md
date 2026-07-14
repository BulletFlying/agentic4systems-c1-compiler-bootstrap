# C1 Performance Model Guidance

This document records performance-model guidance for the active reduced C1 package.

## Official target parameters

The official `Track-C/C1-compiler/hint.md` file remains useful for constructing a participant-side performance model. A local machine-readable transcription is stored at:

```text
docs/performance_targets/track_c_hint_20260713.json
```

The official Platform A/B table includes per-SM register file, unified L1/Shared-Memory pool, max Shared Memory, Shared-Memory bank organization, L2, HBM capacity/bandwidth, host interconnect, GPU interconnect and reference memory latencies.

## New official boundary

The reduced C1 package states that a Cycle Model will not be provided to participants. Teams should build their own performance model. Therefore this repository must not describe `cycle_model_metrics` as an expected official input for local development. Existing `cycle_model_metrics: null` report placeholders may remain as backward-compatible fields, but they are not an active official-data interface.

Organizer clarification says the official performance metric is closer to warp-level dynamic execution instruction/step count than to a latency-weighted cycle simulator. The released `aec-precise` CModel prints stdout JSON with `steps`; use that as the closest official local observation when available. Memory latency estimates from `hint.md` remain useful for optimization reasoning, but they should not be treated as the scoring metric itself.

C1 is still a CPU-executed compiler that emits AEC scalar machine code. The `Track-C/C1-compiler/hint.md` guidance does not make CUDA, H200, PyTorch, `nvcc`, `ncu` or `nsys` dependencies of `compiler/aec-cc`.

Auxiliary real-GPU profiling may be used outside the compiler to calibrate intuition, but such measurements are not official `aec-precise` CModel results and must be labeled as auxiliary.

## Model scope under the reduced package

The first useful C1 model should stay simple, serializable and conservative:

| Dimension | Purpose | C1 use |
|---|---|---|
| Dynamic step count | Closest released CModel observation for scoring pressure | Compare O2 pass candidates through `aec-precise` when runnable |
| Static instruction count and mix | Approximate scalar execution pressure before running CModel | Compare O2 pass candidates |
| Register and predicate count | Estimate pressure and allocation risk | Guide T4 work and avoid pass regressions |
| Spill count | Track local-memory pressure once implemented | Reject transformations that create spill-heavy code |
| Branch count | Estimate control overhead | Guide CFG simplification and loop lowering |
| Load/store count | Estimate memory instruction pressure | Guide T3 memory optimization |
| Memory instruction ratio | Explain memory-bound kernels | Prioritize load reuse and address optimization |
| Static GMEM traffic | Estimate coarse bandwidth pressure | Compare candidate transformations |
| Dependency depth | Estimate scheduling opportunity | Guide T4 list scheduling |
| Arithmetic intensity | Explain scalar GEMM and reuse behavior | Guide T5 FP32 scalar GEMM work |

Tensor tile shape and low-precision tensor utilization are no longer C1 model dimensions because the new C1 scope does not require Tensor instructions or low-precision GEMM.

## Recommended compile report direction

The official `spec.md` shows a compile-report example with fields such as PTX/AEC instruction counts, block/register/predicate counts, spill counts, pass flags and warnings. Repository reports should converge toward these diagnostics while preserving useful existing fields:

```json
{
  "status": "ok",
  "input": "kernel.ptx",
  "output": "output.aecbin",
  "opt_level": "O2",
  "num_ptx_instructions": 0,
  "num_aec_instructions": 0,
  "num_basic_blocks": 0,
  "num_virtual_registers": 0,
  "num_physical_registers": null,
  "num_predicates": 0,
  "spills": {
    "loads": 0,
    "stores": 0
  },
  "passes": {},
  "static_metrics": {
    "instruction_count": 0,
    "register_count": null,
    "predicate_count": null,
    "spill_count": null,
    "branch_count": 0,
    "load_count": 0,
    "store_count": 0,
    "memory_instruction_ratio": null,
    "estimated_dependency_depth": null,
    "estimated_gmem_128b_services_per_warp": null,
    "estimated_arithmetic_intensity": null
  },
  "auxiliary_real_gpu_metrics": null,
  "warnings": []
}
```

Use `null` for unavailable estimates. Do not fabricate official measurements.

## Optimization implications by official family

T2 scalar optimization: report pass-level effects for constant folding/propagation, DCE, CSE, LICM and block simplification. Instruction-count reduction is useful only if executable correctness is preserved.

T3 memory optimization: focus on repeated global loads, safe load hoisting, simple reuse, address-computation optimization and memory-instruction reduction. Shared-memory promotion is optional and must be justified by legality and correctness evidence.

T4 register allocation and scheduling: track register/predicate count, live ranges, spills, dependency depth and load/compute interleaving. A transformation that reduces instructions but increases spill pressure must be treated as suspect.

T5 FP32 scalar GEMM: model scalar K-loop cost, global memory traffic, multiply-add count, dependency depth and register pressure. Do not plan for TMUL, Tensor Load/Store or low-precision tile search in C1.

## Non-goals

This document does not authorize public testcase-name dispatch, matrix-size dispatch, fixed-register hacks, CUDA runtime dependency, Cycle Model fabrication, Tensor ISA work or low-precision GEMM work for C1.
