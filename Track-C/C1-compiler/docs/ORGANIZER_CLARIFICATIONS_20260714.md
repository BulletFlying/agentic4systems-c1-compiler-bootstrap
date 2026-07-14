# Organizer Clarifications 2026-07-14

This document records organizer clarifications that arrived after the reduced C1 package was mirrored into this repository. It is an implementation-facing errata ledger, not a replacement for the official repository.

## Source boundary

Official repository checked:

```text
ephonic/Agentic4SystemSummerSchoolContest
latest observed main: c30b3f9eed11183fee8e33735e82cdf72a50cbe8
```

Relevant official commits observed:

```text
f3b8b3e 添加 C1-compiler aec-cmodel 评测工具
dce818b 更新 C3-scheduler spec.md 并增加 C35_WORKER_PROTOCOL.md
c30b3f9 更新 C2-runtime starter-kit 虚拟设备库及发布清单
```

The current upstream C1 `spec.md` still shows `shl.b32 -> SHL.b32` in the lowering table. The organizer clarification below supersedes that stale row until upstream `spec.md` is updated.

## C1 clarification: `shl.b32` encodes as `SHL.u32`

Actionable rule:

```text
PTX input remains:  shl.b32 dst, a, b
AEC output must be: SHL.u32 dst, a, b
```

This changes only the AEC type-code field used in the output encoding. It does not change PTX source syntax and does not change the bit-level result, which remains `Rs1 << (Rs2 & 31)`.

Implementation implications:

```text
1. Parser must continue accepting PTX `shl.b32`.
2. Lowering/encoding must emit a legal AEC `SHL` instruction with type `.u32`.
3. Tests must check the encoded/decode-observed AEC type, not merely the internal PTX source type.
4. `AND.b32`, `OR.b32` and `XOR.b32` remain `.b32`; do not globally remap `.b32` to `.u32`.
```

## C1 clarification: no warp-divergent branch / reconvergence requirement

Organizer rule:

```text
C1 does not require support for warp-internal divergent branch or reconvergence.
BRX is a warp-level conditional branch.
Before BRX executes, all currently active lanes in the warp must agree on the branch condition.
If active lanes disagree, aec-precise returning `non-uniform branch` is expected behavior.
Official hidden tests will guarantee BRX is uniform on legal execution paths.
```

Implementation implications:

```text
1. The compiler must not implement a CUDA-style reconvergence stack for C1.
2. Branch lowering may reject or if-convert branches not proven safe.
3. Correctness tests should include uniform BRX and negated-uniform BRX.
4. Divergent branch programs are negative tests, not functionality that C1 must support.
5. Any legacy fallback that allows varying BRX should be treated as technical debt, not as an official feature.
```

## C1 CModel / performance-model status

The official `aec-cmodel/` release provides `aec-precise` command documentation and binaries. It runs AEC binaries, supports memory load/dump arguments, and prints JSON status including `steps`. It is a correctness/debugging CModel, not a Cycle Model.

The organizer continues to state that C1 Cycle Model will not be provided. Participants may build their own performance model using the provided NVIDIA-like target parameters. The model should guide optimization, but fabricated official cycle metrics are forbidden.

The official baseline compiler performance numbers are not public. Local performance work should compare pass candidates through available static metrics and `aec-precise` step observations when runnable.

## Cross-track notes that must not contaminate C1

The same organizer discussion also included C3 and C2 answers. They are recorded here only to prevent accidental scope drift.

C3 notes:

```text
C3 has a containerized H200 MIG environment.
C3 allows custom CUDA kernels through CuPy.
C3 model measurement uses separate processes, no cache persistence, warmup 2, repeat 5 average.
C3 aggregation and ranking rules are C3-only.
```

C2 notes:

```text
The C2 controlled device library was updated.
DOT/NRM2 support the documented 1,048,576 length with the new libaec_device.so.
FP4/INT4 high-nibble legality is an input-format guarantee; hidden tests will not use illegal packed inputs.
```

These C2/C3 facts are not C1 requirements. They must not introduce CUDA, CuPy, ONNX, PyTorch, H200, C2 `libaec_device.so`, Host-side validation, DOT/NRM2 or FP4/INT4 work into the C1 compiler path.
