# TASK-1918: Feature-mode models — FeatureBrief, judge panel, planner/synthesis/feedback contracts

**Feature**: FEAT-378 — DevLoop Enhancement — Feature-Mode Topology
**Spec**: `sdd/specs/devloop-enhancement.spec.md`
**Status**: done
**Completed**: 2026-07-27
**Verification**: verified
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (models half). Every other FEAT-378 task consumes these
Pydantic contracts: the document-based `FeatureBrief` (discriminated union
with `WorkBrief`), the judge-panel config, and the output models for the four
new nodes. This is the root of the dependency graph — nothing else can start
until these exist.

---

## Scope

- Implement in `parrot/flows/dev_loop/models.py`:
  - `FeatureBrief` (`kind: Literal["feature"]`, `document_path`,
    `document_kind: Literal["brainstorm","proposal","spec"]`,
    `jira_issue_key: Optional[str]`, `dev_agents: Optional[List[DevAgentSpec]]`,
    `judge_panel: Optional[JudgePanelConfig]`) — see spec §2 Data Models.
  - `JudgeSpec` (`agent: DevAgentBackend`, `model: str = ""`).
  - `JudgePanelConfig` (`judges: List[JudgeSpec]` min_length=1,
    `decision: Literal["majority"] = "majority"`) + a module-level
    `default_judge_panel()` helper returning the resolved default 3-judge
    panel (claude-code/claude-sonnet-4-6, codex/gpt-5.5, gemini/"").
  - `PlannerOutput`, `SynthesisReport`, `FeedbackDecision` per spec §2.
  - `Brief` discriminated union of `WorkBrief | FeatureBrief` on `kind`.
- Extend `ClaudeCodeDispatchProfile.subagent` Literal (models.py:527) with
  `"sdd-planner"` and `"sdd-feedback"`.
- Validators: `FeatureBrief.document_path` must exist and be a readable file
  (fail fast at model construction, per spec §7 "Nonexistent/unreadable
  document"); `document_kind` must match the file suffix convention when the
  filename ends in `.brainstorm.md` / `.proposal.md` / `.spec.md` (warn-level
  log, not hard fail, on mismatch).
- Write unit tests (`tests/flows/dev_loop/test_feature_models.py`).

**NOT in scope**: CLI loader changes (TASK-1926), any node, dispatcher, or
topology code, session-state actions (TASK-1919), conf.py keys.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` | MODIFY | New models + union + Literal extension |
| `packages/ai-parrot/tests/flows/dev_loop/test_feature_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models import (   # verified 2026-07-27
    WorkBrief, DevAgentSpec, DevAgentPoolConfig,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models.py  (verified 2026-07-27)
WorkKind = Literal["bug", "enhancement", "new_feature"]        # :116
class WorkBrief(BaseModel):                                     # :138
    kind: WorkKind = "bug"                                      # :151  ⚠ defaulted discriminator
    acceptance_criteria: List[AcceptanceCriterion]              # :180 (min_length=1)
    dev_agents: Optional[List[DevAgentSpec]]                    # :200
    dev_isolation: Optional[Literal["shared", "isolated"]]      # :210
DevAgentBackend = Literal["claude-code","codex","gemini","nvidia","grok","zai","moonshot"]  # :372
class DevAgentSpec(BaseModel):        # :377 — agent, model="", count=1
class DevAgentPoolConfig(BaseModel):  # :396 — agents (min 1), isolation_mode="shared"
class ClaudeCodeDispatchProfile(BaseModel):  # :519
    subagent: Optional[Literal["sdd-research","sdd-worker","sdd-qa","sdd-codereview"]] = "sdd-worker"  # :527
```

### Does NOT Exist
- ~~`FeatureBrief`, `JudgeSpec`, `JudgePanelConfig`, `PlannerOutput`, `SynthesisReport`, `FeedbackDecision`, `Brief`~~ — this task creates them.
- ~~`sdd-secondopinion` in `ClaudeCodeDispatchProfile.subagent`~~ — it is Codex-only (models.py:557, :884). Do NOT add it to the Claude Literal.
- ~~`WorkKind` value `"feature"`~~ — do NOT extend `WorkKind`; `FeatureBrief` carries its own `kind: Literal["feature"]`.

---

## Implementation Notes

### Pattern to Follow
Follow the existing model style in `models.py` (Pydantic v2, `Field(...,
description=...)`, Google-style docstrings). Place the new models in a
clearly-commented "FEAT-378 feature-mode" block after the existing brief
models.

### Key Constraints
- **Discriminated-union gotcha (spec §7)**: `WorkBrief.kind` has default
  `"bug"` and is a 3-value Literal, not a single tag. Pydantic v2
  `Field(discriminator="kind")` requires each member to have a Literal
  discriminator — a multi-value Literal on `WorkBrief` is accepted, but
  verify with a test that a dict WITHOUT `kind` still parses as `WorkBrief`
  when loaded via the union. If the defaulted discriminator breaks
  `TypeAdapter(Brief)`, implement `parse_brief(data: dict) -> WorkBrief |
  FeatureBrief` as a loader shim (kind == "feature" → FeatureBrief, else
  WorkBrief) and export THAT as the union entry point — document the choice.
- Zero behavior change for `WorkBrief`: do not touch its fields/validators.
- `FeatureBrief` must NOT require `acceptance_criteria` or `log_sources`.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` — host module
- Spec §2 Data Models — authoritative field list

---

## Acceptance Criteria

- [ ] All new models importable: `from parrot.flows.dev_loop.models import FeatureBrief, JudgeSpec, JudgePanelConfig, PlannerOutput, SynthesisReport, FeedbackDecision`
- [ ] Union/loader: dict with `kind: feature` → `FeatureBrief`; dicts with `kind` bug/enhancement/new_feature AND with no `kind` at all → `WorkBrief` (zero behavior change)
- [ ] `FeatureBrief` with missing/unreadable `document_path` raises `ValidationError`
- [ ] `ClaudeCodeDispatchProfile.subagent` accepts `"sdd-planner"` and `"sdd-feedback"`
- [ ] `default_judge_panel()` returns the 3-judge default from spec §2
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_feature_models.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/models.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_feature_models.py
import pytest
from pydantic import ValidationError


def test_feature_brief_valid(tmp_path):
    doc = tmp_path / "x.proposal.md"; doc.write_text("# p")
    from parrot.flows.dev_loop.models import FeatureBrief
    fb = FeatureBrief(document_path=str(doc), document_kind="proposal")
    assert fb.kind == "feature" and fb.jira_issue_key is None

def test_feature_brief_missing_document():
    from parrot.flows.dev_loop.models import FeatureBrief
    with pytest.raises(ValidationError):
        FeatureBrief(document_path="/nope/missing.md", document_kind="spec")

def test_union_routes_by_kind(tmp_path):
    doc = tmp_path / "x.spec.md"; doc.write_text("# s")
    from parrot.flows.dev_loop.models import FeatureBrief, WorkBrief, parse_brief
    assert isinstance(parse_brief({"kind": "feature", "document_path": str(doc),
                                   "document_kind": "spec"}), FeatureBrief)
    wb = parse_brief({"kind": "bug", "title": "t", "description": "d",
                      "acceptance_criteria": [...]})  # complete per WorkBrief fields
    assert isinstance(wb, WorkBrief)

def test_union_default_kind_is_workbrief():
    """Dict without kind still parses as WorkBrief (zero behavior change)."""

def test_judge_panel_defaults():
    from parrot.flows.dev_loop.models import default_judge_panel
    panel = default_judge_panel()
    assert len(panel.judges) == 3 and panel.decision == "majority"
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/devloop-enhancement.spec.md` (§2 Data Models, §6, §7)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — line numbers above verified 2026-07-27; re-grep before editing (FEAT-377 may have merged and shifted lines — its TASK-1912 adds `DevAgentSpec.escalation_model`, TASK-1910 adds `QAReport.attempt`)
4. **Update status** in `sdd/tasks/index/devloop-enhancement.json` → `"in-progress"`
5. **Implement**, **verify criteria**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-27
**Notes**: `FeatureBrief`, `JudgeSpec`, `JudgePanelConfig`, `default_judge_panel()`,
`PlannerOutput`, `SynthesisReport`, `FeedbackDecision` implemented in
`models.py` per spec §2. `ClaudeCodeDispatchProfile.subagent` extended with
`"sdd-planner"` and `"sdd-feedback"`. Discriminated-union gotcha handled via
the `parse_brief()` loader shim (documented inline) rather than a bare
`TypeAdapter(Brief)`, per the task's own guidance — `Brief` union is still
exported for typing purposes. All 13 unit tests in
`test_feature_models.py` pass; `ruff check` clean.

**Deviations from spec**: none
