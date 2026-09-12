# TASK-3153: Worktree naming rule as code — `plan_worktree()` in `sdd_meta`

**Feature**: FEAT-552 — Worktree Creation Ownership
**Spec**: `sdd/specs/worktree-creation-ownership.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Worktree naming is currently prose repeated across five
markdown files, in two mutually incompatible templates (`feat-<FEAT-ID>-<slug>`
vs `feat-<id>-<slug>`) — which is why this repo has both
`feat-538-workingmemory-toolkit` and `feat-FEAT-538-workingmemory-toolkit`.
This task hoists the rule into `scripts/sdd/sdd_meta.py`, the module that
already owns exactly this kind of hoisted rule (`WORK_KIND_FLOW` carries the
comment *"This mapping used to live only as prose in
.claude/agents/sdd-research.md (FEAT-466)"*).

Everything else in FEAT-552 depends on this function existing.

---

## Scope

- Add `WORKTREE_ROOT`, `WorktreePlan`, and `plan_worktree()` to
  `scripts/sdd/sdd_meta.py`, appended after `resolve_flow()`.
- Write `tests/sdd_scripts/test_worktree_plan.py` covering the seven cases in
  spec §4.

**NOT in scope**: any git command (that is TASK-3154); any edit to
`.claude/**` or `CLAUDE.md`; renaming existing branches or worktrees.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/sdd_meta.py` | MODIFY | Append `WORKTREE_ROOT`, `WorktreePlan`, `plan_worktree()` |
| `tests/sdd_scripts/test_worktree_plan.py` | CREATE | Unit tests for the naming rule |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from scripts.sdd.sdd_meta import FlowMeta, plan_worktree, WorktreePlan  # after this task
from pydantic import BaseModel, model_validator   # verified: scripts/sdd/sdd_meta.py:20
```
The test module follows the existing sibling convention — absolute
`from scripts.sdd.sdd_meta import ...`, no `sys.path` manipulation
(verified: `tests/sdd_scripts/test_sdd_meta.py:11`).

### Existing Signatures to Use
```python
# scripts/sdd/sdd_meta.py
KNOWN_BRANCHES: frozenset[str] = frozenset({"main", "staging", "dev"})   # line 29
WORK_KIND_FLOW: dict[str, tuple[str, str]]                               # line 34

class FlowMeta(BaseModel):                                               # line 41
    type: Literal["feature", "hotfix"]                                   # line 44
    base_branch: str                                                     # line 45

    @model_validator(mode="after")
    def _hotfix_implies_main(self) -> "FlowMeta":                        # line 47
        # raises ValueError when type == "hotfix" and base_branch != "main"

def resolve_flow(*, kind=None, doc_path=None,
                 type_override=None, base_branch_override=None) -> FlowMeta:   # line 104
```
The module already has `from __future__ import annotations` (line 13) and a
module-level `logger` (line 22). The file currently ends at line 159.

### Does NOT Exist
- ~~`scripts/sdd/worktree.py`~~ — `scripts/sdd/` holds only
  `calibrate_rlimit_as.py`, `check_id_collisions.py`, `close_task.sh`,
  `heal_orphans.sh`, `id_ledger.py`, `insight.py`, `lint_new.py`,
  `migrate_index.py`, `reserve_ids.py`, `sdd_meta.py`, `tag_yaml_fixtures.py`
- ~~`sdd_meta.worktree_name()`~~ — the function is named `plan_worktree`
- ~~`FlowMeta.feature_id`~~ / ~~`FlowMeta.slug`~~ — `FlowMeta` has exactly two
  fields, `type` and `base_branch`. Do not add fields to it.
- ~~`.worktrees/`~~ — SDD worktrees live under `.claude/worktrees/`; the
  `.worktrees/_active.json` mentioned in `.claude/rules/worktree-*.md` is read
  by no SDD command and does not exist in this repo

---

## Implementation Notes

### Key Constraints
- Pure function: no `subprocess`, no `pathlib` filesystem access, no git.
- `path` is **repo-relative** (`.claude/worktrees/<name>`), a `str`, not a `Path`
  — the caller joins it to its own repo root.
- `base_ref` is always remote-qualified (`origin/<base_branch>`). This is what
  stops a worktree from inheriting an unpushed local `HEAD` — the FEAT-466 root
  cause (PR #1250).
- Do NOT re-derive the hotfix/main rule: `FlowMeta` already enforces it
  (line 47). For a hotfix, `meta.base_branch` is `"main"` by construction.
- Google-style docstrings + strict type hints, matching the module.

### References in Codebase
- `scripts/sdd/sdd_meta.py:31-38` — the prose-to-code hoist precedent
- `tests/sdd_scripts/test_sdd_meta.py` — test style to follow (plain functions,
  `tmp_path`, `pytest.raises(..., match=...)`)

---

## Implementation Blueprint

### Steps (in order)
1. Append the three new symbols to `scripts/sdd/sdd_meta.py` after
   `resolve_flow()` — *why*: the module is the SSOT for SDD flow rules, and
   `plan_worktree` consumes `FlowMeta`, so it must come after it.
2. Validate inputs before building any string — *why*: a silently-wrong
   worktree name is the exact failure mode FEAT-552 exists to remove; failing
   loudly at plan time is cheap.
3. Write the tests and run them — *why*: this rule is consumed by five callers;
   a regression here is a regression everywhere.

### `scripts/sdd/sdd_meta.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    return FlowMeta(type=final_type, base_branch=final_base)' scripts/sdd/sdd_meta.py)
# AFTER — append below `    return FlowMeta(type=final_type, base_branch=final_base)` (verified: scripts/sdd/sdd_meta.py:159, last line of file)


#: Every SDD worktree lives directly under this repo-relative directory.
WORKTREE_ROOT: str = ".claude/worktrees"

#: A reserved feature id, e.g. ``FEAT-552``. Bare numbers are rejected.
_FEATURE_ID_RE = re.compile(r"^FEAT-\d+$")


class WorktreePlan(BaseModel):
    """Where a feature/hotfix worktree goes and what it branches from."""

    name: str
    path: str
    base_ref: str


def plan_worktree(
    meta: FlowMeta,
    *,
    slug: str,
    feature_id: str | None = None,
    jira_key: str | None = None,
) -> WorktreePlan:
    """Resolve the canonical worktree name, path and base ref for a run.

    Naming (confirmed canonical 2026-09-11 — it is what /sdd-done greps on):
      * ``type == "feature"`` -> ``feat-<feature_id>-<slug>``, e.g.
        ``feat-FEAT-552-worktree-creation-ownership``. The doubled
        ``feat-FEAT-`` prefix is intentional, not a bug.
      * ``type == "hotfix"``  -> ``hotfix-<jira_key>-<slug>`` (FEAT-466: a
        hotfix reserves no FEAT-<NNN>; its identity is the Jira key).

    ``base_ref`` is always ``origin/<meta.base_branch>`` so a worktree can
    never inherit an unpushed local HEAD. For a hotfix that is ``origin/main``
    by construction — ``FlowMeta`` already refuses any other base branch for
    a hotfix (see ``_hotfix_implies_main``).

    Args:
        meta: Resolved flow metadata.
        slug: Feature slug, kebab-case.
        feature_id: ``FEAT-<NNN>``; required when ``meta.type == "feature"``.
        jira_key: Jira issue key; required when ``meta.type == "hotfix"``.

    Returns:
        A ``WorktreePlan`` whose ``path`` is repo-relative.

    Raises:
        ValueError: When ``slug`` is empty or blank; when a feature run has no
            ``feature_id`` or one not matching ``^FEAT-\d+$``; when a hotfix
            run has no ``jira_key``.
    """
    # FILL IN: validate slug, then branch on meta.type to build `name` —
    #   bounded by the two templates above and by the ValueError contract in
    #   this docstring (AC: test_plan_* in tests/sdd_scripts/test_worktree_plan.py).
    #   Every error message must name the missing/!invalid argument so the CLI
    #   in TASK-3154 can surface it verbatim to an operator.
    raise NotImplementedError
```
**Why this shape**: `WorktreePlan` is the contract TASK-3154's CLI and all five
markdown callers depend on, so its three field names are fixed. Keeping the
function pure (no git) is what makes the seven table-driven tests possible
without a git fixture. `_FEATURE_ID_RE` exists so `feature_id="552"` is a loud
error rather than a worktree named `feat-552-…` that collides with the legacy
template this feature is removing. Add `import re` to the module's import block
(it is not currently imported).

### `tests/sdd_scripts/test_worktree_plan.py` (CREATE)
```python
"""Unit tests for ``scripts.sdd.sdd_meta.plan_worktree`` — FEAT-552 / TASK-3153."""

from __future__ import annotations

import pytest

from scripts.sdd.sdd_meta import WORKTREE_ROOT, FlowMeta, WorktreePlan, plan_worktree

SLUG = "worktree-creation-ownership"


def test_plan_feature_name_keeps_feat_prefix() -> None:
    """A feature keeps the doubled `feat-FEAT-` prefix — /sdd-done greps it."""
    plan = plan_worktree(
        FlowMeta(type="feature", base_branch="dev"), slug=SLUG, feature_id="FEAT-552"
    )
    assert isinstance(plan, WorktreePlan)
    assert plan.name == f"feat-FEAT-552-{SLUG}"
    assert plan.path == f"{WORKTREE_ROOT}/feat-FEAT-552-{SLUG}"


@pytest.mark.parametrize("branch", ["dev", "staging"])
def test_plan_feature_base_ref_is_remote_qualified(branch: str) -> None:
    """base_ref is always origin/<base_branch> — never a local HEAD."""
    # FILL IN: assert plan.base_ref == f"origin/{branch}" — bounded by the
    #   "never inherit an unpushed local HEAD" constraint (spec §7)


def test_plan_hotfix_uses_jira_key_and_origin_main() -> None:
    """FEAT-466: a hotfix is named from its Jira key and branches from main."""
    # FILL IN: build FlowMeta(type="hotfix", base_branch="main"), assert
    #   name == f"hotfix-NAV-8036-{SLUG}" and base_ref == "origin/main"


def test_plan_feature_without_feature_id_raises() -> None:
    """A feature with no id is a programming error, not a default."""
    with pytest.raises(ValueError, match="feature_id"):
        plan_worktree(FlowMeta(type="feature", base_branch="dev"), slug=SLUG)


def test_plan_feature_with_bare_number_raises() -> None:
    """`552` is not `FEAT-552` — reject it rather than emit a legacy-style name."""
    # FILL IN: pytest.raises(ValueError) for feature_id="552"


def test_plan_hotfix_without_jira_key_raises() -> None:
    """A hotfix has no FEAT id, so the Jira key is mandatory."""
    # FILL IN: pytest.raises(ValueError, match="jira_key")


@pytest.mark.parametrize("slug", ["", "   "])
def test_plan_empty_slug_raises(slug: str) -> None:
    """An empty slug would yield `feat-FEAT-552-` — refuse it."""
    # FILL IN: pytest.raises(ValueError, match="slug")
```
**Why**: the two positive tests are written out in full so the executor has the
exact expected strings; the rest are stubs bounded by their docstring. Do not
rename the test functions — TASK-3160 and spec §4 refer to them by name.

### FILL IN checklist
- [ ] `sdd_meta.py::plan_worktree` — body: validation order and the two name
      templates; bounded by the docstring's Raises contract and spec §3 M1
- [ ] `sdd_meta.py` — add `import re` to the existing import block (line 13-20)
- [ ] `test_worktree_plan.py` — five stubbed test bodies; bounded by each
      docstring and by spec §4's test table

---

## Acceptance Criteria

- [ ] `plan_worktree(FlowMeta(type="feature", base_branch="dev"), slug="x", feature_id="FEAT-552").name == "feat-FEAT-552-x"`
- [ ] `plan_worktree(FlowMeta(type="hotfix", base_branch="main"), slug="x", jira_key="NAV-8036").name == "hotfix-NAV-8036-x"`
- [ ] `base_ref` is `origin/<base_branch>` in every case, never a bare branch name and never `HEAD`
- [ ] Missing `feature_id`, malformed `feature_id`, missing `jira_key` and blank `slug` each raise `ValueError` naming the offending argument
- [ ] All tests pass: `pytest tests/sdd_scripts/test_worktree_plan.py -v`
- [ ] Existing suite still green: `pytest tests/sdd_scripts/test_sdd_meta.py tests/sdd_scripts/test_sdd_meta_resolve_flow.py -q`
- [ ] No linting errors: `ruff check scripts/sdd/sdd_meta.py tests/sdd_scripts/test_worktree_plan.py`
- [ ] `plan_worktree` performs no I/O — `grep -n "subprocess\|open(\|Path(" ` over the added block returns nothing

---

## Test Specification

See the `tests/sdd_scripts/test_worktree_plan.py` blueprint block above — it is
the scaffold. Seven test functions, names fixed by spec §4.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 1, §7 Known Risks)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm `sdd_meta.py` still ends at
   `resolve_flow` and that `FlowMeta` still has exactly `type` and `base_branch`
4. **Update status** in `sdd/tasks/index/worktree-creation-ownership.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:`
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3153-plan-worktree-rule.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker orchestrator (FEAT-549 pool)
**Date**: 2026-09-11
**Notes**: Implemented `WORKTREE_ROOT`, `WorktreePlan`, and `plan_worktree()`
in `scripts/sdd/sdd_meta.py` exactly per the blueprint; all 9 tests in
`tests/sdd_scripts/test_worktree_plan.py` pass, existing `test_sdd_meta.py`
+ `test_sdd_meta_resolve_flow.py` suites (21 tests) stay green, and
`ruff check` is clean on both files.

**Deviations from spec**: none

Seat: gemini · Backend: google-compat · Model: gemini-3.5-flash · Attempts: 2 (1 qwen/nova timeout, 1 gemini/google-compat success) · Duration: 583.97s · Tokens: 188644 in / 2637 out
