# Change Review

## Scope

Milestone:

Primary goal:

Branch:

Base commit:

## Changed modules

List each module and its responsibility:

- TBD

For a new or materially changed module, describe:

- Inputs/outputs and error behavior:
- Analyses consumed/preserved/invalidated:
- Semantic invariants:
- Conservative fallback/unsupported cases:

## Design and proof

Explain why the transformation or lowering is correct. For control flow, state the uniformity/divergence argument. For optimization, state the legality and preserved semantics. For backend changes, state register/dependency/memory-order constraints.

## Generalization

- [ ] No case ID, input file name, hash, fixed label, fixed PTX register number or fixed instruction position is used as a semantic trigger.
- [ ] Register/label renaming behavior was considered.
- [ ] Parameter, loop-count, block-order or shape variation was considered as applicable.

## Verification

### Passed

```text
commands and exact results
```

### Failed

```text
none, or commands and failures
```

### Not run

```text
unavailable tools, or deliberately out-of-scope checks
```

Required baseline:

- [ ] `python -m compileall -q src compiler disassembler tests`
- [ ] `python -m pytest -q tests`
- [ ] `git diff --check`
- [ ] Milestone-specific CLI/objdump checks
- [ ] Mutation/negative/differential tests as applicable

## Code-quality review

Complexity added:

Responsibility boundaries:

Technical debt introduced/removed:

## Artifacts and documentation

- [ ] No cache, temporary binary, log, or disposable artifact is tracked.
- [ ] `docs/STATUS.md` is updated when milestone state or debt changed.
- [ ] README claims match verified capabilities.

## Reviewer decision

- [ ] Correctness gate satisfied
- [ ] Generalization gate satisfied
- [ ] Architecture/module contract is acceptable
- [ ] Ready to merge
