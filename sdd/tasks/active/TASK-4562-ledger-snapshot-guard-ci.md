# TASK-4562: Wire the ledger snapshot guard into CI

**Feature**: FEAT-712 — Ledger snapshot removal guard
**Spec**: `sdd/specs/ledger-service-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4561
**Assigned-to**: unassigned
**Discovered-from**: `issue:1752eb466e1e`

---

## Context

TASK-4561 builds `scripts/sdd/check_ledger_snapshot.py`. A guard nobody runs
protects nothing: both documented snapshot losses (`ccbfef606`, `769ca8516`)
reached `dev` through ordinary PRs. This task puts the guard in front of them.

The `lint-and-registry` job already hosts the two sibling SDD backstops
(FEAT-387 collisions at `ci.yml:94-97`, stalled task files at `ci.yml:104-107`),
so it is the established home.

## Scope

Add one step to the `lint-and-registry` job in `.github/workflows/ci.yml` that
fetches the base branch and runs the guard against it.

**NOT in scope**: the guard script or its tests (TASK-4561); changing any other
CI job; adding a baseline-exception file (there are no pre-existing violations —
TASK-4561's AC8 proves today's snapshot is clean).

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `.github/workflows/ci.yml` | MODIFY | One step appended to `lint-and-registry` |
| `tests/sdd_scripts/test_check_ledger_snapshot.py` | MODIFY | Append `TestCiWiring` (module created by TASK-4561) |

## Codebase Contract (Anti-Hallucination)

### Existing Signatures (verified)

```yaml
# .github/workflows/ci.yml:10
  lint-and-registry:
# .github/workflows/ci.yml:14
      - uses: actions/checkout@v6      # depth-1 by default: NO `with: fetch-depth`
# .github/workflows/ci.yml:94-97 — the FEAT-387 sibling step, the pattern to copy
      - name: Check SDD TASK-ID collisions (FEAT-387)
        run: |
          uv run python -m scripts.sdd.check_id_collisions \
            --baseline scripts/sdd/.collision_baseline.json
```

The job already runs `uv sync --all-packages` (`ci.yml:27`), so `uv run` is
available at this point in the job.

### Does NOT Exist (verified absent)

- No `with: fetch-depth: 0` anywhere in `lint-and-registry` — the base ref is
  **not** present in the checkout and must be fetched explicitly.
- No existing CI step reads `sdd/ledger/issues.jsonl`.
- No `scripts/sdd/.ledger_baseline.json` — and none is needed.

### Edit Site (Blueprint Anchor)

| File | Anchor | Occurrences | Action |
|---|---|---|---|
| `.github/workflows/ci.yml` | `      - name: Check stalled SDD task files` | 1 (verified: `grep -c`, line 104) | insert the new step after that step's `run:` block |

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".github/workflows/ci.yml", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_check_ledger_snapshot.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

## Implementation Notes

- `github.base_ref` is set on `pull_request` events only; it is empty on a
  `push`. Fall back to `dev` so the step works on both (spec §8 open question 1
  resolved this way).
- Pushing `.github/workflows/*` requires the **SSH remote** — the `gh` token
  lacks the `workflow` scope. The worktree remote is already
  `git@github.com:...`, so a plain `git push` works; do not switch it to HTTPS.

## Implementation Blueprint

### `.github/workflows/ci.yml` — MODIFY

```yaml
# occurrences: 1 (verified: grep -c '      - name: Check stalled SDD task files' .github/workflows/ci.yml)
# AFTER — insert below the `--baseline scripts/sdd/.task_state_baseline.json`
# line that closes the step beginning at `      - name: Check stalled SDD task files`
# (verified: .github/workflows/ci.yml:104)

      # FEAT-712: sdd/ledger/issues.jsonl has silently lost open issues twice
      # (ccbfef606, 769ca8516 — 25 issues, 14 of them open, including a
      # vulnerability). export_snapshot reconciles since FEAT-671, so this is
      # the independent backstop: it fails the build when a row that is open or
      # claimed at the base ref disappears from the snapshot. A status
      # transition (open -> closed) is normal and passes. Intentional removals
      # carry a `Ledger-Removal: issue:<id>` trailer on the removing commit.
      # actions/checkout is depth-1 here, so the base branch is fetched first.
      - name: Check SDD ledger snapshot removals (FEAT-712)
        run: |
          BASE="${{ github.base_ref || 'dev' }}"
          git fetch --depth=50 origin "$BASE"
          uv run python -m scripts.sdd.check_ledger_snapshot \
            --base-ref "origin/$BASE"
```

**Why**: the step sits with its two sibling SDD backstops so all three fail in
one job and one log. `--depth=50` rather than `--depth=1` because
`allowed_removals` reads commit messages across `base..HEAD`, which needs more
than the tip commit; 50 comfortably covers a PR while staying far cheaper than
a full clone. The comment carries the incident evidence because the next reader
will ask why a whole CI step guards one JSONL file.

### Steps (in order)

1. Confirm the anchor still occurs exactly once
   (`grep -c '      - name: Check stalled SDD task files' .github/workflows/ci.yml`);
   a count of 0 means drift — stop and report rather than inventing a site.
2. Insert the block above after that step's `run:` body, keeping the blank line
   between steps and the six-space step indentation.
3. Validate the YAML parses and the new step is attached to `lint-and-registry`.
4. Push over SSH (see Implementation Notes).

### FILL IN checklist

- [ ] Anchor re-verified as 1 occurrence immediately before editing
- [ ] Step lands inside `lint-and-registry`, not a sibling job
- [ ] `BASE` falls back to `dev` when `github.base_ref` is empty (AC10)

## Acceptance Criteria

Implements spec AC10.

- [ ] AC10: the guard runs in `lint-and-registry` and works on a depth-1 checkout
- [ ] `.github/workflows/ci.yml` parses as valid YAML
- [ ] The new step is a member of the `lint-and-registry` job's `steps` list
- [ ] The step fetches the base branch before invoking the guard

## Validation Commands

- `pytest tests/sdd_scripts/test_check_ledger_snapshot.py -q`

## Test Specification

Append a `TestCiWiring` class to the module TASK-4561 created, so the wiring is covered by
the same pytest operand the feature's Validation Contract already names, rather than by an
unselectable shell one-liner:

```python
class TestCiWiring:
    """FEAT-712 AC10: the guard must actually run inside lint-and-registry."""

    def test_guard_step_is_registered_in_lint_and_registry(self) -> None:
        # FILL IN: yaml.safe_load('.github/workflows/ci.yml'), read
        # jobs['lint-and-registry']['steps'], assert a step named
        # 'Check SDD ledger snapshot removals (FEAT-712)' is present — bounded by AC10
        # (membership of THAT job, not mere presence somewhere in the file).

    def test_guard_step_fetches_the_base_ref_first(self) -> None:
        # FILL IN: assert that step's `run` body contains 'git fetch' BEFORE
        # 'check_ledger_snapshot' — bounded by the depth-1 checkout risk in spec §7.
```

`yaml` is already available to the test suite; do not add a dependency.

## Agent Instructions

Touch only `.github/workflows/ci.yml`, and only inside `lint-and-registry`. Do
not add `fetch-depth: 0` to the job's `actions/checkout` — that would slow every
run of a job that currently needs only the tip; the step fetches what it needs.

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
