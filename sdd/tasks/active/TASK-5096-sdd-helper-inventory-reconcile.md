# TASK-5096: Helper inventory reconciliation — package `check_spec_consequences`, un-ship `insight`

**Feature**: FEAT-633 — parrot-installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.8, amendment C26 — proposal rev 0.9)
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4088, TASK-4091, TASK-5095
**Assigned-to**: unassigned

---

## Context

C26's review of the branch found two inventory defects. (1) `check_spec_consequences` (FEAT-784 M9, dev
`scripts/sdd/check_spec_consequences.py`) is invoked by shipped markdown 10× as
`python -m scripts.sdd.check_spec_consequences` and is not packaged, so an installed `/sdd-spec` / `/sdd-task`
breaks outside the monorepo. (2) `insight.py` (110 KB) is packaged by TASK-4088 although C22 excludes
`/sdd-insight` from shipping and nothing shipped reaches it (Q-C26-1, default **drop**). This task makes the
packaged set equal to the mounted set so TASK-5095's gate stays exact.

---

## Scope

- Move `check_spec_consequences` into `packages/ai-parrot/src/parrot/sdd/scripts/` and leave the standard
  compatibility shim at `scripts/sdd/check_spec_consequences.py`; mount it as `parrot sdd spec consequences`.
- Un-ship `insight`: delete `packages/ai-parrot/src/parrot/sdd/scripts/insight.py`, restore the real module at
  `scripts/sdd/insight.py` from `origin/dev`, and empty `_UNMOUNTED` in `cli.py`.
- Update `_MOVED` in `test_no_repo_script_refs.py` (add `check_spec_consequences`, remove `insight`).

**NOT in scope**: rewriting the 10 markdown references (TASK-5098 does it from the table); any other helper
move; `check_ledger_snapshot` / `price_coverage` (they stay in `scripts/sdd/`, C26).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/check_spec_consequences.py` | CREATE | moved from `scripts/sdd/` (dev) |
| `scripts/sdd/check_spec_consequences.py` | MODIFY | becomes the compatibility shim |
| `packages/ai-parrot/src/parrot/sdd/scripts/insight.py` | MODIFY | deleted (`git rm`) |
| `scripts/sdd/insight.py` | MODIFY | real module restored from `origin/dev` (replaces the shim) |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `spec consequences` verb; `_UNMOUNTED = frozenset()` |
| `packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py` | MODIFY | `_MOVED` adjusted |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `feat-FEAT-633-parrot-installer` @ `54868dcb2d` and `origin/dev` @ `6a334a377c` (2026-11-01).

### Verified Imports
```python
# scripts/sdd/check_spec_consequences.py (dev) — these all resolve inside the wheel, so the module can move as-is:
from parrot.knowledge.wiki.decisions.consequences_render import check_spec, render_spec   # :17
from parrot.knowledge.wiki.decisions.models import AUDIT_NOT_CONFIGURED                   # :18
from parrot.knowledge.wiki.decisions.render import DEFAULT_BUDGET_TOKENS                  # :19
from parrot.knowledge.wiki.decisions.spec_audit import is_configured, open_consequence_service   # :20
from parrot.knowledge.wiki.decisions.spec_entries import DECISIONS_HEADING, extract_block # :21
import scripts.sdd.check_spec_consequences as gate            # tests/sdd_scripts/test_check_spec_consequences.py:10 (keeps working through the shim)
from parrot.sdd.scripts import ensure_worktree as _impl       # scripts/sdd/ensure_worktree.py:4 — the shim pattern to copy
```

### Existing Signatures to Use
```python
# scripts/sdd/check_spec_consequences.py (dev)
def main(argv: list[str] | None = None) -> int:               # :77 — exit matrix 0 pass|skipped · 1 conflict · 2 invalid · 3 incomplete
# scripts/sdd/ensure_worktree.py — the whole shim (7 lines):
"""Compatibility shim — moved to ``parrot.sdd.scripts.ensure_worktree`` (FEAT-633)."""
import sys
from parrot.sdd.scripts import ensure_worktree as _impl
if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
# packages/ai-parrot/src/parrot/sdd/cli.py (after TASK-5095): VERBS["spec"] dict; _UNMOUNTED = frozenset({"insight"})
# packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py:26-36 — _MOVED tuple ("insight" at :29)
# scripts/sdd/insight.py on origin/dev — the real module ("SDD Insight — AI-Parrot internal AI-fluency + SDD-process analyzer.");
#   on the branch it is a shim with a sys.path retry (scripts/sdd/insight.py:1-12).
# .claude/commands/sdd-insight.md:51,85 and .agents/skills/sdd-insight/SKILL.md:22,46 run `python3 scripts/sdd/insight.py` — unchanged.
```

### Does NOT Exist
- ~~`parrot.sdd.scripts.check_spec_consequences`~~ — created by this task.
- ~~`parrot sdd spec consequences`~~ — mounted by this task (TASK-5095 does not add it).
- ~~an importer of `parrot.sdd.scripts.insight` outside the shim~~ — verify with `grep -rn "sdd.scripts.insight\|sdd.scripts import insight"`; if a test imports it, point it at `scripts.sdd.insight`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/check_spec_consequences.py", "action": "CREATE"},
    {"path": "scripts/sdd/check_spec_consequences.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/insight.py", "action": "MODIFY"},
    {"path": "scripts/sdd/insight.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/check_spec_consequences.py#main",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#VERBS"
  ]
}
```

---

## Implementation Notes

- Use `git mv` for the move so history follows, then write the shim. `git show origin/dev:scripts/sdd/insight.py >
  scripts/sdd/insight.py` restores the real module byte-for-byte; `git rm` the packaged copy.
- `check_spec_consequences` has an `asyncio` entry and imports `parrot.knowledge.wiki.decisions.*` — all core
  modules, so no `ai-parrot-tools` dependency is introduced (C20 stays true).
- The 10 shipped references keep saying `python -m scripts.sdd.check_spec_consequences` until TASK-5098 rewrites
  them; `test_no_repo_script_refs` will flag them once `check_spec_consequences` is in `_MOVED` — that is the
  expected red that TASK-5098 turns green. State it in the Completion Note.

---

## Implementation Blueprint

### Steps (in order)
1. `git mv scripts/sdd/check_spec_consequences.py packages/ai-parrot/src/parrot/sdd/scripts/check_spec_consequences.py` — *why*: history follows the move.
2. Write the shim at `scripts/sdd/check_spec_consequences.py` — *why*: `tests/sdd_scripts/test_check_spec_consequences.py` and monorepo hand use keep working.
3. Mount `spec consequences`; empty `_UNMOUNTED` — *why*: C26 table row; Q-C26-1.
4. `git rm` the packaged `insight.py`; restore `scripts/sdd/insight.py` from `origin/dev` — *why*: C22, nothing shipped reaches it.
5. Adjust `_MOVED` — *why*: it is the list the no-repo-refs gate checks.

### `scripts/sdd/check_spec_consequences.py` (MODIFY — whole file)
```python
"""Compatibility shim — moved to ``parrot.sdd.scripts.check_spec_consequences`` (FEAT-633, C26)."""
import sys

from parrot.sdd.scripts import check_spec_consequences as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```
**Why**: identical to every other FEAT-633 shim (`scripts/sdd/ensure_worktree.py`).

### `packages/ai-parrot/src/parrot/sdd/cli.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-5095: grep -c '"prune-intake": ("prune_intake"' packages/ai-parrot/src/parrot/sdd/cli.py)
# AFTER — insert below `"prune-intake": ("prune_intake", (), "Prune stale /sdd-spec intake staging."),`
        "consequences": ("check_spec_consequences", (), "Decision-audit gate for a spec (FEAT-784)."),
# occurrences: 1 — REPLACE `_UNMOUNTED: frozenset[str] = frozenset({"insight"})` with
_UNMOUNTED: frozenset[str] = frozenset()
```
**Why**: the mount-completeness gate must now see 27 packaged modules with `main()` and 27 mounted.

### `packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"doc_taxonomy", "backfill_taxonomy", "migrate_index", "select_tests", "insight", "install_hooks",' …)
# REPLACE that line (:29) with
    "doc_taxonomy", "backfill_taxonomy", "migrate_index", "select_tests", "install_hooks",
# and append to the tuple, before the closing paren (:36):
    "check_spec_consequences",  # C26 / TASK-5096 — FEAT-784 gate, 10 shipped refs
```
**Why**: `_MOVED` is what the gate rewrites expectations from; `insight` is monorepo-only again.

### FILL IN checklist
- [ ] any test importing `parrot.sdd.scripts.insight` → `scripts.sdd.insight`; bounded by AC-3.
- [ ] `tests/sdd_scripts/test_check_spec_consequences.py` passes through the shim unchanged; bounded by AC-1.

---

## Acceptance Criteria
- [ ] AC-1 `parrot sdd spec consequences --help` exits 0; `tests/sdd_scripts/test_check_spec_consequences.py` passes unchanged.
- [ ] AC-2 `test_sdd_cli_mounts_every_helper` passes with `_UNMOUNTED` empty (27 mounted of 29 packaged modules).
- [ ] AC-3 `packages/ai-parrot/src/parrot/sdd/scripts/insight.py` is gone; `python3 scripts/sdd/insight.py --help` works from the restored module; `/sdd-insight` text untouched.
- [ ] AC-4 `test_no_repo_script_refs` reports only the 10 `check_spec_consequences` references (to be rewritten by TASK-5098) — listed in the Completion Note.

---

## Validation Commands
- `pytest tests/sdd_scripts/test_check_spec_consequences.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py -q`

---

## Test Specification
```python
# No new test file: test_sdd_cli_mounts_every_helper (TASK-5095) proves the mount; the shim is covered by
# tests/sdd_scripts/test_check_spec_consequences.py through `import scripts.sdd.check_spec_consequences`.
```

---

## Agent Instructions
- Work inside `.claude/worktrees/feat-FEAT-633-parrot-installer`; run tests with `PYTHONPATH=packages/ai-parrot/src`.
- Do not touch markdown or `_assets`. Commit: `feat(parrot-installer): TASK-5096 — package check_spec_consequences, un-ship insight`.

---

## Completion Note
_(filled by the implementer)_
