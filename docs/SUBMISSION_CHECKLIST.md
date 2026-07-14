# C1 Submission Checklist

Checklist for producing a valid C1 compiler submission under the reduced official C1 scoring package.

## Required submission contents

| Path | Required | Notes |
|---|---|---|
| `compiler/aec-cc` | **Yes** | Executable entry point (shebang `#!/usr/bin/env python3`, `chmod +x`) |
| `src/` | **Yes** | All compiler source (`aec_c1` package) |
| `README.md` | **Yes** | Project overview, build/run instructions |
| `LICENSE` | Yes | License file (MIT) |
| `spec.md` | No | Official spec (reference) |
| `scoring.md` | No | Official scoring (reference) |
| `hint.md` | No | Official hint targets (reference) |

## Explicitly excluded from submission

These files and directories must NOT appear in the submission archive:

| Pattern | Reason |
|---|---|
| `__pycache__/`, `*.pyc` | Python bytecode cache |
| `.pytest_cache/` | Test cache |
| `.git/`, `.github/` | Version control |
| `*.aecbin` | Generated binaries |
| `*_dump*.bin` | CModel memory dumps |
| `compile_report.json` | Generated reports |
| `.ssh/`, `*login*`, `*mig07*` | Credentials / host info |
| `__MACOSX/`, `.DS_Store`, `Thumbs.db` | OS metadata |
| `*.log`, `*.tmp`, `*.bak` | Temporary files |
| `*.tar.gz`, `*.zip` (except `*.sha256`) | Archives |
| `build/`, `dist/`, `*.egg-info/` | Build artifacts |
| `.vscode/`, `.idea/`, `*.iml` | IDE files |

## Submission creation

### Option A: Git archive (recommended)

```bash
git archive --format=tar.gz \
  --output=c1-submission-20260714.tar.gz \
  HEAD:compiler HEAD:src HEAD:README.md HEAD:LICENSE
```

### Option B: Scripted packaging

```bash
python scripts/make_submission.py --output c1-submission-20260714.tar.gz
```

## Pre-submission verification

Run all of the following on a clean checkout on Linux x86-64 with Python 3.13.5:

```bash
# 1. Syntax check
python -m compileall -q src compiler

# 2. Fast test suite (expect 169+ passed)
python -m pytest -q tests

# 3. Slow manifest e2e tests (expect 5/5)
python -m pytest -q tests/test_manifest_execution.py -m slow -v

# 4. CLI smoke test
./compiler/aec-cc testcases/T1_basic_lowering/kernel.ptx \
  -O2 -o /tmp/t1.aecbin --report /tmp/t1.json

# 5. Verify output
test -f /tmp/t1.aecbin || echo "FAIL: no output"
test $(stat -c%s /tmp/t1.aecbin) -gt 0 || echo "FAIL: empty output"
test $(( $(stat -c%s /tmp/t1.aecbin) % 16 )) -eq 0 || echo "FAIL: not 16-byte multiple"
python -c "import json; r=json.load(open('/tmp/t1.json')); assert r['status']=='ok'; assert r['optimization']=='O2'"

# 6. CModel validation (Linux x86-64 only)
python -m pytest -q tests/test_cmodel.py -v
```

## Scoring command

The official evaluator runs:

```bash
compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json
```

- Optimization level is fixed at `-O2` (confirmed by organizer, 2026-07-14).
- Default ISA profile is `c1_default` (C1 spec §4–§5 opcodes/types only).
- Report must include `status`, `optimization`, `opt_level`, and diagnostic fields per `spec.md` §12.

## CModel compatibility

- `aec-cmodel/` provides `aec-precise-linux-x86_64` and `aec-precise-macos-arm64`.
- The CModel expects raw 128-bit AEC instruction streams (no headers).
- `shl.b32` must encode as `SHL.u32` (organizer erratum 2026-07-14).
- BRX requires uniform branch condition across active warp lanes.
- C1 does not require warp-internal divergent branch or reconvergence.

## Final checks

- [ ] No `__pycache__` directories in archive
- [ ] No generated `.aecbin` or `.json` files
- [ ] No hardcoded local paths (e.g. `C:\Users\HP\anaconda3`)
- [ ] No credentials, tokens, or private keys
- [ ] `compiler/aec-cc` has `+x` permission
- [ ] All PTX lowering uses the C1-default ISA profile
- [ ] `shl.b32` encodes as `SHL.u32`
- [ ] Report `passes.scheduler` is `post_lowering_list` (not `none`)
- [ ] Cycle model metrics are `null` (not fabricated)
- [ ] README states Linux x86-64 + Python 3.13.5 evaluation environment
