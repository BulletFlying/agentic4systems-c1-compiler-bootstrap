# AGENTS.md — AEC Compiler Toolchain Development Rules

This file applies to the repository root and all subdirectories. Detailed goals, architecture, and milestones are in `docs/`. Current implementation state is in `docs/STATUS.md`.

## 1. Hard Boundaries

- No case-specific dispatch based on kernel name, filename, input hash, fixed label, fixed register number, or fixed instruction position.
- No relaxing of simulator/validator semantics to make tests pass.
- Lowerings/optimizations that cannot be proven legal must fall back conservatively or error explicitly — never guess.
- Unverified claims must not be marked as passed; local simulator results are not equivalent to external validation.

## 2. Source-of-Truth Order

1. Architecture invariants (`docs/ARCHITECTURE_INVARIANTS.md`)
2. ISA and ABI specifications
3. Public test suites
4. Repository documentation and compatibility policies
5. Historical context (informational only, not normative)

## 3. Before Starting Each Round

Record and confirm:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git remote -v
```

Confirm clean tree, then create a short-lived feature branch following `docs/DEVELOPMENT_POLICY.md` naming rules. Do not develop directly on `main` except for emergency documentation fixes.

## 4. Implementation Principles

- Parser → IR → CFG → Analysis → Transform → RegAlloc → Scheduler → ISA/Encoder → Simulator — keep layers separate.
- Analysis produces facts; transforms explicitly consume facts. Invalidate or recompute analysis after CFG changes.
- `UNKNOWN` uniformity is never `UNIFORM`. Only proven-uniform predicates may generate direct `BRX`.
- Kernel-level PTX `ret` lowers to `HALT`.
- Temporary registers must not wrap around; register exhaustion must error explicitly.
- 64-bit PTX pointer to AEC 32-bit memory-space offset conversion must be explicit address legalization.
- Every pass must have independent tests, negative tests, optimization-before/after executable differentials, and declared analysis invalidation.
- Compiler and simulator must not share core semantic implementation (no self-proving cycles).

## 5. Test and Acceptance

Every round at minimum:

```bash
python -m compileall -q src compiler disassembler tests
python -m pytest -q tests
git diff --check
git status --short
```

Acceptance criteria:
- Target tests and all prior regressions pass
- Generated code structure satisfies proof conditions, not just output matching
- No cache, temporary binary, log, or disposable artifact
- README/STATUS accurately describe implementation capabilities

## 6. Code Review Priority

1. Correctness defects: wrong binary encoding, OOB access, register overwrite
2. Generalization defects: failures under register/label rename, loop/shape variation
3. Self-proving cycles: compiler and simulator sharing core logic
4. Silent fallback, legacy bypasses, responsibility mixing, long functions, repeated logic
5. Performance improvement opportunities

Record technical debt in `docs/STATUS.md` with severity, impact, trigger conditions, and suggested fix target.

## 7. Final Report Format

```text
Summary
Changed files
Design / proof
Verification (Passed / Failed / Not run)
Code quality review
Git status and remote verification
Known limitations
Next single main task
```
