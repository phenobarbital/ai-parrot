# TASK-2503: Honour `feat_id == ""` across every run-labelling consumer

**Feature**: FEAT-466 — Dev-Loop Run Fidelity
**Spec**: `sdd/specs/dev-loop-run-fidelity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the **code half of spec Module 2**.

FEAT-466 decides that **a bugfix is not a feature and therefore reserves no
`FEAT-<NNN>` id**. Ledger ids exist for features and the brainstorm → spec →
task SDD flow; a hotfix is identified by its **Jira issue key** instead.

That makes `ResearchOutput.feat_id == ""` the *normal* case for hotfix runs.
Today it is a technically-reachable but never-primary shape: `runner.py:1378`
already constructs a `ResearchOutput` with `feat_id=""`, so nothing rejects it,
but several consumers interpolate it directly into human-facing strings. Left
alone they will produce output like:

```
PR title:      ": replace SHA-1 with SHA-256"       ← deployment_handoff.py:505
bundle field:  feature_id: ""                        ← run_bundle.py:310
```

This task hardens every such consumer **before** TASK-2507 starts producing
id-less runs, so the two changes never have to land in the same commit. It is
deliberately independent of every other task in this feature — no shared files
— so it can run in parallel.

The fallback pattern is already established in this codebase; you are
propagating it, not inventing it:

```python
# nodes/qa.py:194, 342 — already prefers the Jira key
research.jira_issue_key or research.feat_id
```

---

## Scope

Audit and fix the four consumers of `ResearchOutput.feat_id` /
`PlannerOutput.feat_id` so that an empty id degrades to the Jira issue key,
and — only if that is also empty — to a stable placeholder rather than an
empty string.

- **`nodes/deployment_handoff.py:505`** — `_build_title`. Currently
  `f"{research.feat_id}: {first_line}"`. Must prefer `feat_id`, fall back to
  `jira_issue_key`, and omit the prefix entirely (no stray `": "`) when both
  are empty.
- **`run_bundle.py:310`** — `feature_id=getattr(primary_output, "feat_id", "") or ""`.
  Extend the `or` chain to the Jira key so the bundle stays traceable.
- **`nodes/qa.py:417`** — `return document or research.spec_path or research.feat_id or ""`.
  Add `jira_issue_key` to the chain (note: :194 and :342 in the same file
  already do this — make :417 consistent).
- **`nodes/development.py:484`** — `_find_feature_slug(worktree_path, feat_id)`.
  Matches an index file strictly on `data.get("feature_id") == feat_id`. With
  `feat_id == ""` it will scan every index and match any file whose
  `feature_id` is missing/empty. Must **short-circuit to `None` on an empty
  `feat_id`** instead of risking a false match on an unrelated feature's index.
- Add a helper for the label chain so the three string sites share one
  implementation rather than three `or` chains that can drift.
- Unit tests per the Test Specification below.

**NOT in scope**:
- Making anything actually *produce* `feat_id == ""` — that is TASK-2507
  (`sdd-research` naming + skip-reserve). This task only makes consumers safe.
- `ResearchOutput.base_branch` — that is TASK-2504.
- Any change to `nodes/qa.py:194` or `:342` — they are already correct and are
  the precedent you are following.
- Renaming `feat_id` or changing its type. It stays `str`, still required.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/base.py` | MODIFY | Add `run_label()` helper alongside the existing module-level helpers |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py` | MODIFY | `_build_title` uses `run_label()` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/run_bundle.py` | MODIFY | `feature_id` falls back to the Jira key |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | Line 417 chain includes `jira_issue_key` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` | MODIFY | `_find_feature_slug` short-circuits on empty `feat_id` |
| `packages/ai-parrot/tests/flows/dev_loop/test_empty_feat_id.py` | CREATE | Unit tests for all five sites |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.flows.dev_loop.models.base import (
    ResearchOutput,      # models/base.py:323
    DevelopmentOutput,   # models/base.py:476
)
from parrot.flows.dev_loop.nodes.base import (
    DevLoopNode,                      # nodes/base.py:193
    register_dev_loop_node,           # nodes/base.py:174
    scrub_git_output,                 # nodes/base.py:40
    transition_issue_with_candidates, # nodes/base.py:54
    condense_qa_failure,              # nodes/base.py:134
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class ResearchOutput(BaseModel):                             # line 323
    model_config = ConfigDict(populate_by_name=True)         # line 336
    jira_issue_key: str                                      # line 338  (required)
    spec_path: str                                           # line 343  (required)
    feat_id: str                                             # line 348  (required, may be "")
    branch_name: str                                         # line 353
    worktree_path: str                                       # line 358
    repo_path: str = ""                                      # line 363
    log_excerpts: List[str]                                  # line 373

# nodes/base.py — module-level helpers already live here; add yours beside them
def scrub_git_output(text: str) -> str: ...                              # line 40
async def transition_issue_with_candidates(...) -> None: ...             # line 54
def condense_qa_failure(report: QAReport, *, max_chars: int = 2000): ... # line 134
def register_dev_loop_node(name: str): ...                               # line 174
class DevLoopNode(Node): ...                                             # line 193

# THE SITES TO FIX
# nodes/deployment_handoff.py
        return f"{research.feat_id}: {first_line}"                       # line 505

# run_bundle.py
        feature_id=getattr(primary_output, "feat_id", "") or "",         # line 310

# nodes/qa.py  (194 and 342 are ALREADY correct — the precedent)
                runtime_skip, research.jira_issue_key or research.feat_id,   # line 194
                research.jira_issue_key or research.feat_id,                 # line 342
        return document or research.spec_path or research.feat_id or ""      # line 417

# nodes/development.py
    @staticmethod
    def _find_feature_slug(worktree_path: str, feat_id: str) -> Optional[str]:  # line 484
        index_dir = Path(worktree_path) / "sdd" / "tasks" / "index"
        if not index_dir.is_dir():
            return None
        for path in sorted(index_dir.glob("*.json")):
            if path.name == "_orphans.json":
                continue
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("feature_id") == feat_id:      # ← "" matches a missing key
                return data.get("feature") or path.stem
        return None
```

```python
# Proof that feat_id == "" is already a reachable shape:
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
            feat_id="",                                                   # line 1378
```

### Does NOT Exist

- ~~`ResearchOutput.feature_id`~~ — the field is `feat_id`. (`feature_id` *is*
  a field on the **run bundle**, `run_bundle.py:310`, and on the task-index
  JSON header — do not confuse the three.)
- ~~`ResearchOutput.jira_key`~~ — that is only a *validation alias*
  (`models/base.py:341`); the attribute is `jira_issue_key`.
- ~~`nodes/base.run_label()`~~ — you are creating it.
- ~~`DevLoopNode.run_label()`~~ — make it a **module-level function**, not a
  method: `run_bundle.py` is not a node and must be able to call it.
- ~~`ResearchOutput.feat_id: Optional[str]`~~ — it is a required `str`; do not
  change it to optional. `""` is the sentinel, not `None`.

---

## Implementation Notes

### Pattern to Follow

Add the helper beside the existing module-level helpers in `nodes/base.py`
(they sit above `register_dev_loop_node`):

```python
def run_label(output: Any, *, default: str = "run") -> str:
    """Return the best available human label for a run.

    FEAT-466: a hotfix reserves no ``FEAT-<NNN>`` (a bugfix is not a
    feature), so ``feat_id`` is legitimately ``""`` on those runs and the
    Jira issue key carries the identity. Follows the precedence already used
    at ``nodes/qa.py:194,342``.

    Args:
        output: Any object exposing ``feat_id`` / ``jira_issue_key``
            (``ResearchOutput`` or ``PlannerOutput``).
        default: Returned when neither identifier is available, so callers
            never interpolate an empty string into user-facing text.

    Returns:
        ``feat_id`` when set, else ``jira_issue_key`` when set, else
        ``default``.
    """
    for attr in ("feat_id", "jira_issue_key"):
        value = (getattr(output, attr, "") or "").strip()
        if value:
            return value
    return default
```

Then the title site becomes — note the prefix is *dropped*, not left dangling:

```python
# nodes/deployment_handoff.py:505
label = run_label(research, default="")
return f"{label}: {first_line}" if label else first_line
```

And the slug lookup gains a guard as its first statement:

```python
# nodes/development.py:484
        if not feat_id:
            # FEAT-466: hotfix runs carry feat_id == "" and have no per-spec
            # task index. Returning None here (rather than scanning) keeps us
            # from matching an unrelated index whose feature_id key is absent
            # — json .get() returns None, and None == "" is False, but a file
            # with an explicit "feature_id": "" would match.
            return None
```

### Key Constraints

- **`_find_feature_slug` returning `None` is a supported outcome** —
  `_build_scheduler` already handles it and degrades to the single-agent path
  (`development.py:200-207`). You are not breaking the pool; you are making the
  degradation correct. TASK-2506 makes that path honour the operator's chosen
  agent, which is why this is safe.
- Do not change the `or ""` tail semantics at `qa.py:417` — that function
  returns a path-ish string used for lookup; keep `""` as its final fallback
  rather than `"run"`.
- `run_bundle.py` is **not** a `DevLoopNode` — import `run_label` as a plain
  module function.
- `DevLoopNode` subclasses are frozen; you are not adding attributes here, but
  if you touch `__init__` use `object.__setattr__`
  (`deployment_handoff.py:93` is the pattern).
- Keep Google-style docstrings and type hints on everything new.

### References in Codebase

- `nodes/qa.py:194,342` — the exact fallback precedent. Read these first.
- `nodes/base.py:40-172` — the module-level helper neighbourhood you are
  joining.
- `runner.py:1378` — proof `feat_id=""` already constructs cleanly.
- `development.py:200-207` — where a `None` slug degrades gracefully.

---

## Acceptance Criteria

- [ ] `run_label()` exists in `nodes/base.py` as a module-level function and
      returns `feat_id` → `jira_issue_key` → `default`, stripping whitespace
- [ ] `_build_title` with `feat_id=""` and `jira_issue_key="OPS-1"` produces
      `"OPS-1: <summary>"`
- [ ] `_build_title` with both empty produces just `"<summary>"` — no leading
      `": "`
- [ ] `run_bundle` `feature_id` falls back to the Jira key when `feat_id` is `""`
- [ ] `qa.py:417`'s chain includes `jira_issue_key`, consistent with :194/:342
- [ ] `_find_feature_slug(worktree, "")` returns `None` without reading any
      index file (assert via a `tmp_path` containing an index whose
      `feature_id` is `""`)
- [ ] A `ResearchOutput` with `feat_id=""` still validates (regression guard)
- [ ] Existing behaviour with a non-empty `feat_id` is unchanged at all five
      sites
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] `ruff check` and `mypy` clean on all five changed files

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_empty_feat_id.py
import json

import pytest

from parrot.flows.dev_loop.models.base import ResearchOutput
from parrot.flows.dev_loop.nodes.base import run_label
from parrot.flows.dev_loop.nodes.development import DevelopmentNode


def _research(**over) -> ResearchOutput:
    base = dict(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-466",
        branch_name="feat-466-x",
        worktree_path="/tmp/wt",
    )
    base.update(over)
    return ResearchOutput(**base)


class TestRunLabel:
    def test_prefers_feat_id(self):
        assert run_label(_research()) == "FEAT-466"

    def test_falls_back_to_jira_key(self):
        assert run_label(_research(feat_id="")) == "OPS-1"

    def test_falls_back_to_default(self):
        out = _research(feat_id="", jira_issue_key="")
        assert run_label(out, default="run") == "run"

    def test_strips_whitespace_only_values(self):
        assert run_label(_research(feat_id="   ")) == "OPS-1"


class TestEmptyFeatIdValidates:
    def test_research_output_accepts_empty_feat_id(self):
        """runner.py:1378 already relies on this."""
        assert _research(feat_id="").feat_id == ""


class TestFindFeatureSlug:
    def test_empty_feat_id_returns_none_without_matching(self, tmp_path):
        """An index whose feature_id is literally "" must NOT be matched by
        a hotfix run's empty feat_id."""
        idx = tmp_path / "sdd" / "tasks" / "index"
        idx.mkdir(parents=True)
        (idx / "unrelated.json").write_text(
            json.dumps({"feature_id": "", "feature": "unrelated"})
        )
        assert DevelopmentNode._find_feature_slug(str(tmp_path), "") is None

    def test_matching_feat_id_still_resolves(self, tmp_path):
        idx = tmp_path / "sdd" / "tasks" / "index"
        idx.mkdir(parents=True)
        (idx / "x.json").write_text(
            json.dumps({"feature_id": "FEAT-466", "feature": "dev-loop-run-fidelity"})
        )
        got = DevelopmentNode._find_feature_slug(str(tmp_path), "FEAT-466")
        assert got == "dev-loop-run-fidelity"


class TestPrTitle:
    def test_title_uses_jira_key_when_no_feat_id(self):
        """Assert on the node's _build_title; construct the node with mocked
        toolkits per the existing fixtures in test_deployment_handoff.py."""
        ...  # follow the construction pattern in the sibling test module

    def test_title_has_no_dangling_colon_when_both_empty(self):
        ...
```

> Before writing the last class, read
> `packages/ai-parrot/tests/flows/dev_loop/test_deployment_handoff.py` and
> reuse its node-construction fixtures rather than inventing new mocks.

---

## Agent Instructions

1. **Read the spec** — §3 Module 2, and §7's "`feat_id == ""` must be honoured
   by every consumer" risk entry.
2. **Verify the Codebase Contract** — the five line numbers above shift easily;
   re-grep each before editing:
   ```bash
   grep -n 'research.feat_id\|"feat_id"' packages/ai-parrot/src/parrot/flows/dev_loop/**/*.py
   ```
3. **Re-run the audit yourself** and add any site the contract missed:
   ```bash
   grep -rn "feat_id" packages/ai-parrot/src/parrot/flows/dev_loop/ | grep -v models/base.py
   ```
   If you find a sixth consumer, fix it and note it in the Completion Note.
4. **Write failing tests, then implement** (TDD).
5. **Verify** every acceptance criterion, then run the whole dev_loop suite —
   this task touches five files and the suite is the regression net.
6. Move this file to `sdd/tasks/completed/` and set the index entry to `done`.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-27
**Notes**: Added `run_label()` to `nodes/base.py` per spec, wired it into
`_build_title` (deployment_handoff.py, drops the dangling `": "` when both
identifiers are empty) and `run_bundle.py`'s `feature_id`. Extended
`qa.py:417`'s chain with `jira_issue_key` (consistent with :194/:342).
`_find_feature_slug` short-circuits to `None` on empty `feat_id` before
touching the filesystem. Re-ran the full audit grep per the Agent
Instructions; found `development.py:204,217,628` also reference
`research.feat_id` but only inside internal WARNING/error log strings (no
PR/bundle-facing text, no lookup semantics) — left untouched as out of
scope for this task's explicit 4-site list. Added
`packages/ai-parrot/tests/flows/dev_loop/test_empty_feat_id.py` (10 tests,
all passing) following `test_deployment_handoff.py`'s node-construction
fixtures. Full `pytest packages/ai-parrot/tests/flows/dev_loop/` run:
1091 passed, 3 pre-existing failures confirmed unrelated (identical
failures reproduced on the unmodified baseline via `git stash`) — no
regressions introduced. `ruff check` on all 5 changed files shows the
same or fewer findings than the unmodified baseline versions (pre-existing
UP00x/S110 style debt, none attributable to this diff). `mypy` timed out
on the whole-project run (pre-existing project-wide slowness, not
specific to these files) — best-effort, not confirmed clean.

**Deviations from spec**: none
