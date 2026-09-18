# TASK-3473: Intake staging retention — `prune_intake.py` + `/sdd-status` Step 0 + gitignore

**Feature**: FEAT-577 — `/sdd-spec` Intake Mode — Interview-Driven Spec Creation
**Spec**: `sdd/specs/sdd-feature-specification.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3469
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 9** (G13) and the `.gitignore` half of **Module 8**.
The user resolved in spec review that `sdd/state/.intake/` is git-ignored and
that staged runs older than 10 days are pruned during `/sdd-status`. This is
the one documented exception to `/sdd-status`'s read-only guardrail. It is
limited to untracked children of `sdd/state/.intake/`.

---

## Scope

- Create `scripts/sdd/prune_intake.py` with the Module 9 interface: dry-run by
  default, `--apply` deletes, strict root safety.
- Create `tests/sdd_scripts/test_prune_intake.py`.
- Add **Step 0 — Prune stale intake staging** to `.claude/commands/sdd-status.md`
  and to `.agent/workflows/sdd-status.md` (same body; that twin differs only by
  frontmatter), and amend their Guardrail line 18.
- Amend `.agents/skills/sdd-status/SKILL.md` (guardrail + workflow step).
- Add `sdd/state/.intake/` to `.gitignore`.

**NOT in scope**: pruning `sdd/state/.design_research/` (it stays manual), and
anything that writes intake runs (TASK-3470/3471).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/prune_intake.py` | CREATE | stale-run finder + pruner CLI |
| `tests/sdd_scripts/test_prune_intake.py` | CREATE | unit tests + sdd-status contract |
| `.claude/commands/sdd-status.md` | MODIFY | Step 0 + guardrail exception |
| `.agent/workflows/sdd-status.md` | MODIFY | identical body edit |
| `.agents/skills/sdd-status/SKILL.md` | MODIFY | guardrail exception + step |
| `.gitignore` | MODIFY | ignore `sdd/state/.intake/` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel  # verified: scripts/sdd/id_ledger.py:25 (scripts/sdd already uses pydantic)
# stdlib only otherwise: argparse, json, logging, shutil, datetime, pathlib
```

### Existing Signatures / Anchors
- CLI pattern: `scripts/sdd/check_task_graph.py:445` `def main(argv: list[str] | None = None) -> int:` and `:460` `if __name__ == "__main__":`; tests import `from scripts.sdd.check_task_graph import ...` (`tests/sdd_scripts/test_check_task_graph.py:6`).
- `.claude/commands/sdd-status.md` (104 lines): `:18` `- Read-only — do not modify any files.` (once); `:21` `## Steps`; `:23` `### 1. Read All Per-Spec Indexes (FEAT-145)` (once). `.agent/workflows/sdd-status.md` differs **only** at frontmatter line 2 (`description:` vs `model: haiku`).
- `.agents/skills/sdd-status/SKILL.md`: `:18` `- Read-only: never modifies any files.` (once); `:24` `1. Load all per-spec indexes:` (once).
- `.gitignore:406-407` — `# FEAT-545: id-independent staging for /sdd-spec §3b; …` / `sdd/state/.design_research/` (once).
- `intake.json.updated_at` — `"format": "date-time"` string (TASK-3469, `sdd/templates/intake.schema.json`).

### Does NOT Exist
- ~~`scripts/sdd/prune_intake.py`~~ — created here.
- ~~Any existing SDD script that deletes directories~~ — this is the first. Keep the safety checks strict.
- ~~A parity test for `sdd-status`~~ — none. Keep the two copies identical anyway.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/prune_intake.py", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_prune_intake.py", "action": "CREATE"},
    {"path": ".claude/commands/sdd-status.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-status.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-status/SKILL.md", "action": "MODIFY"},
    {"path": ".gitignore", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Safety first** (CLAUDE.md forbids `rm -rf`). Deletion is `shutil.rmtree` on
  a path that has been checked to be a direct, non-symlink child directory of a
  root whose resolved path ends with `sdd/state/.intake`. Anything else raises
  `ValueError` (CLI exit 2).
- Age source: `intake.json.updated_at` (ISO-8601; treat a naive timestamp as
  UTC). Fall back to the directory mtime when the file is missing, unreadable,
  or unparsable.
- The CLI is dry-run by default. `/sdd-status` passes `--apply`.
- Logging via `logging.getLogger(__name__)`. The CLI prints its report lines
  (matching the other `scripts/sdd` CLIs); the library functions never print.

---

## Implementation Blueprint

### Steps (in order)
1. Write `prune_intake.py`. *Why*: deterministic and testable, instead of a `find -delete` in a prompt.
2. Write the tests with a `tmp_path`-based fake root at `tmp_path/"sdd"/"state"/".intake"`. *Why*: exercises the suffix check without touching the repo.
3. Add Step 0 and the guardrail exception to `sdd-status` (both copies + skill). *Why*: G13.
4. Add the `.gitignore` line. *Why*: G5/G13, staging never gets committed.

### `scripts/sdd/prune_intake.py` (CREATE)
```python
"""``prune_intake.py`` — prune stale /sdd-spec intake staging (FEAT-577).

Staged intake runs live under ``sdd/state/.intake/<slug>-<RUN_ID>/`` (git-ignored).
``/sdd-status`` calls this with ``--apply`` to delete runs older than 10 days.
Dry-run by default; only direct, non-symlink child directories of a root that
resolves to ``.../sdd/state/.intake`` are ever deleted.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEFAULT_ROOT: Path = Path("sdd/state/.intake")
DEFAULT_MAX_AGE_DAYS: int = 10


class StaleIntake(BaseModel):
    """One staged run selected for pruning."""

    path: Path
    age_days: float
    age_source: str  # "updated_at" | "mtime"


def _check_root(root: Path) -> Path:
    """Return the resolved root, or raise ValueError when it is not an intake staging root."""
    resolved = root.resolve()
    if resolved.parts[-3:] != ("sdd", "state", ".intake"):
        raise ValueError(f"refusing to prune outside sdd/state/.intake: {root}")
    return resolved


def run_age(run_dir: Path, now: datetime) -> tuple[timedelta, str]:
    """Age from intake.json ``updated_at``; falls back to the dir mtime when missing/unparsable."""
    # FILL IN: read run_dir/"intake.json"; parse updated_at with datetime.fromisoformat (accept a trailing "Z";
    # naive ⇒ UTC); on OSError/ValueError/KeyError/json error fall back to
    # datetime.fromtimestamp(run_dir.stat().st_mtime, tz=timezone.utc) with source "mtime" — bounded by spec M9


def find_stale(root: Path, max_age_days: int = DEFAULT_MAX_AGE_DAYS, now: datetime | None = None) -> list[StaleIntake]:
    """Direct child dirs of ``root`` (no symlinks) older than ``max_age_days``. Missing root → []."""
    if not root.exists():
        return []
    resolved = _check_root(root)
    now = now or datetime.now(timezone.utc)
    # FILL IN: iterate sorted(resolved.iterdir()); skip non-dirs and symlinks (is_symlink() before is_dir());
    # compute run_age; keep age > timedelta(days=max_age_days) — bounded by spec M9 tests


def prune(
    root: Path, max_age_days: int = DEFAULT_MAX_AGE_DAYS, *, apply: bool = False, now: datetime | None = None
) -> list[StaleIntake]:
    """Return the stale runs; delete them only when ``apply``. Raises ValueError for an unsafe root."""
    stale = find_stale(root, max_age_days, now)
    if apply:
        for run in stale:
            # FILL IN: re-assert run.path.parent == _check_root(root) and not run.path.is_symlink() before
            # shutil.rmtree(run.path); logger.info each deletion — bounded by "Safety first"
            pass
    return stale


def main(argv: list[str] | None = None) -> int:
    """CLI: --root, --older-than-days (default 10), --apply. Prints one line per run; exit 0, or 2 on an unsafe root."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--older-than-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--apply", action="store_true", help="delete (default: dry-run)")
    args = parser.parse_args(argv)
    # FILL IN: call prune; on ValueError print the message and return 2; print "<pruned|would prune> <name>
    # (<age_days:.1f>d, <age_source>)" per run; return 0 — bounded by spec M9 CLI contract


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why this shape**: signatures are fixed by spec §3 Module 9. `_check_root` is
the private helper that makes the unsafe-root test and the per-deletion
re-check share one rule.

### `.claude/commands/sdd-status.md` (MODIFY) — and `.agent/workflows/sdd-status.md` identically
```markdown
# occurrences: 1 (verified: grep -cF -- '- Read-only — do not modify any files.' .claude/commands/sdd-status.md) — line 18
# REPLACE with:
- Read-only — do not modify any files, **except** Step 0's pruning of git-ignored `sdd/state/.intake/` staging (FEAT-577).

# occurrences: 1 (verified: grep -cF '### 1. Read All Per-Spec Indexes (FEAT-145)' .claude/commands/sdd-status.md) — line 23
# BEFORE — insert above it:
### 0. Prune Stale Intake Staging (FEAT-577)

```bash
python -m scripts.sdd.prune_intake --older-than-days 10 --apply
```

If it prunes anything, print one line before the board:
`🧹 Pruned N stale intake run(s) (>10 days): <names>`. Otherwise stay silent.
A non-zero exit is reported in one line, and the board is still shown.

```
**Why**: G13 (the user's resolution). The exception is written into the
guardrail itself so no reader mistakes it for a violation.

### `.agents/skills/sdd-status/SKILL.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -cF -- '- Read-only: never modifies any files.' .agents/skills/sdd-status/SKILL.md) — line 18
# REPLACE with:
- Read-only: never modifies any files, except pruning git-ignored `sdd/state/.intake/` runs older than 10 days (FEAT-577).
# occurrences: 1 (verified: grep -cF '1. Load all per-spec indexes:' .agents/skills/sdd-status/SKILL.md) — line 24
# BEFORE — insert above it (and renumber the following steps +1):
1. Prune stale intake staging: `python -m scripts.sdd.prune_intake --older-than-days 10 --apply`.
# FILL IN: renumber the existing numbered steps — bounded by keeping the list consistent
```

### `.gitignore` (MODIFY)
```gitignore
# occurrences: 1 (verified: grep -cxF 'sdd/state/.design_research/' .gitignore) — line 407
# AFTER — insert below it:
# FEAT-577: id-less /sdd-spec intake staging; promoted to sdd/state/<FEAT-ID>/intake/ on commit, pruned after 10 days by /sdd-status
sdd/state/.intake/
```

### `tests/sdd_scripts/test_prune_intake.py` (CREATE)
```python
"""Tests for scripts/sdd/prune_intake.py and the /sdd-status wiring (FEAT-577, spec §4 Module 9)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.sdd.prune_intake import find_stale, main, prune

_REPO_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "sdd" / "state" / ".intake"
    r.mkdir(parents=True)
    return r


def _run(root: Path, name: str, age_days: float | None) -> Path:
    """Create a staged run whose intake.json updated_at is ``age_days`` old (None ⇒ no intake.json)."""
    d = root / name
    d.mkdir()
    if age_days is not None:
        ts = (_NOW - timedelta(days=age_days)).isoformat()
        (d / "intake.json").write_text(json.dumps({"updated_at": ts}), encoding="utf-8")
    return d


# FILL IN: test_find_stale_uses_updated_at (11d stale, 9d not), test_find_stale_falls_back_to_mtime
# (no/corrupt intake.json + os.utime), test_prune_dry_run_deletes_nothing, test_prune_apply_deletes_only_stale_children
# (fresh run, root-level file, symlinked dir survive), test_prune_rejects_unsafe_root (ValueError; main(["--root", ...]) == 2),
# test_prune_missing_root_is_noop, test_sdd_status_prunes_intake_first (both sdd-status copies contain
# "scripts.sdd.prune_intake" and "FEAT-577"), test_gitignore_ignores_intake_staging — bounded by spec §4 M9 rows
```

### FILL IN checklist
- [ ] `run_age`, `find_stale` loop, `prune` re-check + rmtree, `main` body
- [ ] SKILL.md renumbering
- [ ] the eight tests

---

## Acceptance Criteria

- [ ] `prune_intake.py` is dry-run by default and deletes only stale, direct, non-symlink children of a `.../sdd/state/.intake` root
- [ ] An unsafe `--root` exits 2 and deletes nothing
- [ ] `/sdd-status` (both copies + skill) runs Step 0 with `--apply`, and its guardrail names the FEAT-577 exception
- [ ] `sdd/state/.intake/` is git-ignored
- [ ] `pytest tests/sdd_scripts/test_prune_intake.py -q` passes; `ruff check scripts/sdd/prune_intake.py` is clean

---

## Validation Commands

- `pytest tests/sdd_scripts/test_prune_intake.py -q`

---

## Test Specification

See the blueprint test module.

---

## Agent Instructions

1. Read spec §2 "Staging retention" and §3 Module 9.
2. Confirm TASK-3469 is done (the `updated_at` field is defined).
3. Implement; run the Validation Commands and `ruff check scripts/sdd/prune_intake.py`.
4. Move this file to `sdd/tasks/completed/` and set the index status to `done`.

---

## Completion Note

*(Agent fills this in when done)*
