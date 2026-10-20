# TASK-4537: Repo `.parrot/test_runners.toml` and the UI vitest suite in the nightly matrix

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4526
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11. This repository's runner config and the nightly safety net for the admin UI. `.parrot/`
is git-ignored (`.gitignore:411`) — the TOML must be added with `git add -f` so it is tracked. The workflow file
must be pushed over SSH (memory "push workflow files needs SSH").

---

## Scope

- Create `.parrot/test_runners.toml` exactly as spec §2 (pytest 60, vitest cwd `packages/ai-parrot-server/ui` 120, cargo 300, parrot-e2e tiers merge/feature).
- Add an `admin-ui` entry to `nightly-tests.yml`'s matrix: pnpm setup, `pnpm install --frozen-lockfile`, `pnpm exec vitest run --reporter=junit --outputFile=junit/admin-ui.xml` in the UI dir; upload as the other suites.
- Create `tests/sdd_scripts/test_repo_runner_config.py` asserting `load_registry(repo_root)` loads it and the vitest `cwd` has a `package.json`.

**NOT in scope**: Changing other matrix entries.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.parrot/test_runners.toml` | CREATE | repo runner config (git add -f) |
| `.github/workflows/nightly-tests.yml` | MODIFY | admin-ui matrix entry |
| `tests/sdd_scripts/test_repo_runner_config.py` | CREATE | config loads |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
# test: load the kernel by path like tests/sdd_scripts/test_select_tests.py does, then
from test_scope.runners.registry import load_registry  # TASK-4521
```

### Existing Signatures to Use
```python
# .gitignore:411  `.parrot/`  (ignored — use git add -f)
# .github/workflows/nightly-tests.yml:19-52  strategy.matrix.suite list + include (suite: ai-parrot …); steps "Run suite" :72, "Upload junit" :85 (path junit/${{ matrix.suite }}.xml)
# packages/ai-parrot-server/ui/package.json:14  (test script: vitest run)
```

### Does NOT Exist
- ~~a pnpm step in nightly-tests.yml~~ — add it in this entry only

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".parrot/test_runners.toml",
      "action": "CREATE"
    },
    {
      "path": ".github/workflows/nightly-tests.yml",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_repo_runner_config.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Read the whole workflow first; follow its matrix/include shape. Use `pnpm/action-setup` pinned to the version other workflows in `.github/workflows/` already use (grep) — do not invent a version.

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. TOML — *why*: repo defaults.
2. Workflow entry — *why*: nightly net.
3. Test.

### `.parrot/test_runners.toml` (CREATE)
```toml
# FEAT-709 — runner adapters for the SDD test-scope kernel. The ONLY extension point (vendored kernels read it too).
# Timeouts are placeholders until measured (spec §8 Q4; evidence in artifacts/logs/).

[runners.pytest]
timeout_s = 60

[runners.vitest]
cwd = "packages/ai-parrot-server/ui"
timeout_s = 120

[runners.cargo]
timeout_s = 300

[runners.parrot-e2e]
tiers = ["merge", "feature"]
timeout_s = 900

[extensions]
# kind = "dotted.module:AdapterClass"
```
**Why**: Values fixed by spec §2.

### FILL IN checklist
- [ ] workflow entry
- [ ] test

---

## Acceptance Criteria

- [ ] `git ls-files .parrot/test_runners.toml` lists the file.
- [ ] Registry loads it.
- [ ] Workflow YAML parses (`python -c 'import yaml…'`) and has the admin-ui entry.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest tests/sdd_scripts/test_repo_runner_config.py -q`

---

## Test Specification

Tests live in the files declared above; write the cases named in Acceptance Criteria. sdd_coder tests reuse the hermetic-root fixture in `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug language-agnostic-validation-runners --feature-id FEAT-709`), never on `dev`.
2. Every `Depends-on` task must be `done` in `sdd/tasks/index/language-agnostic-validation-runners.json`.
3. Verify the Codebase Contract first; fix stale entries in this file before coding.
4. Implement from the blueprint; complete every `FILL IN`; never change a fixed signature or path.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Stage only the files listed above (`git add -f` for `.claude/`, `.parrot/`, `artifacts/`).
7. Close with `scripts/sdd/close_task.sh TASK-4537 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
