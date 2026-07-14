# C1 Non-Goals and Scope Boundaries

This document prevents scope drift. A C1 compiler that tries to become every adjacent system will likely miss the actual scoring path.

## Non-goals

C1 is not a full LLVM replacement. Implement only the IR, analyses, passes, and backend structures needed for the contest path. Do not introduce generic compiler abstractions unless they are required by a concrete pass or correctness proof.

C1 is not a CUDA compiler. The input is PTX-style IR in the contest shape, not arbitrary CUDA C++ or arbitrary PTX from NVIDIA tools.

C1 is not a GPU runtime. Do not build kernel launch infrastructure, memory allocators, device synchronization APIs, or host runtime behavior unless the official C1 interface requires it.

C1 is not C2 or C3. Keep historical C2/B3 tensor encoding facts isolated if they remain in source for reference. Do not import C2 runtime assumptions, C2 tensor ISA work, or C3 ONNX/compiler-stack assumptions into the default C1 path.

C1 is not a public-testcase answer generator. Do not select behavior from filenames, public test IDs, source hashes, fixed labels, fixed register names, or fixed instruction positions.

C1 is not an online-LLM benchmark. The Agent may be inspired by LLM planning, but final correctness and scoring must be reproducible without online inference.

C1 is not an official validator. Local simulator checks, encoder round trips, and objdump output are useful evidence but do not replace official `aec-precise` CModel evidence. The reduced C1 package says a Cycle Model will not be provided to participants, so local performance-model estimates must be labeled as estimates.

## Work that should wait

Do not implement broad CSE, broad DCE, LICM, scheduler, GEMM specialization, or optional controller search before the required IR/analysis/report contracts exist and have tests.

Do not add new public-case support by extending `legacy_lowering.py` unless the change is a correctness-preserving legality fix with regression coverage. New optimization behavior belongs in passes.

Do not add Header/Data/Relocation/Symbol sections to `.aecbin` unless the official C1 `spec.md` changes again. The current official format is a raw AEC 128-bit instruction stream.

Do not claim official score improvement from local tests. Local differential tests show repository health; official readiness requires official-model evidence when available.

## Acceptable temporary compromises

A temporary compatibility layer is acceptable when it is isolated, documented, and protected by tests. `legacy_lowering.py` is such a boundary. It must not become the location where future optimization passes are hidden.

A conservative fallback is acceptable when correctness is uncertain. Rejecting unsupported input is better than silently generating a wrong binary.

A minimal IR is acceptable during M2.2-A. It should grow only when a real pass requires additional structure.

Optional controller tooling is acceptable only while it is truthfully labeled as non-scoring infrastructure and does not change the required `compiler/aec-cc ... -O2 ... --report ...` evaluation path.
