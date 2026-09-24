# TASK-3588: Wire the doc tests and script checks into CI

**Feature**: FEAT-586 — Public Install & Getting-Started Guide for AI-Parrot
**Spec**: `sdd/specs/parrot-install-guide.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3585, TASK-3586, TASK-3587
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5: a single-OS CI job that keeps the guide honest and
the scripts parseable. **Depends on TASK-3585/3586/3587** because the job invokes
their artifacts — the claim harness, `install-parrot.sh`, and `install-parrot.ps1`
— which must exist for the pipeline to pass. Single OS only (`ubuntu-latest`); no
matrix (spec AC13, resolved in brainstorm).

---

## Scope

- MODIFY `.github/workflows/ci.yml`: add a job (or steps in an existing job) that
  runs, on `ubuntu-latest`:
  - `pytest packages/ai-parrot/tests/docs/ -q` (the claim harness + script tests),
  - `bash -n scripts/install/install-parrot.sh`,
  - a `pwsh` parse of `scripts/install/install-parrot.ps1` (guarded: skip/soft when
    `pwsh` is unavailable),
  - one `bash scripts/install/install-parrot.sh --dry-run --provider anthropic`.
- Create `packages/ai-parrot/tests/docs/test_ci_install_wiring.py` with
  `test_ci_runs_doc_and_script_checks` — parses `ci.yml` and asserts it references
  the doc-test path, both scripts, and a `--dry-run` invocation.

**NOT in scope**: an OS matrix; executing `--system-deps`; the guide, harness, or
scripts themselves.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/ci.yml` | MODIFY | Add the single-OS doc-tests + script-checks + dry-run steps |
| `packages/ai-parrot/tests/docs/test_ci_install_wiring.py` | CREATE | Asserts ci.yml wires the checks |

---

## Codebase Contract (Anti-Hallucination)

### Verified facts
- `.github/workflows/ci.yml` exists: `name: CI — Monorepo`, triggers on push/PR to
  `main`/`dev`, jobs run `runs-on: ubuntu-latest`, uses `astral-sh/setup-uv` and
  `uv run` / `uv sync` (verified: ci.yml:1-30).
- The artifacts this job invokes:
  - `packages/ai-parrot/tests/docs/` (TASK-3585 + TASK-3586/3587 tests)
  - `scripts/install/install-parrot.sh` (TASK-3586)
  - `scripts/install/install-parrot.ps1` (TASK-3587)

### Does NOT Exist
- ~~a Windows/macOS runner in scope~~ — single-OS `ubuntu-latest` only (spec AC13).
- ~~a `--system-deps` step in CI~~ — never run in CI (spec §7 risk): only `--dry-run`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": ".github/workflows/ci.yml", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/docs/test_ci_install_wiring.py", "action": "CREATE" }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Reuse the file's existing conventions: `actions/checkout@v6`,
  `actions/setup-python@v6` (3.12), `astral-sh/setup-uv@v4`, `uv run`.
- The `pwsh` step must not fail the build when `pwsh` is absent — guard it or use
  a runner image that ships it; a soft/optional step is acceptable.
- CI runs `--dry-run` only — never a real install, never `--system-deps`.

### References in Codebase
- `.github/workflows/ci.yml` — the existing job to extend
- `.github/workflows/docs.yml` — another workflow for style reference

---

## Implementation Blueprint

### Steps (in order)
1. Add an `install-guide` job (or steps) to `ci.yml` mirroring the existing setup
   (checkout, setup-python 3.12, setup-uv) — *why*: consistency with the repo's CI.
2. Add the four checks (doc tests, `bash -n`, `pwsh` parse, `--dry-run`) — *why*:
   this is what keeps the guide and scripts true.
3. Write `test_ci_runs_doc_and_script_checks` asserting the wiring by string — *why*:
   the task must be verifiable without executing CI.

### `.github/workflows/ci.yml` (MODIFY)
```yaml
# occurrences: 1 (verified: grep -c '^jobs:' .github/workflows/ci.yml)
# AFTER — add a new job under `jobs:` (verified: .github/workflows/ci.yml:9)
  install-guide:
    name: Install guide & scripts
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with: { python-version: "3.12" }
      - uses: astral-sh/setup-uv@v4
        with: { version: "latest" }
      - name: Doc-claim & script tests
        run: uv run pytest packages/ai-parrot/tests/docs/ -q
      - name: POSIX installer syntax
        run: bash -n scripts/install/install-parrot.sh
      - name: PowerShell installer parse (soft)
        run: |
          # FILL IN: if `pwsh` is on the runner, ParseFile the .ps1 and fail on
          #          errors; otherwise echo a skip. Bounded by AC13 (single-OS).
          true
      - name: POSIX installer dry run
        run: bash scripts/install/install-parrot.sh --dry-run --provider anthropic
```
**Why this shape**: mirrors the existing `lint-and-registry` job's setup so it
reads as part of the same pipeline. The `pwsh` step is soft because `ubuntu-latest`
does not guarantee PowerShell and the feature is single-OS.

### `packages/ai-parrot/tests/docs/test_ci_install_wiring.py` (CREATE)
```python
"""Assert ci.yml wires the FEAT-586 checks (TASK-3588)."""
from __future__ import annotations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_runs_doc_and_script_checks() -> None:
    """ci.yml references the doc tests, both installer scripts, and a dry run."""
    text = CI.read_text(encoding="utf-8")
    assert "packages/ai-parrot/tests/docs/" in text
    assert "scripts/install/install-parrot.sh" in text
    assert "scripts/install/install-parrot.ps1" in text
    # FILL IN: also assert a '--dry-run' invocation is present — bounded by AC13.
    raise NotImplementedError
```
**Why this shape**: a pure text assertion needs no live CI run, so the task is
verifiable locally; the `--dry-run` assertion is the one `FILL IN`.

### FILL IN checklist
- [ ] `pwsh` soft-parse step in ci.yml; bounded by AC13
- [ ] `test_ci_runs_doc_and_script_checks` `--dry-run` assertion; bounded by AC13
- [ ] confirm the new job's indentation matches the existing `jobs:` block

---

## Acceptance Criteria
- [ ] ci.yml runs the doc tests, both script checks, and one dry run on a single OS (spec AC13)
- [ ] No OS matrix; `--system-deps` never executed in CI (spec §7 risk)
- [ ] `test_ci_runs_doc_and_script_checks` passes
- [ ] YAML is valid (job parses)

## Validation Commands
- `pytest packages/ai-parrot/tests/docs/test_ci_install_wiring.py::test_ci_runs_doc_and_script_checks -q`

---

## Test Specification
```python
def test_ci_runs_doc_and_script_checks(): ...
```

---

## Agent Instructions
1. Read the spec (§3 M5, AC13) and the existing `.github/workflows/ci.yml`.
2. Confirm the checkout/setup-uv action versions in the current file.
3. Index status → in-progress.
4. Implement from the blueprint; complete every `# FILL IN`.
5. Run the Validation Command.
6. Move to `sdd/tasks/completed/`, index → done, fill the note.

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-21
**Notes**: Added an `install-guide` job to `.github/workflows/ci.yml`
(checkout, setup-python 3.12, setup-uv, a NavConfig `env/dev/.env`
scaffold step matching sibling jobs since `parrot.bots.agent` — imported
by the hello-world test — needs it, doc-claim/script tests, `bash -n`
syntax check, a soft `pwsh`-presence-gated PowerShell parse, and one
`--dry-run` install), and
`packages/ai-parrot/tests/docs/test_ci_install_wiring.py`
(`test_ci_runs_doc_and_script_checks`, asserting `ci.yml` references the
doc-test path, both installer scripts, and a `--dry-run` invocation).
Verified: `.github/workflows/ci.yml` parses via `yaml.safe_load` (9 jobs,
including `install-guide`); `bash -n scripts/install/install-parrot.sh`
and a real `bash scripts/install/install-parrot.sh --dry-run --provider
anthropic` both ran clean. `pwsh` itself is not installed in this
environment, so the soft PowerShell-parse step could not be exercised
end-to-end here — it degrades to its `echo`-and-continue branch, verified
by inspection; the step is written to actually parse whenever `pwsh` is
present, e.g. on the CI runner. Full `packages/ai-parrot/tests/docs/`
suite: 14 passed, 1 skipped (the `pwsh`-gated one). `black --check` clean.
`ruff` is not installed in the shared `.venv` in this environment (dev
extra not synced) so `ruff check` could not be run — flagged for the
human/code review.
**Deviations from spec**: none.
