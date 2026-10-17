# TASK-4425: Brief metadata module (`scripts/sdd/brief_meta.py`)

**Feature**: FEAT-698 — /sdd-brief One-Command Brief Flow for Hotfixes and Single-Issue Fixes
**Spec**: `sdd/specs/sdd-brief-hotfix-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models / §3 Module 2. Briefs are a new SDD document kind
(`kind: brief`) that **bypasses `FlowMeta` entirely** — `FlowMeta` ships in
the wikitoolkit wheel and its `hotfix ⇒ main` validator cannot represent a
dev-based ledger brief. This task creates the repo-local model + planning
helpers every other FEAT-698 task builds on: frontmatter parsing/emission,
the worktree plan (`hotfix-<KEY>-<slug>` / `fix-<KEY>-<slug>`), task ids
(`HOTFIX-<KEY>-N`) and the per-brief index writer with the non-empty
`feature_id: "BRIEF-<KEY>"` identity (design-research S1/S2).

---

## Scope

- Create `scripts/sdd/brief_meta.py` with `BriefSource`, `BriefMeta`,
  `parse_brief`, `emit_brief_frontmatter`, `brief_worktree_plan`,
  `plan_brief_worktree`, `brief_task_id`, `write_brief_index`.
- Enforce: ledger source ⇒ `base_branch == "dev"`; `key` and `slug` safe for
  git branch names.
- Write `tests/sdd_scripts/test_brief_meta.py`.

**NOT in scope**: `ensure_worktree.py` changes (TASK-4426/4427); the brief
template (TASK-4428); any change to `scripts/sdd/sdd_meta.py` or
`packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` — both
are read-only for this feature.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/brief_meta.py` | CREATE | Brief model + worktree/index planning |
| `tests/sdd_scripts/test_brief_meta.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from scripts.sdd.sdd_meta import WORKTREE_ROOT, WorktreePlan  # verified: scripts/sdd/sdd_meta.py:10-26 (re-export shim)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py  (re-exported by scripts/sdd/sdd_meta.py)
WORKTREE_ROOT: str = ".claude/worktrees"        # line 322
class WorktreePlan(BaseModel):                  # line 328
    name: str                                   # line 331
    path: str                                   # line 332 — repo-relative, f"{WORKTREE_ROOT}/{name}"
    base_ref: str                               # line 333 — always f"origin/{base_branch}"
# _read_frontmatter rules to mirror (do NOT import the private helper):  lines 112-126
#   block must start at byte 0 with '---'; text.split('---', 2); yaml.safe_load(parts[1]) or {}
```

### Does NOT Exist
- ~~`FlowMeta.type == "brief"`~~ — must never exist; do not touch `FlowMeta`.
- ~~`plan_worktree(..., brief_key=...)`~~ — `plan_worktree` stays feature/hotfix-only (sdd_meta.py:336-390); build `WorktreePlan` directly.
- ~~`scripts.sdd.sdd_meta._read_frontmatter`~~ — private, not re-exported by the shim; reimplement the 6-line rule locally.
- ~~`sdd/briefs/`~~ directory — does not exist in the repo; it is only ever created inside worktrees.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/brief_meta.py", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_brief_meta.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#WorktreePlan"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Mirror `scripts/sdd/ensure_worktree.py` style: `from __future__ import
annotations`, module `logger = logging.getLogger(__name__)`, Pydantic v2
models, Google docstrings, strict typing.

### Key Constraints
- Naming is load-bearing: `/sdd-done` (TASK-4435) greps worktrees by these
  prefixes. `hotfix-<KEY>-<slug>` when `base_branch == "main"`, otherwise
  `fix-<KEY>-<slug>` — the dash form; never `fix/…` (that is the `/sdd-fix`
  fast-lane *branch* namespace, which has no worktree).
- `feature_id` in the index header is `f"BRIEF-{key}"` — non-empty (the
  sdd_coder checkpoint rejects empty, checkpoint.py:462-466) and never
  matching `^FEAT-\d+$`.
- No network, no git calls in this module — pure data + filesystem write.

---

## Implementation Blueprint

### Steps (in order)
1. Create `scripts/sdd/brief_meta.py` from the block below — *why*: every later task imports these exact names.
2. Fill the `write_brief_index` per-task defaulting — *why*: callers pass partial task dicts; the index must be schema-complete for `check_task_graph` and the sdd-coder engine.
3. Write the tests — *why*: AC-1..AC-6 are the contract other tasks rely on.

### `scripts/sdd/brief_meta.py` (CREATE)
```python
"""Brief frontmatter model and worktree/index planning for ``/sdd-brief`` (FEAT-698).

Briefs never go through ``FlowMeta``: it ships in the wikitoolkit wheel and its
``hotfix => main`` validator cannot represent a dev-based ledger brief. This
module therefore builds ``WorktreePlan`` directly and owns the brief's identity.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from scripts.sdd.sdd_meta import WORKTREE_ROOT, WorktreePlan

logger = logging.getLogger(__name__)

#: Repo-relative home of every brief artifact, inside a worktree only.
BRIEFS_DIR: str = "sdd/briefs"
#: Prefix of the per-brief index ``feature_id`` — non-empty, never ``FEAT-<NNN>``.
BRIEF_ID_PREFIX: str = "BRIEF-"
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

SourceType = Literal["code-scanning", "github-issue", "jira", "ledger", "text", "file"]


class BriefSource(BaseModel):
    """Where a brief came from."""

    type: SourceType
    ref: str = Field(..., min_length=1)
    url: str | None = None


class BriefMeta(BaseModel):
    """Frontmatter of ``sdd/briefs/<slug>.brief.md``."""

    kind: Literal["brief"]
    slug: str
    key: str
    base_branch: str = "main"
    source: BriefSource
    jira_issue_key: str | None = None
    ledger_issue: str | None = None
    created: str

    @field_validator("slug", "key")
    @classmethod
    def _branch_safe(cls, value: str) -> str:
        """Reject values that cannot appear in a git branch / worktree dir name."""
        # FILL IN: strip, then raise ValueError unless _SAFE_REF_RE matches — bounded by AC-2
        raise NotImplementedError

    @model_validator(mode="after")
    def _ledger_implies_dev(self) -> "BriefMeta":
        """A ledger-sourced brief always bases on dev (binding brainstorm decision)."""
        # FILL IN: raise ValueError when source.type == "ledger" and base_branch != "dev" — bounded by AC-3
        return self

    @property
    def feature_id(self) -> str:
        """Index identity: ``BRIEF-<KEY>``."""
        return f"{BRIEF_ID_PREFIX}{self.key}"

    @property
    def brief_path(self) -> str:
        """Repo-relative path of the brief document."""
        return f"{BRIEFS_DIR}/{self.slug}.brief.md"

    @property
    def index_path(self) -> str:
        """Repo-relative path of the per-brief index."""
        return f"{BRIEFS_DIR}/{self.slug}.index.json"

    @property
    def tasks_dir(self) -> str:
        """Repo-relative directory holding the materialized task files."""
        return f"{BRIEFS_DIR}/{self.slug}/tasks"


def parse_brief(doc_path: Path) -> BriefMeta:
    """Parse a brief's leading YAML frontmatter.

    Raises:
        ValueError: when the file has no frontmatter block at byte 0.
        pydantic.ValidationError: when the block does not validate as ``BriefMeta``.
    """
    # FILL IN: same rules as sdd_meta._read_frontmatter (text.startswith('---'), split('---', 2),
    #          yaml.safe_load(...) or {}, must be a dict) — raise ValueError instead of returning None
    raise NotImplementedError


def emit_brief_frontmatter(meta: BriefMeta) -> str:
    """Render ``meta`` as a ``---``-delimited YAML block ending in a newline."""
    body = yaml.safe_dump(meta.model_dump(), sort_keys=False).rstrip()
    return f"---\n{body}\n---\n"


def brief_worktree_plan(*, slug: str, key: str, base_branch: str) -> WorktreePlan:
    """``hotfix-<key>-<slug>`` on main, ``fix-<key>-<slug>`` otherwise; base ``origin/<base_branch>``."""
    # FILL IN: validate slug/key with _SAFE_REF_RE (ValueError), pick the prefix, build
    #          WorktreePlan(name=..., path=f"{WORKTREE_ROOT}/{name}", base_ref=f"origin/{base_branch}") — AC-4
    raise NotImplementedError


def plan_brief_worktree(meta: BriefMeta) -> WorktreePlan:
    """Plan the worktree for an already-validated brief."""
    return brief_worktree_plan(slug=meta.slug, key=meta.key, base_branch=meta.base_branch)


def brief_task_id(meta: BriefMeta, n: int) -> str:
    """Local, unreserved task id ``HOTFIX-<KEY>-<n>`` (n >= 1)."""
    if n < 1:
        raise ValueError(f"task number must be >= 1, got {n}")
    return f"HOTFIX-{meta.key}-{n}"


def write_brief_index(meta: BriefMeta, tasks: list[dict[str, Any]], worktree_root: Path) -> Path:
    """Write ``sdd/briefs/<slug>.index.json`` (per-spec index schema, FEAT-145) and return its path."""
    header: dict[str, Any] = {
        "feature": meta.slug,
        "feature_id": meta.feature_id,
        "spec": meta.brief_path,
        "type": "brief",
        "base_branch": meta.base_branch,
        "created_at": meta.created,
        "completed_at": None,
        "parallel_semantics": "exclusive",
        "validation_contract": "required",
        "tasks": [],
    }
    # FILL IN: for each task dict require id/slug/title/file; default status="pending",
    #          depends_on=[], parallel=True, parallelism_notes="", priority="high", effort="S",
    #          assigned_to/started_at/completed_at=None; stamp feature_id/feature/spec from header — AC-5
    path = Path(worktree_root) / meta.index_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(header, indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote brief index %s (%d task(s))", path, len(header["tasks"]))
    return path
```
**Why this shape**: the properties centralize every repo-relative path so
`/sdd-brief`, `/sdd-done` and the dev-loop agree on one layout (spec §2).
`brief_worktree_plan` is keyword-only and separate from `plan_brief_worktree`
because the `ensure_worktree` CLI (TASK-4427) plans a worktree *before* the
brief file exists. Do not add a `type` field to `BriefMeta` — `type:` in
frontmatter is the `FlowMeta` key and must stay absent from briefs.

### `tests/sdd_scripts/test_brief_meta.py` (CREATE)
```python
"""Tests for ``scripts.sdd.brief_meta`` — FEAT-698 / TASK-4425."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.sdd.brief_meta import (
    BriefMeta,
    brief_task_id,
    brief_worktree_plan,
    emit_brief_frontmatter,
    parse_brief,
    plan_brief_worktree,
    write_brief_index,
)


def _meta(**overrides) -> BriefMeta:
    data = {
        "kind": "brief",
        "slug": "fix-path-injection",
        "key": "cs-224",
        "base_branch": "main",
        "source": {"type": "code-scanning", "ref": "224"},
        "created": "2026-10-17T00:00:00+00:00",
    }
    data.update(overrides)
    return BriefMeta(**data)

# FILL IN: one test per AC-1..AC-6 (see Test Specification)
```

### FILL IN checklist
- [ ] `BriefMeta._branch_safe` — strip + regex; bounded by AC-2
- [ ] `BriefMeta._ledger_implies_dev` — bounded by AC-3
- [ ] `parse_brief` — frontmatter rules mirrored from sdd_meta.py:112-126; bounded by AC-1
- [ ] `brief_worktree_plan` — naming + base_ref; bounded by AC-4
- [ ] `write_brief_index` — per-task defaulting; bounded by AC-5
- [ ] tests for AC-1..AC-6

---

## Acceptance Criteria

- [ ] AC-1: `parse_brief(emit_brief_frontmatter(m) + body)` round-trips to an equal `BriefMeta`; a file without a byte-0 `---` raises `ValueError`.
- [ ] AC-2: `slug`/`key` containing `/`, spaces, or a leading `-` raise `ValidationError`.
- [ ] AC-3: `source.type == "ledger"` with `base_branch == "main"` raises `ValidationError`; with `"dev"` validates.
- [ ] AC-4: `plan_brief_worktree` → `hotfix-cs-224-fix-path-injection` / `origin/main` for main; `fix-<key>-<slug>` / `origin/dev` for dev; `path` is `.claude/worktrees/<name>`.
- [ ] AC-5: `write_brief_index` writes `sdd/briefs/<slug>.index.json` with `feature_id == "BRIEF-<key>"`, `type == "brief"`, `parallel_semantics == "exclusive"`, and every task carrying `feature_id`, `feature`, `spec`, `status`, `depends_on`, `file`.
- [ ] AC-6: `brief_task_id(m, 1) == "HOTFIX-cs-224-1"`; `n < 1` raises `ValueError`.
- [ ] `ruff check scripts/sdd/brief_meta.py tests/sdd_scripts/test_brief_meta.py` clean.
- [ ] `git diff` touches nothing under `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/`.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_brief_meta.py -q`

---

## Test Specification

```python
def test_round_trip(tmp_path): ...                 # AC-1
def test_missing_frontmatter_raises(tmp_path): ... # AC-1
@pytest.mark.parametrize("bad", ["a/b", "a b", "-x"])
def test_unsafe_slug_or_key_rejected(bad): ...     # AC-2
def test_ledger_requires_dev(): ...                # AC-3
def test_worktree_naming_main_and_dev(): ...       # AC-4
def test_index_header_and_task_defaults(tmp_path): ...  # AC-5
def test_brief_task_id(): ...                      # AC-6
```

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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4425 sdd-brief-hotfix-flow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
