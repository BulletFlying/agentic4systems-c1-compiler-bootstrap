# C1 Compiler Architecture Invariants

This document defines structural rules for the compiler framework introduced in M2.2-A.
The goal is to prevent incremental feature work from turning the compiler into a monolithic implementation.

## Layer ownership

### Analysis

Analysis modules compute reusable facts only.

Allowed:

```text
IR -> AnalysisResult / Facts
```

Forbidden:

```text
Analysis -> mutate IR
Analysis -> emit ISA
Analysis -> depend on compiler pipeline state
```

Examples include CFG construction, uniformity analysis, liveness, and memory facts.

## Pass framework

Compiler transformations must be represented as passes.

Required interface:

```text
Pass.run(IR, AnalysisManager) -> PassResult
```

A pass must declare analysis invalidation explicitly.

Forbidden:

- hidden global compiler state
- modifying unrelated compiler phases directly
- adding optimization behavior into CLI handling

## Backend isolation

Backend code converts validated compiler representations into target instructions.

Forbidden:

```text
if testcase == PTX-xx
if filename == xxx
if register == special_case
```

Target behavior must be represented by ISA profiles and normal compiler rules.

The 2026-07-14 `shl.b32 -> SHL.u32` organizer erratum is a target encoding rule, not a public-case shortcut. It must be implemented as a general opcode/type rule and covered by tests.

## Branch semantics boundary

C1 does not require warp-internal divergent branch or reconvergence support.

Required behavior:

```text
BRX may be emitted only for branches proven or assumed legal under the active-lane-uniform condition.
If a branch is not safe, the compiler should reject it or legalize it by a general transformation such as if-conversion.
```

Forbidden:

```text
ad hoc reconvergence stacks for C1
claiming divergent-branch support without official requirement and tests
using public branch labels or source shape to choose semantics
```

## Simulator role

The simulator is a local semantic checker.

It is not the official competition oracle and must not be used as a replacement for external evaluation models.

## Regression requirement

Architecture changes must preserve:

- PTX-01 correctness
- PTX-02 control-flow correctness
- official public T1-T5 compile smoke unless the PR explicitly changes the package harness with evidence
- O0 compatibility with the established lowering path unless intentionally changed with evidence

## Review requirement

New optimization functionality should first introduce:

1. IR representation if required
2. pass abstraction
3. analysis dependency
4. regression tests

Only then should the optimization implementation be added.
