# TASK-2504: Record the resolved base branch on `ResearchOutput`

**Feature**: FEAT-466 — Dev-Loop Run Fidelity
**Spec**: `sdd/specs/dev-loop-run-fidelity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2502
**Assigned-to**: unassigned

---

## Context

Implements **spec Module 4** — the "record it" half of the feature's central
idea (*resolve once, record it, read the record*).

`ResearchOutput` is the payload that carries a run from the research phase to
development, QA, and handoff. It records `branch_name`, `worktree_path`,
`spec_path`, `feat_id`, `repo_path` — **but not the branch the branch was cut
from.** So when `DeploymentHandoffNode` needs a PR base, it has nothing to read
and guesses from `brief.kind` instead (`deployment_handoff.py:132-133`). That
guess is the third and final link in the FEAT-466 failure chain, and PR #1250
is what it produced: branch cut from `dev`, PR opened against `main`, 93
commits of `dev` merged into the release branch.

This task closes the information gap. After it lands, TASK-2505 can delete the
guess.

**The critical design constraint** — and the reason this is not a one-line
model change: the value must be **derived in Python from the committed spec
frontmatter**, not taken from the subagent's self-reported JSON. The
`sdd-research` subagent is an LLM; `ResearchOutput` already carries five
validation aliases specifically because subagents drift on field names
(`models/base.py:329-333`). A base branch that the flow trusts blindly is a
base branch the flow cannot rely on. The spec file is on disk, committed, and
parseable — read that.

---

## Scope

- Add `base_branch: str = ""` to `ResearchOutput` with
  `validation_alias=AliasChoices("base_branch", "base")`, matching the
  aliasing style already used on every other field in that model.
- In `ResearchNode.execute()`, **after** the dispatch returns and after the
  existing `jira_issue_key` backfill (`nodes/research.py:380-386`), resolve the
  base branch deterministically and stamp it onto `research_out` via
  `model_copy(update=...)` — the same mechanism the node already uses twice
  (`research.py:384`, `research.py:416`).
- Resolution order for the stamp:
  1. Parse the committed spec at `research_out.spec_path` with
     `sdd_meta.resolve_flow(doc_path=...)` (TASK-2502) — **authoritative**.
  2. If the spec file cannot be found or parsed, fall back to
     `resolve_flow(kind=brief.kind)` and log at WARNING that the spec was
     unreadable.
  3. Never leave it as the subagent's self-reported value. If the subagent
     supplied one that disagrees with the spec, log both at WARNING and keep
     the spec's.
- Resolve `spec_path` relative to the worktree when it is not absolute —
  the field's own docstring says "Path to the spec, inside the worktree"
  (`models/base.py:345`), so a bare `sdd/specs/x.spec.md` must be joined
  against `research_out.worktree_path`.
- Unit tests per the Test Specification below.

**NOT in scope**:
- Consuming `base_branch` in the handoff nodes, or the sibling-overlap guard —
  that is TASK-2505.
- Changing how the worktree is *created* (i.e. which ref it branches from) —
  that is TASK-2507's `sdd-research.md` change.
- Adding `flow_type` / `base_branch` to `WorkBrief` for the console override —
  that is TASK-2508.
- `PlannerOutput` (feature-mode's equivalent). TASK-2505 handles
  `FeatureHandoffNode`'s side; if it needs a field there, that task adds it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` | MODIFY | Add `ResearchOutput.base_branch` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` | MODIFY | Deterministic read-back + stamp in `execute()` |
| `packages/ai-parrot/tests/flows/dev_loop/test_research_base_branch.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pydantic import BaseModel, ConfigDict, Field, AliasChoices
# already imported in models/base.py — confirm with:
#   grep -n "^from pydantic" packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py

from scripts.sdd.sdd_meta import resolve_flow   # created by TASK-2502
from parrot.flows.dev_loop.models.base import ResearchOutput, BugBrief, WorkBrief
```

> **Import caution**: `scripts/` is not part of the installed `parrot` package.
> Verify that `scripts.sdd.sdd_meta` is importable from inside
> `parrot.flows.dev_loop.nodes.research` in this repo layout before relying on
> it:
> ```bash
> python -c "from scripts.sdd.sdd_meta import parse; print('importable')"
> ```
> If it is NOT importable from an installed context, do **not** add a `sys.path`
> hack. Instead read the frontmatter locally with a small private helper in
> `research.py` (the format is a leading `---` block; `yaml.safe_load` on the
> middle segment — mirror `sdd_meta.parse()`'s 6-line body at
> `scripts/sdd/sdd_meta.py:66-76`) and note the decision in the Completion Note.
> Resolving this cleanly is part of the task.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class ResearchOutput(BaseModel):                                        # line 323
    """The model accepts a small set of common aliases under
    populate_by_name=True so subagent outputs that drift on field names
    (jira_key, feature_id, branch, worktree) still validate."""         # 329-333
    model_config = ConfigDict(populate_by_name=True)                    # line 336
    jira_issue_key: str = Field(
        ..., validation_alias=AliasChoices(
            "jira_issue_key", "jira_key", "issue_key", "ticket_key"))   # line 338-342
    spec_path: str = Field(
        ..., description="Path to the spec, inside the worktree.",
        validation_alias=AliasChoices("spec_path", "spec"))             # line 343-347
    feat_id: str = Field(...)                                           # line 348
    branch_name: str = Field(...)                                       # line 353
    worktree_path: str = Field(...)                                     # line 358
    repo_path: str = Field(default="", ...)                             # line 363
    log_excerpts: List[str] = Field(default_factory=list)               # line 373

# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
WorkKind = Literal["bug", "enhancement", "new_feature"]                 # line 116
class WorkBrief(BaseModel): ...                                         # line 138
    kind: WorkKind = Field(default="bug", ...)                          # line 151
BugBrief = WorkBrief                                                    # line 223

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py
    async def execute(self, ctx, deps=None, **kwargs) -> ResearchOutput:  # line 207
        shared = self.shared_state(ctx)
        brief: BugBrief = shared["bug_brief"]
        ...
        research_out: ResearchOutput = await self._dispatcher.dispatch(...)
        # 5. If the subagent left jira_issue_key blank, inject ours.
        if not research_out.jira_issue_key:                               # line 382
            research_out = research_out.model_copy(
                update={"jira_issue_key": issue_key})                     # line 384  ← STAMP PATTERN
        ...
        research_out = research_out.model_copy(
            update={"repo_path": repo_path})                              # line 416  ← STAMP PATTERN
        shared["research_output"] = research_out
        return research_out

# scripts/sdd/sdd_meta.py
def parse(doc_path: Path) -> FlowMeta: ...        # line 45 — RAISES FileNotFoundError if absent
class FlowMeta(BaseModel):                        # line 29
    type: Literal["feature", "hotfix"]            # line 32
    base_branch: str                              # line 33
```

### Does NOT Exist

- ~~`ResearchOutput.base_branch`~~ — you are creating it. Verified absent:
  `grep -rn "base_branch" .../dev_loop/models/base.py` → no matches.
- ~~`ResearchOutput.flow_type`~~ — not part of this task. Only `base_branch` is
  needed downstream; the type is derivable from it and adding both invites drift.
- ~~`ResearchNode._resolve_base_branch()`~~ — you are creating it.
- ~~`sdd_meta.parse()` returning a default for a missing file~~ — it raises
  `FileNotFoundError` (`sdd_meta.py:66`). Use TASK-2502's `resolve_flow()`,
  which handles absence, or guard the call yourself.
- ~~`ResearchOutput` being mutable~~ — it is a plain pydantic `BaseModel`;
  the node's established idiom is `model_copy(update={...})`, not attribute
  assignment. Follow it.

---

## Implementation Notes

### Pattern to Follow — the model field

Match the surrounding field style exactly:

```python
    base_branch: str = Field(
        default="",
        description=(
            "Branch this run's branch was cut from, resolved deterministically "
            "by ResearchNode from the COMMITTED spec frontmatter — never from "
            "the subagent's self-report. '' means unresolved; handoff nodes "
            "must block rather than guess a default (FEAT-466)."
        ),
        validation_alias=AliasChoices("base_branch", "base"),
    )
```

### Pattern to Follow — the stamp

Add a private helper, then one `model_copy` beside the two that already exist:

```python
    def _resolve_base_branch(
        self, research_out: ResearchOutput, brief: WorkBrief
    ) -> str:
        """Resolve the run's base branch from the committed spec.

        The spec file on disk is authoritative: it was written and committed
        by /sdd-spec, whereas anything on ``research_out`` was produced by an
        LLM and may have drifted. When the spec cannot be read we fall back to
        the work-kind mapping and say so loudly, because a wrong base branch
        is what FEAT-466 exists to prevent.

        Args:
            research_out: The validated dispatch output (for ``spec_path`` and
                ``worktree_path``).
            brief: This run's brief, for the ``kind`` fallback.

        Returns:
            The resolved base branch name; never ``""``.
        """
        spec_path = Path(research_out.spec_path)
        if not spec_path.is_absolute():
            spec_path = Path(research_out.worktree_path) / spec_path

        try:
            meta = resolve_flow(doc_path=spec_path, kind=getattr(brief, "kind", None))
        except (OSError, ValueError) as exc:
            self.logger.warning(
                "Could not resolve flow metadata from spec %s (%s); "
                "falling back to the kind mapping for kind=%r.",
                spec_path, exc, getattr(brief, "kind", None),
            )
            meta = resolve_flow(kind=getattr(brief, "kind", None))

        reported = (research_out.base_branch or "").strip()
        if reported and reported != meta.base_branch:
            self.logger.warning(
                "sdd-research reported base_branch=%r but the committed spec "
                "%s resolves to %r; using the spec's value.",
                reported, spec_path, meta.base_branch,
            )
        return meta.base_branch
```

Then, immediately after the `repo_path` stamp at `research.py:416`:

```python
        research_out = research_out.model_copy(
            update={"base_branch": self._resolve_base_branch(research_out, brief)}
        )
```

### Key Constraints

- **The spec wins, always.** There is an explicit test for the case where the
  subagent reports `dev` and the spec says `main`. Do not add a code path where
  the subagent's value survives.
- **Never leave `base_branch == ""` on a successful run.** `""` is reserved to
  mean "nothing resolved it", which TASK-2505 treats as a blocking condition.
  Your fallback chain must always produce a real branch name.
- Stamp **after** the dispatch, not before — the spec does not exist until the
  subagent has run `/sdd-spec`.
- Use `self.logger` (never `print`); `DevLoopNode` provides it.
- Adding a defaulted field is backward compatible; every existing
  `ResearchOutput(...)` construction (including `runner.py:1378`) keeps working.
  Confirm with the full suite.

### References in Codebase

- `nodes/research.py:380-386` and `:414-418` — the two `model_copy` stamps you
  are joining. Copy their comment style.
- `models/base.py:329-333` — the docstring explaining *why* subagent output is
  not trusted. This task is that principle applied to a new field.
- `scripts/sdd/sdd_meta.py:66-76` — `parse()`'s body, in case you need to
  inline a local frontmatter reader (see the Import caution above).

---

## Acceptance Criteria

- [ ] `ResearchOutput.base_branch` exists, defaults to `""`, and accepts
      `{"base": "main"}` via its alias
- [ ] Every existing `ResearchOutput(...)` construction still validates
      (`runner.py:1378` included) — full dev_loop suite green
- [ ] After `ResearchNode.execute()`, `research_output.base_branch` equals the
      value in the committed spec's frontmatter
- [ ] When the subagent reports a *different* base branch than the spec, the
      spec's value wins **and** a WARNING is logged naming both
- [ ] A relative `spec_path` is resolved against `worktree_path`
- [ ] An unreadable/absent spec falls back to the kind mapping
      (`bug` → `main`) and logs a WARNING — it does **not** raise
- [ ] `base_branch` is never `""` after a successful `execute()`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] `ruff check` and `mypy` clean on both changed files

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_research_base_branch.py
import pytest

from parrot.flows.dev_loop.models.base import ResearchOutput


def _spec(tmp_path, *, type_="hotfix", base="main"):
    d = tmp_path / "sdd" / "specs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "x.spec.md"
    p.write_text(f"---\ntype: {type_}\nbase_branch: {base}\n---\n# Spec\n")
    return p


class TestModelField:
    def test_defaults_to_empty(self):
        out = ResearchOutput(
            jira_issue_key="OPS-1", spec_path="sdd/specs/x.spec.md",
            feat_id="FEAT-466", branch_name="b", worktree_path="/tmp/wt",
        )
        assert out.base_branch == ""

    def test_accepts_base_alias(self):
        out = ResearchOutput(
            jira_issue_key="OPS-1", spec_path="s", feat_id="F",
            branch_name="b", worktree_path="/w", base="main",
        )
        assert out.base_branch == "main"


class TestResolveBaseBranch:
    """Construct ResearchNode with the mocked toolkits/dispatcher used by the
    existing suite — read tests/flows/dev_loop/test_research_node.py and reuse
    its fixtures rather than writing new mocks."""

    async def test_spec_frontmatter_is_authoritative(self, tmp_path):
        """Spec says hotfix/main; subagent claims dev. Spec must win."""
        _spec(tmp_path, type_="hotfix", base="main")
        # dispatcher returns ResearchOutput(..., base_branch="dev")
        # assert shared["research_output"].base_branch == "main"
        ...

    async def test_warns_on_disagreement(self, tmp_path, caplog):
        ...

    async def test_relative_spec_path_resolved_against_worktree(self, tmp_path):
        ...

    async def test_missing_spec_falls_back_to_kind_mapping(self, tmp_path, caplog):
        """No spec file at all -> kind='bug' -> 'main', with a WARNING."""
        ...

    async def test_never_empty_after_execute(self, tmp_path):
        ...
```

---

## Agent Instructions

1. **Check your dependency**: TASK-2502 must be in `sdd/tasks/completed/` and
   `resolve_flow` importable. If not, stop and report.
2. **Read the spec** — §2 Overview (the "resolve once, record it, read the
   record" framing), §3 Module 4, §6.
3. **Settle the `scripts.sdd` import question FIRST** (see Import caution). It
   determines the shape of the rest of your work; do not discover it late.
4. **Verify the Codebase Contract** — re-read `research.py:375-420` and confirm
   the two `model_copy` sites and their line numbers.
5. **Write failing tests, then implement** (TDD). Reuse the existing
   `test_research_node.py` fixtures.
6. **Verify** every acceptance criterion, then the full dev_loop suite.
7. Move this file to `sdd/tasks/completed/` and set the index entry to `done`.
   Record the `scripts.sdd` import decision in the Completion Note — TASK-2505
   and TASK-2507 need to know what you chose.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
