---
type: feature
base_branch: dev
projects: [scripts]
tags: [installer, security, ledger-fix]
---
# FEAT-873 — install-parrot fix group (fixgroup:87473741d81e)

**Status**: approved · **Source**: `/sdd-fix issue:2e35462be4bb` (ledger group of 5)

## 1. Problem
Five open ledger issues on `scripts/install/install-parrot.{sh,ps1}`:

| Issue | Kind | Defect |
|---|---|---|
| issue:6e31d9355edc | vulnerability | uv archive verified against a `.sha256` fetched from the same release (no tamper/MITM protection) |
| issue:2e35462be4bb | bug | PS `python -c 'import parrot.self_.uv' 2>$null` under `$ErrorActionPreference='Stop'` can throw NativeCommandError on PS 5.1 |
| issue:73295db52ee4 | bug | `install-parrot.sh --global --install-cli` silently drops `--install-cli` |
| issue:a786fec203e1 | tech_debt | ps1 `-Python` defaults to `python`; fails when only the `py` launcher exists |
| issue:3b2432011ac9 | tech_debt | `(FEAT-586)` breadcrumb in both public script headers |

## 2. Design
- **Pinned hashes**: both scripts carry the SHA-256 of every uv `$UV_VERSION` asset they can
  download (taken from astral-sh/uv release 0.11.28) and verify the archive against the pin; the
  `.sha256` file is no longer downloaded. An unknown target fails closed. `PARROT_UV_SHA256`
  overrides the expected hash (offline mirrors and the test fixtures) — local environment only.
- **PS probe**: run the import probe with `$ErrorActionPreference='Continue'` inside try/catch;
  any failure means legacy-compat mode.
- **`--global --install-cli`**: rejected up front with a clear message (the managed runtime
  installs no host CLIs), like the other `--global` incompatibilities.
- **`-Python` default**: when `-Python` is not passed and `python` is not on PATH, fall back to
  `py -3` (the Python Launcher).
- **Breadcrumb**: drop `(FEAT-586)` from both headers.
- `scripts/install/SHA256SUMS` regenerated.

## 3. Acceptance Criteria
- [ ] No `.sha256` download remains; the pinned table covers every asset either script selects.
- [ ] Tampered archive (hash ≠ pin) aborts; existing installer tests pass with `PARROT_UV_SHA256`.
- [ ] `--global --install-cli` exits 1 with a message.
- [ ] ps1 probe cannot abort the install; `py` fallback present; no `FEAT-586` in either script.
- [ ] `SHA256SUMS` matches both scripts.
