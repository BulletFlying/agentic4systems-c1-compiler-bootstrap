# C1 Development, Branch and Module-Change Policy

This policy applies to all future C1 code, test, documentation and infrastructure changes in `BulletFlying/agentic4systems-c1-compiler-bootstrap`.

## 1. Repository boundary

- The only writable project repository is `BulletFlying/agentic4systems-c1-compiler-bootstrap`.
- `origin` must point to `BulletFlying/agentic4systems-c1-compiler-bootstrap`.
- `ephonic/Agentic4SystemSummerSchoolContest` must not be configured as a local Git remote.
- No feature branch, commit, tag, release, PR or issue may be created in the official repository without explicit one-time user authorization.
- Every completion report records the project repository `main` SHA and confirms no official remote is configured.

## 2. Main-branch rule

`main` is the accepted baseline, not a development workspace.

Future code and infrastructure changes must use a branch and pull request. Direct commits to `main` are reserved for an explicitly authorized emergency documentation correction. Until GitHub branch-protection settings are configured, this rule is enforced by repository policy, PR templates and review discipline.

Do not force-push `main`. Do not rewrite published milestone history.

## 3. Branch naming

Use one of the following forms:

```text
milestone/m<N>-<short-goal>
feat/c1-<short-goal>
fix/c1-<short-goal>
refactor/c1-<short-goal>
test/c1-<short-goal>
infra/c1-<short-goal>
docs/c1-<short-goal>
audit/<short-goal>
```

Examples:

```text
milestone/m2-scalar-passes
refactor/c1-pass-manager
fix/c1-varying-branch-fallback
test/c1-uniformity-mutations
infra/c1-governance-baseline-v2
```

A branch must start from the latest accepted `main` unless the PR explicitly documents a stacked dependency. One branch should have one primary goal.

## 4. Required branch start record

Before editing, record in the work log or PR:

```bash
git status --short
git status --branch --short
git rev-parse HEAD
git remote -v
git branch -vv
git ls-remote origin refs/heads/main
```

The tree must be clean. The writable destination must resolve to the BulletFlying repository. The official repository must not appear in `git remote -v`.

## 5. New-module change contract

Any branch that creates or materially changes a compiler module must declare:

1. Module responsibility and forbidden responsibilities.
2. Public inputs/outputs and error behavior.
3. Analyses consumed, preserved and invalidated.
4. Semantic invariants.
5. Unit, structural, executable, differential, mutation and negative tests that apply.
6. Migration plan from any legacy code path.
7. Known unsupported cases and conservative fallback.

Module-specific gates:

| Module class | Required gate |
|---|---|
| Parser / source model | malformed-input tests, source-line preservation, register/label rename tests |
| CFG / analysis | multi-block joins, unreachable blocks, reorder tests, fixed-point convergence, conservative unknown handling |
| Transform / pass | before/after executable differential, negative legality case, analysis invalidation declaration |
| Lowering / control legalization | structural target-code assertion, mixed-lane safety proof, boundary/partial-warp execution |
| Register allocation | interference/pair tests, pressure tests, spill correctness, no silent physical overlap |
| Scheduler | DDG dependency preservation, memory-order tests, deterministic output, cycle metric evidence |
| ISA / object format | official golden vectors, round-trip, malformed binary rejection, profile separation |
| Simulator | independent semantics, unsupported-op failure, OOB and non-uniform branch rejection |
| Agent | real report input, candidate loop, correctness rejection, fallback and final report |
| CI / packaging | clean checkout execution, supported Python versions, no generated artifacts committed |

## 6. Pull-request gate

Every non-emergency branch is merged through a PR to `main`. The PR must contain:

- Scope and milestone.
- Changed modules.
- Design/proof summary.
- Test commands and exact results.
- Explicit `Passed`, `Failed` and `Not run` sections.
- Code-quality and complexity review.
- Project repository SHA verification and confirmation that no official remote is configured.
- Known limitations and organizer questions.
- Confirmation that no case ID, file name, hash, fixed label or fixed register number is used as a semantic trigger.

Required checks before merge:

```bash
python -m compileall -q src compiler disassembler agent tests
python -m pytest -q tests
git diff --check
```

Add milestone-specific CLI, objdump, mutation, differential and artifact checks. When the `C1 compiler tests` workflow runs, it must be green before merge.

## 7. Review and merge rules

Review priority:

1. Correctness and illegal target behavior.
2. Generalization under hidden-test mutations.
3. Independent validation quality.
4. Architecture boundaries and complexity.
5. Performance.

Use normal merge, squash or rebase consistently within a PR; never force-push `main`. The final accepted commit must update `docs/STATUS.md` when milestone state, technical debt or organizer clarification changes.

## 8. Commit structure

Prefer separate commits for:

1. IR/analysis/refactor foundation.
2. Feature implementation.
3. Tests and executable validation.
4. Documentation/status/CI.

Commit prefixes:

```text
feat(c1):
fix(c1):
refactor(c1):
test(c1):
docs(c1):
ci(c1):
```

Avoid uninformative commit messages such as `fix`, `update`, `final` or `try again`.

## 9. Completion and cleanup

Before merge and after merge:

- Confirm no `__pycache__`, `.pytest_cache`, `.pyc`, temporary binaries, logs or disposable outputs are tracked.
- Confirm the feature branch contains only intended changes.
- Confirm the official repository is not configured as a Git remote and was not targeted by any write operation.
- Confirm project `main` points to the accepted result.
- Record CI state honestly; a workflow file existing is not equivalent to a successful run.

## 10. Branch lifecycle

- `audit/*` branches are read-only review snapshots and must not become implementation bases.
- `infra/*`, `docs/*`, `test/*`, `fix/*`, `refactor/*`, `feat/*` and `milestone/*` branches are short-lived.
- Delete merged short-lived branches through GitHub UI when convenient.
- Long-lived divergence branches are prohibited unless documented as an ISA/profile compatibility line.
