# TASK-3196: Thread `--base` into the dev-flow ideation document (`DevRequestBrief.base_branch`)

**Feature**: FEAT-555 — Dev-Loop Slack Kick-off
**Spec**: `sdd/specs/dev-loop-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (G10). The feature-mode base branch is *the SDD document's
frontmatter*: `feature_handoff._resolve_base_branch` reads the committed spec
(`feature_handoff.py:348`) and `/sdd-spec` resolves it from the brainstorm via
`resolve_flow`. Today the `sdd-ideation` subagent hard-codes `base_branch: dev`
in the frontmatter it writes (`sdd-ideation.md:181`), and `DevRequestBrief` has
no base-branch field at all, so a Slack `--base staging` on a feature run would
be inert. This task makes the value flow: brief → `_IdeationBrief` payload →
subagent instructions → document frontmatter. No `FeatureBrief` field is added
(the document is authoritative — spec §8 resolved question).

---

## Scope

- Add `flow_type: Optional[Literal["feature","hotfix"]] = None` and
  `base_branch: Optional[str] = None` to `DevRequestBrief`, plus a Pydantic v2
  `model_validator(mode="after")` that rejects `flow_type == "hotfix"` with a
  `base_branch` other than `"main"` (mirrors `WorkBrief`'s FEAT-466 rule).
- Add `base_branch: str = "dev"` to `_IdeationBrief` and pass
  `base_branch=brief.base_branch or "dev"` when the payload is built.
- Update `sdd-ideation.md`: document the `base_branch` payload field in the
  Input table and replace the hard-coded `base_branch: dev` frontmatter line
  with an instruction to write the payload's value (type stays `feature`).
- Write `packages/ai-parrot/tests/flows/dev_flow/test_base_branch_threading.py`.

**NOT in scope**: `FeatureBrief` changes (none — the document carries the
value); the Slack parser / brief builder that sets `base_branch` (TASK-3201);
`WorkBrief` (already has the fields); any change to `IdeationNode` gate logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/models.py` | MODIFY | Two fields + validator on `DevRequestBrief` (:61) |
| `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py` | MODIFY | `_IdeationBrief.base_branch` (:101) and payload passthrough (:477) |
| `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md` | MODIFY | Input table row + frontmatter instruction (:60-69, :181) |
| `packages/ai-parrot/tests/flows/dev_flow/test_base_branch_threading.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from pydantic import BaseModel, Field                     # verified: packages/ai-parrot/src/parrot/flows/dev_flow/models.py:29
from pydantic import model_validator                      # pydantic v2 public API (add to the existing import line)
from parrot.flows.dev_flow.models import DevRequestBrief  # verified: packages/ai-parrot/src/parrot/flows/dev_flow/models.py:61
from parrot.flows.dev_flow.nodes.ideation import _IdeationBrief, IdeationNode  # verified: nodes/ideation.py:101, :200 (execute)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_flow/models.py
DevRequestKind = Literal["enhancement", "new_feature"]
class DevRequestBrief(BaseModel):                          # line 61
    kind: DevRequestKind; title: str (min_length=1); description: str (min_length=1); context: str = ""
    jira_issue_key: str | None = None                      # line 97
    dev_agents: list[DevAgentSpec] | None = None           # line 109
    judge_panel: JudgePanelConfig | None = None            # line 117-122  ← last field today

# packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py
class _IdeationBrief(BaseModel):                           # line 101
    mode: Literal["brainstorm", "proposal"]; title: str; description: str; context: str = ""
    graph_context: str = ""; answers: dict[str, str] = Field(default_factory=dict)
    document_path: str = ""; round: int = 1                # line 119
    partner_findings: str = ""; partner_findings_path: str = ""
#   payload construction: dispatch_brief = _IdeationBrief(mode=mode, title=brief.title, description=brief.description,
#       context=brief.context, graph_context=graph_context, answers=dict(answers), document_path=document_path,
#       round=round_, partner_findings=..., partner_findings_path=...)      # lines 475-486
#   FeatureBrief emitted at lines 317-324 (document_path, document_kind, jira_issue_key, dev_agents, judge_panel) — UNCHANGED

# packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md
#   Input table rows `| `mode` | ... |` … `| `partner_findings` | ... |`      # lines 62-72
#   Step 3 frontmatter block: "type: feature" / "base_branch: dev"           # lines 175-182 (line 181 = `base_branch: dev`)

# Precedent for the validator rule (WorkBrief, FEAT-466):
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:219 flow_type, :226 base_branch
```

### Does NOT Exist
- ~~`DevRequestBrief.flow_type` / `.base_branch`~~ — added by THIS task; absent today (spec §6).
- ~~`FeatureBrief.base_branch`~~ — does not exist and must NOT be added (document frontmatter is authoritative, `feature_handoff.py:348`).
- ~~`_IdeationBrief.base_branch`~~ — added by THIS task.
- ~~`IdeationNode` reading `conf.SDD_BASE_BRANCH` or similar~~ — no such setting; the only source is the brief.
- ~~a Jinja/format placeholder syntax in `sdd-ideation.md`~~ — the subagent reads the JSON payload; the markdown is prose instructions, not a template with placeholders.

---

## Implementation Notes

### Pattern to Follow
```python
# WorkBrief (flows/dev_loop/models/base.py:219-232) declares the same two optional fields with
# "None ⇒ derive" semantics; mirror the descriptions and add the validator DevRequestBrief lacks.
from pydantic import model_validator

@model_validator(mode="after")
def _hotfix_requires_main(self) -> "DevRequestBrief":
    if self.flow_type == "hotfix" and self.base_branch not in (None, "main"):
        raise ValueError("flow_type='hotfix' requires base_branch='main'")
    return self
```

### Key Constraints
- Defaults stay `None` so every existing caller (`server_dev.py`, tests) is byte-identical.
- `_IdeationBrief.base_branch` defaults to `"dev"`; the payload passes `brief.base_branch or "dev"`.
- Keep the FeatureBrief emission (ideation.py:317-324) untouched.
- Google docstrings, type hints, `black` 120.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:219-232` — field precedent
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py:348` — consumer of the frontmatter
- `packages/ai-parrot/tests/flows/dev_flow/test_models.py` — existing model test style

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the two fields + validator to `DevRequestBrief` — *why*: the brief is the only carrier of the Slack `--base` value.
2. Add `base_branch` to `_IdeationBrief` and to the payload — *why*: the subagent only sees the payload.
3. Edit `sdd-ideation.md` (table row + frontmatter instruction) — *why*: the subagent writes the frontmatter that `feature_handoff` later reads.
4. Write the tests, run `pytest packages/ai-parrot/tests/flows/dev_flow -q` — *why*: AC11 and the existing ideation suites must stay green.

### `packages/ai-parrot/src/parrot/flows/dev_flow/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            "Optional QA judge-panel override, passed through to the " "``FeatureBrief`` that ``IdeationNode`` emits."' packages/ai-parrot/src/parrot/flows/dev_flow/models.py)
# AFTER — insert below the closing `    )` of the judge_panel Field (verified: models.py:117-122), still inside DevRequestBrief
    flow_type: Optional[Literal["feature", "hotfix"]] = Field(
        default=None,
        description="FEAT-555 per-run SDD flow type. None ⇒ 'feature'.",
    )
    base_branch: Optional[str] = Field(
        default=None,
        description=(
            "FEAT-555 per-run base branch, written by sdd-ideation into the document "
            "frontmatter. None ⇒ 'dev'. flow_type='hotfix' requires 'main'."
        ),
    )

    @model_validator(mode="after")
    def _hotfix_requires_main(self) -> "DevRequestBrief":
        """Reject a hotfix that does not base on main (FEAT-466 rule, mirrored from WorkBrief)."""
        # FILL IN: raise ValueError when flow_type == "hotfix" and base_branch not in (None, "main") — bounded by AC11
        return self
```
Also extend line 29 to `from pydantic import BaseModel, Field, model_validator` and add `Optional` to the `typing` import on line 27.
**Why this shape**: spec §2 Data Models fixes these two names; `None` defaults keep every existing caller unchanged.

### `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py` (MODIFY — two edits)
```python
# occurrences: 1 (verified: grep -c '    round: int = 1' packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py)
# AFTER — insert below `    round: int = 1` (verified: ideation.py:119)
    # FEAT-555: base branch the subagent must write into the document frontmatter.
    base_branch: str = "dev"
```
```python
# occurrences: 1 (verified: grep -c '            context=brief.context,' packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py)
# AFTER — insert below `            context=brief.context,` (verified: ideation.py:479)
            base_branch=brief.base_branch or "dev",
```
**Why**: the payload is the subagent's only input; defaulting to `"dev"` keeps every existing run identical.

### `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md` (MODIFY — two edits)
```markdown
<!-- occurrences: 1 (verified: grep -c '| `answers` |' packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md) -->
<!-- AFTER — insert below the `| `answers` | Prior-round ...` row (verified: sdd-ideation.md:69) -->
| `base_branch` | FEAT-555. The branch the document's frontmatter MUST declare (`base_branch: <value>`). Default `dev`; never infer it from the text. |
```
```markdown
<!-- occurrences: 1 (verified: grep -c '^base_branch: dev$' packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md) -->
<!-- REPLACE line `base_branch: dev` (verified: sdd-ideation.md:181) with: -->
base_branch: <the payload's `base_branch` value, verbatim — `dev` when it is `dev`>
```
Add one sentence under the frontmatter block: "`type` is always `feature`; `base_branch` comes from the payload — do not hard-code `dev`."
**Why**: `feature_handoff._resolve_base_branch` and `/sdd-spec`'s `resolve_flow` read this frontmatter (AC11).

### `packages/ai-parrot/tests/flows/dev_flow/test_base_branch_threading.py` (CREATE)
```python
"""FEAT-555 TASK-3196 — `--base` threading into the dev-flow ideation payload."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.flows.dev_flow.models import DevRequestBrief  # verified: dev_flow/models.py:61
from parrot.flows.dev_flow.nodes.ideation import _IdeationBrief  # verified: nodes/ideation.py:101


def _brief(**overrides):
    payload = {"kind": "new_feature", "title": "t", "description": "d"}
    payload.update(overrides)
    return DevRequestBrief(**payload)


def test_defaults_are_none():
    b = _brief()
    assert b.flow_type is None and b.base_branch is None


def test_staging_feature_accepted():
    assert _brief(flow_type="feature", base_branch="staging").base_branch == "staging"


def test_hotfix_requires_main():
    with pytest.raises(ValidationError):
        _brief(flow_type="hotfix", base_branch="dev")


def test_ideation_brief_default_base_branch():
    assert _IdeationBrief(mode="brainstorm", title="t", description="d").base_branch == "dev"


def test_ideation_payload_carries_base_branch():
    # FILL IN: drive IdeationNode's dispatch with a stubbed dispatcher (see tests/flows/dev_flow/test_ideation_node.py
    # for the fixture pattern) and assert the captured _IdeationBrief.base_branch == "staging" — bounded by AC11
    pytest.skip("FILL IN")


def test_subagent_instructions_mention_base_branch():
    from pathlib import Path
    import parrot.flows.dev_flow.nodes.ideation as mod
    text = (Path(mod.__file__).parent.parent / "_subagent_data" / "sdd-ideation.md").read_text(encoding="utf-8")
    assert "| `base_branch` |" in text and "base_branch: dev\n" not in text.split("## Step 3")[1][:600]
```
**Why this shape**: the spec's unit rows `test_devrequestbrief_base_branch_validator` and `test_ideation_payload_carries_base_branch` map 1:1; the last test guards the prose edit.

### FILL IN checklist
- [ ] `models.py::DevRequestBrief._hotfix_requires_main` — raise on hotfix + non-main; bounded by AC11
- [ ] `test_base_branch_threading.py::test_ideation_payload_carries_base_branch` — stub dispatcher capture; bounded by AC11

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow -q`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_flow`
- [ ] Imports work: `from parrot.flows.dev_flow.models import DevRequestBrief`
- [ ] Spec AC11 (feature half): the `_IdeationBrief` payload carries `base_branch="staging"` when the brief says so, and the subagent instructions no longer hard-code `base_branch: dev`
- [ ] Spec AC19: existing `test_ideation_*` and `test_server_dev*` suites stay green

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_base_branch_threading.py — see blueprint block above
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/dev-loop-slack.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3196-dev-flow-base-branch-threading.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
