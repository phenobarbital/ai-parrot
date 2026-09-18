# TASK-3461: `doc_taxonomy` CLI — list SDD docs by project / tag

**Feature**: FEAT-576 — SDD Document Taxonomy (`projects` and `tags` frontmatter)
**Spec**: `sdd/specs/sdd-spec-changes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3459
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 4** (goals G6 support, AC2). `/sdd-status` and `/sdd-next`
(TASK-3466) call this CLI to get the spec paths that match `--project`/`--tag`, and
`--summary` gives the vocabulary overview that keeps tag sprawl visible (spec §7 risk).

---

## Scope

- Create `scripts/sdd/doc_taxonomy.py` with `TaxonomyRow`, `collect()`, `filter_rows()`,
  `main()` exactly as the spec §3 M4 skeleton fixes them.
- Write `tests/sdd_scripts/test_doc_taxonomy.py`.

**NOT in scope**: editing any command `.md` (TASK-3466); writing to any document (read-only CLI).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/doc_taxonomy.py` | CREATE | query CLI |
| `tests/sdd_scripts/test_doc_taxonomy.py` | CREATE | unit + real-repo smoke test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from scripts.sdd.sdd_meta import normalize_project, normalize_tag, parse_taxonomy  # created by TASK-3459
from pydantic import BaseModel, ValidationError   # pydantic v2 (used by sdd_meta.py:20)
```

### Existing Signatures to Use
```python
# scripts/sdd/check_task_graph.py — CLI pattern to mirror:
#   module docstring shows `python -m scripts.sdd.check_task_graph ... [--root .] [--json]` (line 44)
def main(argv: list[str] | None = None) -> int:  # check_task_graph.py:445
```
Doc locations (verified 2026-09-19): specs are `sdd/specs/*.spec.md`; exploration docs are
`sdd/proposals/*.brainstorm.md` and `sdd/proposals/*.proposal.md`. `sdd/proposals/` also holds
files NOT following that naming (e.g. `FEAT-TBD_sweetspot_brainstorm.md`) — they are ignored.

### Does NOT Exist
- ~~`scripts/sdd/doc_taxonomy.py`~~ — created by this task
- ~~a `spec_index` / spec-catalog module to reuse~~ — scan the globs directly

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/doc_taxonomy.py", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_doc_taxonomy.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/check_task_graph.py#main"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- AND across `--project`/`--tag`, OR within a repeated flag; filter values normalized with
  `normalize_project`/`normalize_tag` so `--project formdesigner` matches `parrot-formdesigner`.
- A doc whose taxonomy fails validation is skipped with `logger.warning` — the scan never aborts (AC3).
- Output goes to stdout via `sys.stdout.write` (it is program output, not logging).
- Exit 0 on a successful scan even when nothing matches; exit 2 on bad arguments (argparse default).
- Paths printed repo-relative (relative to `--root`, default `.`), sorted.

---

## Implementation Blueprint

### Steps (in order)
1. Create the module with the model and the three functions — *why*: signatures fixed by spec §3 M4.
2. Implement `--paths-only` (one path per line), `--json` (list of row dicts), default table, `--summary` — *why*: M5 consumes `--paths-only`; humans use the table/summary.
3. Write tests, including a smoke run over the real repo — *why*: AC2 requires a clean scan of existing docs.

### `scripts/sdd/doc_taxonomy.py` (CREATE)
```python
"""List SDD docs by ``projects``/``tags`` frontmatter (FEAT-576).

Usage::

    python -m scripts.sdd.doc_taxonomy [--root .] [--kind spec|brainstorm|proposal|all]
        [--project P ...] [--tag T ...] [--paths-only | --json | --summary]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from scripts.sdd.sdd_meta import normalize_project, normalize_tag, parse_taxonomy

logger = logging.getLogger(__name__)

DocKind = Literal["spec", "brainstorm", "proposal", "all"]

_GLOBS: dict[str, str] = {
    "spec": "sdd/specs/*.spec.md",
    "brainstorm": "sdd/proposals/*.brainstorm.md",
    "proposal": "sdd/proposals/*.proposal.md",
}


class TaxonomyRow(BaseModel):
    """One SDD document and its taxonomy."""

    path: str
    kind: DocKind
    projects: list[str]
    tags: list[str]


def collect(root: Path, kind: DocKind = "all") -> list[TaxonomyRow]:
    """Scan sdd/specs/*.spec.md and sdd/proposals/*.{brainstorm,proposal}.md under ``root``.

    A doc whose frontmatter fails validation is skipped with a logged warning.
    """
    # FILL IN: iterate _GLOBS (all kinds, or just `kind`), parse_taxonomy each file inside
    #   try/except ValidationError -> logger.warning + continue; rows sorted by path — bounded by AC2/AC3
    raise NotImplementedError


def filter_rows(rows: list[TaxonomyRow], projects: list[str], tags: list[str]) -> list[TaxonomyRow]:
    """AND across the two flags, OR within each; filter values are normalized first."""
    # FILL IN: normalize filters; empty filter list == no constraint — bounded by test_filter_and_or_semantics
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns 0 on a successful scan, 2 on bad arguments."""
    parser = argparse.ArgumentParser(prog="python -m scripts.sdd.doc_taxonomy", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--kind", choices=["spec", "brainstorm", "proposal", "all"], default="all")
    parser.add_argument("--project", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--paths-only", action="store_true")
    mode.add_argument("--json", action="store_true")
    mode.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    # FILL IN: collect -> filter -> render per mode; --summary prints two Counter tables
    #   (projects, tags) as "<count>\t<value>" sorted by count desc then name — bounded by spec M4
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
```
**Why this shape**: spec §3 M4 fixes the model, function names and flags; M5 depends on the
exact `--kind spec --paths-only` contract, so do not rename flags.

### FILL IN checklist
- [ ] `collect` — globbing, per-file try/except, sorted rows; AC2/AC3
- [ ] `filter_rows` — normalized AND/OR semantics
- [ ] `main` — four output modes; exit codes 0 / 2

---

## Acceptance Criteria

- [ ] `python -m scripts.sdd.doc_taxonomy --summary` completes over the real repo with exit 0 (AC2)
- [ ] `--kind spec --paths-only --project formdesigner` prints repo-relative spec paths, one per line
- [ ] A malformed doc is skipped with a warning, the rest still listed (AC3)
- [ ] `ruff check scripts/sdd/doc_taxonomy.py` clean

---

## Validation Commands
- `pytest tests/sdd_scripts/test_doc_taxonomy.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_doc_taxonomy.py
"""Tests for scripts.sdd.doc_taxonomy (FEAT-576)."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.sdd.doc_taxonomy import TaxonomyRow, collect, filter_rows, main

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write(root: Path, rel: str, front: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\ntype: feature\nbase_branch: dev\n{front}---\n# x\n", encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _write(tmp_path, "sdd/specs/a.spec.md", "projects: [ai-parrot]\ntags: [memory]\n")
    _write(tmp_path, "sdd/specs/b.spec.md", "projects: [parrot-formdesigner]\ntags: [mcp]\n")
    _write(tmp_path, "sdd/proposals/c.brainstorm.md", "tags: [memory]\n")
    _write(tmp_path, "sdd/specs/bad.spec.md", "tags: ['!!']\n")
    return tmp_path


def test_collect_skips_invalid_doc(repo: Path) -> None:
    paths = [r.path for r in collect(repo)]
    assert "sdd/specs/bad.spec.md" not in paths
    assert len(paths) == 3


def test_filter_and_or_semantics(repo: Path) -> None:
    rows = collect(repo)
    assert {r.path for r in filter_rows(rows, [], ["memory"])} == {"sdd/specs/a.spec.md", "sdd/proposals/c.brainstorm.md"}
    assert [r.path for r in filter_rows(rows, ["ai-parrot"], ["memory"])] == ["sdd/specs/a.spec.md"]
    assert {r.path for r in filter_rows(rows, ["formdesigner", "ai-parrot"], [])} == {"sdd/specs/a.spec.md", "sdd/specs/b.spec.md"}


def test_cli_paths_only(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(repo), "--kind", "spec", "--paths-only", "--tag", "mcp"]) == 0
    assert capsys.readouterr().out.split() == ["sdd/specs/b.spec.md"]


def test_doc_taxonomy_on_repo() -> None:
    assert isinstance(collect(REPO_ROOT), list)
```

---

## Agent Instructions

1. Read spec §3 Module 4 and §7 (tag sprawl risk).
2. Confirm TASK-3459 is done.
3. Implement from the blueprint, run Validation Commands, fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
