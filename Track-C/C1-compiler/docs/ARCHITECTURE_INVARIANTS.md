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

## Simulator role

The simulator is a local semantic checker.

It is not the official competition oracle and must not be used as a replacement for external evaluation models.

## Regression requirement

Architecture changes must preserve:

- PTX-01 correctness
- PTX-02 control-flow correctness
- O0 compatibility with the established lowering path unless intentionally changed with evidence

## Review requirement

New optimization functionality should first introduce:

1. IR representation if required
2. pass abstraction
3. analysis dependency
4. regression tests

Only then should the optimization implementation be added.
