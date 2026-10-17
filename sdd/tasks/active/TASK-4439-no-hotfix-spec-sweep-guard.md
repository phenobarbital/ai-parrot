# TASK-4439: Regression guard — no live `--type hotfix` references remain

**Feature**: FEAT-698 — /sdd-brief One-Command Brief Flow for Hotfixes and Single-Issue Fixes
**Spec**: `sdd/specs/sdd-brief-hotfix-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4433, TASK-4436
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 and §5 ("the M6 sweep grep comes back clean"). After the
hard cut, `/sdd-spec --type hotfix` must not be taught anywhere live. This
task turns the sweep into a permanent test, so a future edit cannot
reintroduce it, and records the sweep result.

---

## Scope

- Create `tests/sdd_scripts/test_no_type_hotfix_refs.py`: scan `.claude/`
  (excluding `.claude/worktrees/`), `.agents/`, `.agent/`, `scripts/`,
  `packages/*/src/parrot/flows/`, `docs/`, `sdd/templates/` for an
  **invocation** of the removed path — regex
  `[/$]sdd-spec\s+\S+.*--type hotfix` (a `/sdd-spec` or `$sdd-spec` call
  with an argument, followed by `--type hotfix` on the same line).
  **Why a regex, not the literal**: correct post-feature text legitimately
  contains `--type hotfix` — the `/sdd-spec` refusal ("if `--type hotfix`
  was passed…", TASK-4436), `/sdd-brief`'s "Replaces `/sdd-spec --type
  hotfix`" line (TASK-4429), and `ensure_worktree.py`'s `--jira-key` help
  ("Implies --type hotfix"). None of those is an invocation with an
  argument, so none matches. Skip binaries (`*.pyc`, `__pycache__`).
- Run the guard; if it fails, the failing files belong to a dependency task —
  report them in the Completion Note and mark `done-with-issues` (do not
  edit other tasks' files).

**NOT in scope**: historical `sdd/specs/`, `sdd/tasks/completed/`,
`sdd/state/`, `sdd/proposals/` (history is not rewritten); fixing hits.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_no_type_hotfix_refs.py` | CREATE | permanent sweep guard |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
- Pre-feature inventory (2026-10-17, `grep -rln -- "--type hotfix"` excluding worktrees):
  `.claude/commands/sdd-spec.md`, `.claude/agents/sdd-research.md`,
  `.agents/agents/sdd-research/agent.md`, `.agent/workflows/sdd-spec.md`,
  `.agent/agents/sdd-research/agent.md`, `scripts/sdd/ensure_worktree.py`
  (+ its `.pyc`), `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md`,
  `docs/sdd/CODEX.md`. All but `ensure_worktree.py` are cleaned by
  TASK-4433/4436.
- `tests/sdd_scripts/test_command_contracts.py` precedent: never inspect
  `.claude/worktrees/` (separate checkouts legitimately hold old text).

### Does NOT Exist
- ~~a repo-wide grep helper in tests/sdd_scripts~~ — use `Path.rglob` + `read_text(errors="ignore")`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "tests/sdd_scripts/test_no_type_hotfix_refs.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Sanity-check the regex against the known legitimate mentions (the TASK-4436 refusal line, TASK-4429's "Replaces" line, ensure_worktree.py's help text) — *why*: they must NOT match.
2. Write the guard — *why*: AC-1.
3. Run it and record the result — *why*: AC-2.

### `tests/sdd_scripts/test_no_type_hotfix_refs.py` (CREATE)
```python
"""No live doc or prompt teaches `/sdd-spec --type hotfix` after FEAT-698 — TASK-4439."""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_INVOCATION = re.compile(r"[/$]sdd-spec\s+\S+.*--type hotfix")
_SCAN = (".claude", ".agents", ".agent", "scripts", "docs", "sdd/templates")
_SKIP_PARTS = {"worktrees", "__pycache__"}


def _hits() -> list[str]:
    roots = [_ROOT / s for s in _SCAN] + sorted(_ROOT.glob("packages/*/src/parrot/flows"))
    found: list[str] = []
    # FILL IN: rglob each root; skip paths with a part in _SKIP_PARTS and non-text suffixes
    #          (.pyc, .so, images); read_text(errors="ignore"); for each line matching _INVOCATION
    #          collect "<repo-relative posix path>:<lineno>" — AC-1
    return found


def test_no_live_type_hotfix_references() -> None:
    hits = _hits()
    assert not hits, f"--type hotfix is still taught in: {hits} (FEAT-698 removed it; use /sdd-brief)"
```

### FILL IN checklist
- [ ] `_hits` traversal — AC-1
- [ ] Completion Note: the sweep result

---

## Acceptance Criteria

- [ ] AC-1: the guard passes on the feature branch with all dependencies done.
- [ ] AC-2: the Completion Note records the final sweep result (clean, or the offending files).
- [ ] AC-3: the guard never reads `.claude/worktrees/`.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_no_type_hotfix_refs.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-brief-hotfix-flow --feature-id FEAT-698`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/sdd-brief-hotfix-flow.json`
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** all acceptance criteria — run the Validation Commands from the worktree root
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4439 sdd-brief-hotfix-flow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
