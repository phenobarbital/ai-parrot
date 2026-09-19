# TASK-3473: Intake staging pruner — `prune_intake.py` with a once-a-day gate + gitignore

**Feature**: FEAT-577 — `/sdd-spec` Intake Mode — Interview-Driven Spec Creation
**Spec**: `sdd/specs/sdd-feature-specification.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3469
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 9** (G13, revision 0.3). `sdd/state/.intake/` is
git-ignored, and staged intake runs older than 10 days are pruned automatically
**by a git hook that runs at most once a day**. The hook itself is installed by
TASK-3476. This task provides the script the hook calls:
`python -m scripts.sdd.prune_intake --daily --apply`. **`/sdd-status` stays
read-only and is not touched.**

---

## Scope

- Create `scripts/sdd/prune_intake.py` with the Module 9 interface: dry-run by
  default, `--apply` deletes, strict root safety, and the `--daily` stamp gate.
- Create `tests/sdd_scripts/test_prune_intake.py`.
- Add `sdd/state/.intake/` to `.gitignore`.

**NOT in scope**: installing git hooks (TASK-3476); any change to
`/sdd-status` (it must stay read-only); pruning `sdd/state/.design_research/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/prune_intake.py` | CREATE | stale-run finder + pruner CLI with `--daily` gate |
| `tests/sdd_scripts/test_prune_intake.py` | CREATE | unit tests |
| `.gitignore` | MODIFY | ignore `sdd/state/.intake/` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel  # verified: scripts/sdd/id_ledger.py:25 (scripts/sdd already uses pydantic)
# stdlib only otherwise: argparse, json, logging, shutil, subprocess, datetime, pathlib
```

### Existing Signatures / Anchors
- CLI pattern: `scripts/sdd/check_task_graph.py:445` `def main(argv: list[str] | None = None) -> int:` and `:460` `if __name__ == "__main__":`; tests import `from scripts.sdd.check_task_graph import ...` (`tests/sdd_scripts/test_check_task_graph.py:6`).
- `.gitignore:406-407` — `# FEAT-545: id-independent staging for /sdd-spec §3b; …` / `sdd/state/.design_research/` (`grep -cxF 'sdd/state/.design_research/' .gitignore` = 1).
- `intake.json.updated_at` — `"format": "date-time"` string (TASK-3469, `sdd/templates/intake.schema.json`).
- `git rev-parse --git-common-dir` — prints the shared `.git` dir (same for every linked worktree). It may be relative to the cwd, so resolve it.
- `.claude/commands/sdd-status.md:18` — "- Read-only — do not modify any files." **Must remain unchanged** (spec AC).

### Does NOT Exist
- ~~`scripts/sdd/prune_intake.py`~~ — created here.
- ~~Any existing SDD script that deletes directories~~ — this is the first. Keep the safety checks strict.
- ~~A `/sdd-status` prune step~~ — explicitly not added.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/prune_intake.py", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_prune_intake.py", "action": "CREATE"},
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
- **Daily gate**: the stamp defaults to `<git-common-dir>/sdd-intake-prune.stamp`,
  so all worktrees share one budget. Touch the stamp **before** pruning so two
  near-simultaneous hook runs can't both prune. A stamp younger than 24 h ⇒ exit
  0 silently. If `git rev-parse` fails (not a repo), `--daily` exits 0 and does
  nothing: the hook must never fail.
- Age source: `intake.json.updated_at` (ISO-8601; treat a naive timestamp as
  UTC). Fall back to the dir mtime when the file is missing, unreadable, or
  unparsable.
- The CLI is dry-run by default; the hook passes `--daily --apply`. The library
  functions never print; `main` prints the report lines.

---

## Implementation Blueprint

### Steps (in order)
1. Write `prune_intake.py`. *Why*: deterministic and testable, instead of a `find -delete` in a hook.
2. Write the tests with a `tmp_path` fake root at `tmp_path/"sdd"/"state"/".intake"`
   and an explicit `--stamp`/`stamp=` path. *Why*: exercises the suffix check and
   the gate without touching the repo or its `.git`.
3. Add the `.gitignore` line. *Why*: G5/G13, staging never gets committed.

### `scripts/sdd/prune_intake.py` (CREATE)
```python
"""``prune_intake.py`` — prune stale /sdd-spec intake staging (FEAT-577).

Staged intake runs live under ``sdd/state/.intake/<slug>-<RUN_ID>/`` (git-ignored).
A git hook (installed by ``scripts/sdd/install_hooks.py``) calls this with
``--daily --apply`` on checkout/merge/commit; ``--daily`` lets it run at most once
per 24 h. Dry-run by default; only direct, non-symlink child directories of a
root that resolves to ``.../sdd/state/.intake`` are ever deleted.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEFAULT_ROOT: Path = Path("sdd/state/.intake")
DEFAULT_MAX_AGE_DAYS: int = 10
DAILY_INTERVAL: timedelta = timedelta(hours=24)
STAMP_NAME: str = "sdd-intake-prune.stamp"


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
    # FILL IN: parse run_dir/"intake.json" updated_at via datetime.fromisoformat (accept trailing "Z"; naive ⇒ UTC);
    # on OSError/ValueError/KeyError/TypeError/json.JSONDecodeError use
    # datetime.fromtimestamp(run_dir.stat().st_mtime, tz=timezone.utc) with source "mtime" — bounded by spec M9


def find_stale(root: Path, max_age_days: int = DEFAULT_MAX_AGE_DAYS, now: datetime | None = None) -> list[StaleIntake]:
    """Direct child dirs of ``root`` (no symlinks) older than ``max_age_days``. Missing root → []."""
    if not root.exists():
        return []
    resolved = _check_root(root)
    now = now or datetime.now(timezone.utc)
    # FILL IN: iterate sorted(resolved.iterdir()); skip symlinks (check is_symlink() before is_dir()) and non-dirs;
    # keep runs whose age > timedelta(days=max_age_days) — bounded by spec §4 M9 rows


def prune(
    root: Path, max_age_days: int = DEFAULT_MAX_AGE_DAYS, *, apply: bool = False, now: datetime | None = None
) -> list[StaleIntake]:
    """Return the stale runs; delete them only when ``apply``. Raises ValueError for an unsafe root."""
    stale = find_stale(root, max_age_days, now)
    if apply:
        for run in stale:
            # FILL IN: re-assert run.path.parent == _check_root(root) and not run.path.is_symlink(), then
            # shutil.rmtree(run.path); logger.info("pruned %s", run.path) — bounded by "Safety first"
            pass
    return stale


def default_stamp() -> Path | None:
    """``$(git rev-parse --git-common-dir)/sdd-intake-prune.stamp`` (shared by all worktrees); None outside a repo."""
    # FILL IN: subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True, check=False);
    # non-zero ⇒ None; else Path(out.strip()).resolve() / STAMP_NAME — bounded by "hook must never fail"


def claim_daily_slot(stamp: Path, now: datetime | None = None) -> bool:
    """True (and touch the stamp) when the last run was ≥ 24 h ago or never; False otherwise."""
    # FILL IN: missing stamp or now - mtime >= DAILY_INTERVAL ⇒ stamp.parent.mkdir(parents=True, exist_ok=True),
    # stamp.touch(), os.utime to `now` when given (tests), return True; else False — bounded by "touch before prune"


def main(argv: list[str] | None = None) -> int:
    """CLI: --root, --older-than-days (default 10), --apply, --daily, --stamp. Exit 0; 2 on an unsafe root."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--older-than-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--apply", action="store_true", help="delete (default: dry-run)")
    parser.add_argument("--daily", action="store_true", help="run at most once per 24 h (git hook mode)")
    parser.add_argument("--stamp", type=Path, default=None, help="daily stamp file (default: <git-common-dir>/" + STAMP_NAME + ")")
    args = parser.parse_args(argv)
    # FILL IN: when --daily: stamp = args.stamp or default_stamp(); None or not claim_daily_slot(stamp) ⇒ return 0.
    # Then prune(); ValueError ⇒ print message, return 2; print "<pruned|would prune> <name> (<age:.1f>d, <source>)"
    # per run; return 0 — bounded by spec M9 CLI contract


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why this shape**: spec §3 Module 9 fixes the signatures. `_check_root` makes
the unsafe-root check and the per-deletion re-check share one rule. The gate
lives here, not in shell, so it is unit-testable.

### `.gitignore` (MODIFY)
```gitignore
# occurrences: 1 (verified: grep -cxF 'sdd/state/.design_research/' .gitignore) — line 407
# AFTER — insert below it:
# FEAT-577: id-less /sdd-spec intake staging; promoted to sdd/state/<FEAT-ID>/intake/ on commit, pruned after 10 days by a daily git hook (scripts/sdd/install_hooks.py)
sdd/state/.intake/
```

### `tests/sdd_scripts/test_prune_intake.py` (CREATE)
```python
"""Tests for scripts/sdd/prune_intake.py (FEAT-577, spec §4 Module 9)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.sdd.prune_intake import claim_daily_slot, find_stale, main, prune

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


# FILL IN: test_find_stale_uses_updated_at, test_find_stale_falls_back_to_mtime, test_prune_dry_run_deletes_nothing,
# test_prune_apply_deletes_only_stale_children (fresh run, root-level file, symlinked dir survive),
# test_prune_rejects_unsafe_root (ValueError; main(["--root", str(tmp_path)]) == 2), test_prune_missing_root_is_noop,
# test_daily_gate_skips_within_24h, test_daily_gate_first_run_creates_stamp (use tmp_path stamp + os.utime),
# test_gitignore_ignores_intake_staging, test_sdd_status_stays_read_only (neither .claude/commands/sdd-status.md
# nor .agent/workflows/sdd-status.md mentions "prune_intake") — bounded by spec §4 M9 rows
```

### FILL IN checklist
- [ ] `run_age`, `find_stale` loop, `prune` re-check + rmtree
- [ ] `default_stamp`, `claim_daily_slot`, `main` body
- [ ] the ten tests

---

## Acceptance Criteria

- [ ] `prune_intake.py` is dry-run by default and deletes only stale, direct, non-symlink children of a `.../sdd/state/.intake` root
- [ ] `--daily` runs at most once per 24 h per repository (stamp in the git common dir), and exits 0 silently otherwise or outside a repo
- [ ] An unsafe `--root` exits 2 and deletes nothing
- [ ] `sdd/state/.intake/` is git-ignored; `/sdd-status` is unchanged
- [ ] `pytest tests/sdd_scripts/test_prune_intake.py -q` passes; `ruff check scripts/sdd/prune_intake.py` is clean

---

## Validation Commands

- `pytest tests/sdd_scripts/test_prune_intake.py -q`

---

## Test Specification

See the blueprint test module.

---

## Agent Instructions

1. Read spec §2 "Staging retention" and §3 Module 9 (revision 0.3).
2. Confirm TASK-3469 is done (the `updated_at` field is defined).
3. Implement; run the Validation Commands and `ruff check scripts/sdd/prune_intake.py`.
4. Move this file to `sdd/tasks/completed/` and set the index status to `done`.

---

## Completion Note

Created `scripts/sdd/prune_intake.py` implementing `StaleIntake` (Pydantic
model), `_check_root`, `run_age`, `find_stale`, `prune`, `default_stamp`,
`claim_daily_slot`, `main` exactly per the blueprint signatures. Safety:
`_check_root` requires the resolved path's last 3 parts to be
`("sdd","state",".intake")` (ValueError / exit 2 otherwise, nothing
deleted); `prune(apply=True)` re-checks parent + non-symlink before
`shutil.rmtree`; `claim_daily_slot` touches the stamp before returning True;
`default_stamp()` returns `None` on any git failure and `main --daily`
exits 0 in that case (hook never fails). Added `sdd/state/.intake/` to
`.gitignore`. Wrote `tests/sdd_scripts/test_prune_intake.py` (10 tests, all
via `tmp_path`, no real-`$HOME` touch per prior feedback).

`pytest tests/sdd_scripts/test_prune_intake.py -q` → 10 passed.
`ruff check scripts/sdd/prune_intake.py tests/sdd_scripts/test_prune_intake.py` → clean.

Delivered natively (sonnet) and merged cleanly via `coder_merge`
(outcome: merged; engine lint autofix commit `4772072ab` — black only).

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: 169s · Tokens: 90148 (subagent total, backend-reported)
