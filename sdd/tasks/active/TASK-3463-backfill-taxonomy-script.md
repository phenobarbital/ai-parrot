# TASK-3463: `backfill_taxonomy` — infer `projects` for existing SDD docs (dry-run default)

**Feature**: FEAT-576 — SDD Document Taxonomy (`projects` and `tags` frontmatter)
**Spec**: `sdd/specs/sdd-spec-changes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3459
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 8** (goal G9, AC11). Several hundred existing specs/proposals lack
`projects`. This script proposes values from the code paths each doc mentions; it is a
**dry run by default** and only writes with `--apply`. Running it for real is an operator
action outside this feature (spec Non-Goals). Tags are never inferred.

---

## Scope

- Create `scripts/sdd/backfill_taxonomy.py` with `infer_projects()`, `plan_edit()`, `main()`
  as fixed by the spec §3 M8 skeleton.
- Write `tests/sdd_scripts/test_backfill_taxonomy.py`.

**NOT in scope**: running `--apply` on the repo; committing anything; inferring tags.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/backfill_taxonomy.py` | CREATE | inference + text-insertion editor |
| `tests/sdd_scripts/test_backfill_taxonomy.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from scripts.sdd.sdd_meta import KNOWN_PROJECTS, parse_taxonomy  # created by TASK-3459
```

### Existing Signatures to Use
```python
# scripts/sdd/check_task_graph.py:445 — CLI entry pattern
def main(argv: list[str] | None = None) -> int:
```
Frontmatter rule (same as `parse()`, sdd_meta.py:76-85): a block exists only if the file
starts with `---` at byte 0 and a second `---` follows. Real docs put comment lines inside the
block (e.g. `sdd/templates/spec.md:2-4`) — they MUST survive an `--apply`.

Path → project mapping (spec §3 M8):
| Mention in doc text | Project |
|---|---|
| `packages/<dist>/` where `<dist>` ∈ KNOWN_PROJECTS | `<dist>` |
| `packages/ai-parrot-server/ui/` | `admin-ui` (in addition to `ai-parrot-server`) |
| `parrot_tools` / `parrot_loaders` / `parrot_pipelines` | `ai-parrot-tools` / `ai-parrot-loaders` / `ai-parrot-pipelines` |
| `scripts/sdd/`, `.claude/commands/`, `sdd/templates/` | `sdd-tooling` |
| `flows/dev_loop` | `dev-loop` |
| bare `parrot/<x>` (not preceded by `src/` of a `packages/` path) | `ai-parrot` |

### Does NOT Exist
- ~~`scripts/sdd/backfill_taxonomy.py`~~ — created by this task
- ~~a YAML round-trip library (`ruamel.yaml`) in the deps~~ — do NOT add one; edit as text

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/backfill_taxonomy.py", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_backfill_taxonomy.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/check_task_graph.py#main"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Never re-dump YAML** — insert text lines before the closing `---` (spec §7 risk).
- Never overwrite a non-empty `projects:`; if `projects: []` exists, replace just that line.
- Add `tags: []` only if no `tags:` key exists.
- Doc with no frontmatter → prepend `---\ntype: feature\nbase_branch: dev\nprojects: [...]\ntags: []\n---\n`
  (equals `parse()` defaults, so flow resolution is unchanged).
- Output list in flow style: `projects: [a, b]`.
- `--apply` writes files but NEVER runs git.

---

## Implementation Blueprint

### Steps (in order)
1. Implement `infer_projects` from the mapping table with compiled regexes — *why*: pure function, easy to test.
2. Implement `plan_edit` returning new text or `None` — *why*: dry-run and apply share it; tests can diff.
3. Implement `main` (dry-run prints `<path>: projects = [...]`; `--apply` writes) — *why*: AC11.

### `scripts/sdd/backfill_taxonomy.py` (CREATE)
```python
"""Infer ``projects`` frontmatter for existing SDD docs (FEAT-576). Dry-run by default.

Usage::

    python -m scripts.sdd.backfill_taxonomy [--root .] [--kind spec|brainstorm|proposal|all]
        [--limit N] [--apply]
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from scripts.sdd.sdd_meta import KNOWN_PROJECTS, parse_taxonomy

logger = logging.getLogger(__name__)

_GLOBS: dict[str, str] = {
    "spec": "sdd/specs/*.spec.md",
    "brainstorm": "sdd/proposals/*.brainstorm.md",
    "proposal": "sdd/proposals/*.proposal.md",
}


def infer_projects(text: str) -> list[str]:
    """Map code paths mentioned in ``text`` to canonical projects, ordered by first mention.

    Only values in ``KNOWN_PROJECTS`` are returned.
    """
    # FILL IN: regex scan per the mapping table; record (first_offset, project); sort by offset; dedupe — bounded by test_infer_projects
    raise NotImplementedError


def plan_edit(doc_path: Path) -> str | None:
    """Return the new file text, or ``None`` when no change is needed.

    ``None`` when ``projects`` is already non-empty or nothing was inferred. Inserts lines as
    text before the closing ``---``; never rewrites any other byte.
    """
    # FILL IN: parse_taxonomy (skip on ValidationError -> logger.warning, None); locate block by the
    #   same byte-0 '---' rule as parse(); replace `projects: []` line or insert; add `tags: []` if absent — bounded by AC11
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns 0. Writes only with ``--apply``; never commits."""
    parser = argparse.ArgumentParser(prog="python -m scripts.sdd.backfill_taxonomy", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--kind", choices=["spec", "brainstorm", "proposal", "all"], default="all")
    parser.add_argument("--limit", type=int, default=0, help="stop after N proposed edits (0 = no limit)")
    parser.add_argument("--apply", action="store_true", help="write the edits (default: dry run)")
    args = parser.parse_args(argv)
    # FILL IN: iterate globs sorted; for each plan_edit != None print "<rel>: projects = [..]" and write if --apply;
    #   final line "N docs would change" / "N docs changed" — bounded by AC11
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
```

### FILL IN checklist
- [ ] `infer_projects` — mapping table, first-mention order
- [ ] `plan_edit` — text insertion, never-overwrite, no-frontmatter prepend
- [ ] `main` — dry-run vs apply, `--limit`

---

## Acceptance Criteria

- [ ] Dry run by default; files change only with `--apply` (AC11)
- [ ] Non-empty `projects` never overwritten; every other byte preserved, comments kept (AC11)
- [ ] Never invokes git
- [ ] `ruff check scripts/sdd/backfill_taxonomy.py` clean

---

## Validation Commands
- `pytest tests/sdd_scripts/test_backfill_taxonomy.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_backfill_taxonomy.py
"""Tests for scripts.sdd.backfill_taxonomy (FEAT-576)."""
from __future__ import annotations

from pathlib import Path

from scripts.sdd.backfill_taxonomy import infer_projects, main, plan_edit

FRONT = "---\n# a comment that must survive\ntype: feature\nbase_branch: dev\n---\n"


def test_infer_projects() -> None:
    text = (
        "see packages/parrot-formdesigner/src/x.py and parrot_tools.jira, "
        "scripts/sdd/reserve_ids.py, packages/ai-parrot-server/ui/src/App.svelte, parrot/bots/abstract.py"
    )
    assert infer_projects(text) == [
        "parrot-formdesigner", "ai-parrot-tools", "sdd-tooling", "ai-parrot-server", "admin-ui", "ai-parrot",
    ]


def test_plan_edit_preserves_bytes(tmp_path: Path) -> None:
    p = tmp_path / "a.spec.md"
    body = "# A\nuses packages/ai-parrot-server/src/parrot/handlers/x.py\n"
    p.write_text(FRONT + body, encoding="utf-8")
    new = plan_edit(p)
    assert new is not None
    assert new.startswith("---\n# a comment that must survive\ntype: feature\nbase_branch: dev\n")
    assert "projects: [ai-parrot-server]\n" in new and "tags: []\n" in new
    assert new.endswith("---\n" + body)


def test_plan_edit_never_overwrites(tmp_path: Path) -> None:
    p = tmp_path / "b.spec.md"
    p.write_text("---\ntype: feature\nbase_branch: dev\nprojects: [docs]\n---\npackages/ai-parrot/x\n", encoding="utf-8")
    assert plan_edit(p) is None


def test_backfill_dry_run_writes_nothing(tmp_path: Path) -> None:
    spec = tmp_path / "sdd" / "specs" / "c.spec.md"
    spec.parent.mkdir(parents=True)
    original = FRONT + "packages/ai-parrot-tools/src/parrot_tools/x.py\n"
    spec.write_text(original, encoding="utf-8")
    assert main(["--root", str(tmp_path)]) == 0
    assert spec.read_text(encoding="utf-8") == original
    assert main(["--root", str(tmp_path), "--apply"]) == 0
    assert "projects: [ai-parrot-tools]" in spec.read_text(encoding="utf-8")
```

---

## Agent Instructions

1. Read spec §3 Module 8 and §7 Known Risks. Confirm TASK-3459 is done.
2. Implement, run Validation Commands, fill in the Completion Note (include a dry-run count over
   the real repo: `python -m scripts.sdd.backfill_taxonomy | tail -1`).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
