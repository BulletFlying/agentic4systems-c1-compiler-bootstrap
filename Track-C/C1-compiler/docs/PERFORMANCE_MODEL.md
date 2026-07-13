# C1 Performance Model Guidance

This document records the 2026-07-13 organizer clarification about Track-C AI Inference performance optimization and translates it into C1 compiler work items.

## Organizer clarification

The organizer clarified that Track-C performance optimization is intended to prepare for the future integration of Tracks A, B and C. Track-C performance work should therefore remain tied to the architecture designed in Track-B. At the current stage, teams are not required to handle full cross-track integration, but may use the provided NVIDIA-like general-purpose GPU performance parameters as the current target-hardware indicators.

The organizer also suggested building a Performance Model from these parameters, using the model to analyze compute, memory access and data-movement bottlenecks, and then using measurement from realistic workloads to evaluate and correct the model.

The slide-deck screenshots supplied on 2026-07-13 provide the current target-hardware indicators below. Treat them as contest guidance for model construction, not as an official C1 Cycle Model schema.

## Target hardware indicators

The C1 model should stay aligned with the Track-B AEC GPGPU architecture because C1-generated binaries are evaluated against that ISA and model direction.

| Indicator | Slide value | C1 model implication |
|---|---:|---|
| Instruction width | 128-bit fixed | Instruction count maps directly to code bytes at 16 bytes per instruction |
| Register file | 256 x 32-bit registers per thread | CSE, LICM, unroll and tiling choices must account for register pressure |
| Predicate registers | 8 independent predicates, P0-P7 | Predicate allocation is a finite resource, not an unbounded PTX namespace |
| Execution granularity | Warp = 32 lanes | Branch legality and memory coalescing should be reasoned at warp granularity |
| CTA limit | CTA <= 256 threads, 8 warps | Occupancy and shared-memory use should be reported per CTA where possible |
| Memory spaces | `.gmem`, `.smem`, `.cmem`, `.lmem`, `.pmem` | Reports should separate global, shared, constant, local and parameter traffic |
| Shared memory | 65536 bytes per CTA, fixed | Shared-memory promotion and GEMM tiling must fit this per-CTA budget |
| Local memory | 4096 bytes per thread | Spill modeling should report estimated local-memory pressure |
| Memory service | 128-byte line, 32-cycle latency, 16 outstanding requests | Memory model should estimate cache-line traffic, latency exposure and request-level parallelism |

Toolchain constraints from the same slide deck: Python 3.10+ applies to Tracks A and C, and GCC/G++ 13.3.0 applies to Tracks B and C. The local development environment may use Python 3.13, but submitted code should remain compatible with Python 3.10+ unless the official environment changes.

## Track-B PPA signals for C1 modeling

Track-B scoring is not C1 scoring, but it gives useful architectural signals for a C1 performance model:

```text
T_i = W_i * f_max / C_i
```

where `W_i` is effective work, `C_i` is measured Verilator cycles, and `f_max` is the OpenSTA maximum frequency.

The workload units shown in the slide deck are:

| Workload | Effective work `W_i` | Report unit |
|---|---|---|
| GEMM M x N x K | `2 * M * N * K` | GOP/s |
| Copy / transpose | read bytes + written bytes | GB/s |
| Vector add | element count | Gelement/s |

SRAM macro area constants shown for Track-B are:

| SRAM macro | Area |
|---|---:|
| 256 x 32 | 415.24 um^2 |
| 512 x 32 | 691.20 um^2 |
| 1024 x 32 | 1311.03 um^2 |
| 256 x 64 | 747.43 um^2 |

These SRAM constants are hardware-design inputs, not direct C1 scoring terms. They are useful only when explaining shared-memory capacity pressure or future cross-track PPA reasoning.

## C1 interpretation

C1 is still a CPU-executed compiler that emits AEC ISA binaries. The new clarification does not make CUDA, H200, PyTorch or NVIDIA runtime support a dependency of `aec-cc`.

The clarification does change how performance work should be planned. C1 optimizations should be driven by an explicit target model rather than by isolated pass-local metrics. For each optimization candidate, the compiler or Agent should be able to explain which modeled bottleneck it is attempting to improve.

In short:

```text
PTX-like IR
  -> C1 analyses and optimization passes
  -> AEC ISA binary
  -> AEC validator / Golden Model / Cycle Model
  -> performance report
  -> C1 performance model update
  -> Agent or pass-policy update
```

## Model scope

The first C1 performance model should be simple, serializable and conservative. It should not attempt to replace the official AEC Cycle Model.

Minimum model dimensions:

| Dimension | Purpose | Initial C1 use |
|---|---|---|
| Instruction mix | Estimate scalar, memory and tensor pressure | Guide pass selection and scheduling work |
| Register pressure | Estimate spill risk and occupancy loss | Bound CSE, LICM, unroll and tiling aggressiveness |
| Global-memory traffic | Estimate line transactions and bandwidth bottlenecks | Guide load reuse and memory coalescing work |
| Shared-memory use | Estimate promotion benefit and per-CTA capacity pressure | Guide PTX-03 and GEMM tiling work |
| Data movement | Track GMEM/SMEM/register movement cost | Explain bottleneck migration after optimization |
| Dependency depth | Estimate latency hiding and scheduling opportunity | Guide DDG/list-scheduling work |
| Tensor tile shape | Estimate arithmetic intensity and boundary overhead | Guide PTX-05 tile search |

The model must remain an explanatory and search-guidance layer. Correctness must still be enforced by executable validation.

## Required report schema direction

Future compilation reports should expose model inputs and pass effects in machine-readable form so the Agent can run a closed loop. A minimal report should include:

```json
{
  "compiler_commit": "...",
  "input_fingerprint": "...",
  "target_profile": "track_b_v1 or official-aec-profile",
  "optimization_level": "O0/O2/O3",
  "enabled_passes": [],
  "static_metrics": {
    "instruction_count": 0,
    "branch_count": 0,
    "gmem_loads": 0,
    "gmem_stores": 0,
    "estimated_gmem_bytes": 0,
    "estimated_gmem_lines_128b": 0,
    "smem_ops": 0,
    "estimated_smem_bytes_per_cta": null,
    "estimated_register_pressure": null,
    "estimated_lmem_bytes_per_thread": null,
    "estimated_dependency_depth": null,
    "estimated_arithmetic_intensity": null
  },
  "cycle_model_metrics": {
    "total_cycles": null,
    "spill_count": null,
    "dual_issue_rate": null,
    "memory_transactions": null,
    "stall_cycles": null
  },
  "model_diagnosis": [],
  "notes": []
}
```

Use `null` for unavailable official metrics. Do not fabricate official Cycle Model data.

## Optimization implications by milestone

### M2.2 scalar foundation

The pass framework should record pass effects and model-visible metrics. Constant folding, DCE, CSE and LICM should not be judged only by instruction-count reduction. They must also report whether they increase live ranges or risk register pressure.

### M3 memory optimization

Load reuse, coalescing and shared-memory promotion should be implemented with an explicit memory-traffic model. The model should distinguish reduced global traffic from increased shared-memory traffic, synchronization and address-generation overhead.

### M4 register allocation and scheduling

Register allocation, spill generation and DDG/list scheduling should consume static pressure and dependency metrics. A pass that improves instruction count but increases spills should be treated as suspect until validated by Cycle Model feedback.

### M5 GEMM and tensor optimization

Tile search should not be restricted to human-friendly divisors unless required by legality. Non-divisible tiles may be valid candidates if the modeled boundary overhead is outweighed by better arithmetic intensity, memory behavior or tensor utilization.

### M6 Agent

The Agent should treat the performance model as a local world model. The default Agent must remain offline and deterministic enough to run in the official environment. Any LLM advisor is optional and must not be required for the baseline closed loop.

## Non-goals

This document does not introduce a requirement that C1 run on NVIDIA GPUs. It also does not authorize hard-coding public testcase names, matrix sizes, labels, register numbers or hashes into compilation decisions.

## Open blockers

- A machine-readable official target-hardware parameter file is not available; the current constants are recorded from slide screenshots.
- The official C1 `.aecbin` container layout is still unresolved.
- The official PMEM ABI is still unresolved.
- The final T5 tensor profile, Track-B versus C2/B3 or another frozen profile, is still unresolved.
- The official C1 validator, Golden Model, Cycle Model and report schema are still unavailable in this repository.
