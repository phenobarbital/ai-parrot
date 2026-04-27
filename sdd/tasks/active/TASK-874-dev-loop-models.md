# TASK-874: Pydantic v2 contracts for `parrot.flows.dev_loop`

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** (`parrot.flows.dev_loop.models`) from the spec.

Every other dev-loop module — dispatcher, nodes, flow factory, streaming
multiplexer — imports its data structures from this module. It is the
foundational task with zero internal dependencies, so it MUST land first
and be parallel-safe with TASK-875 (FEAT-124 extension), TASK-876
(settings) and TASK-877 (subagents).

Spec sections: §2 "Data Models" (full code listing) and §6 "Codebase
Contract".

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/__init__.py` (new namespace
  package — see "Does NOT Exist" below).
- Create `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py`.
- Implement `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` with
  ALL the Pydantic v2 contracts listed in spec §2:
  - `LogSource`
  - `_AcceptanceCriterionBase`, `FlowtaskCriterion`, `ShellCriterion`,
    and the `AcceptanceCriterion = Annotated[Union[...],
    Field(discriminator="kind")]` discriminated union
  - `BugBrief`
  - `ResearchOutput`
  - `DevelopmentOutput`
  - `CriterionResult`
  - `QAReport`
  - `ClaudeCodeDispatchProfile`
  - `DispatchEvent`
- Re-export every symbol from `parrot.flows.dev_loop.__init__` so
  callers can `from parrot.flows.dev_loop import BugBrief` without
  reaching into `models`.
- Write the unit tests this module owns (see Test Specification).

**NOT in scope**:
- The dispatcher class (TASK-878).
- Any node implementation.
- Settings additions (TASK-876).
- The `agents` / `setting_sources` extension on
  `ClaudeAgentRunOptions` (TASK-875).
- Re-exporting models from `parrot/__init__.py` — they live under their
  package path only.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/__init__.py` | CREATE | Empty namespace marker. One-line docstring is enough. |
| `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` | CREATE | Re-exports models for ergonomic imports. |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` | CREATE | All Pydantic v2 contracts. |
| `packages/ai-parrot/tests/flows/__init__.py` | CREATE | Test namespace. |
| `packages/ai-parrot/tests/flows/dev_loop/__init__.py` | CREATE | Test namespace. |
| `packages/ai-parrot/tests/flows/dev_loop/test_models.py` | CREATE | Unit tests for the contracts. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Stdlib
from typing import Annotated, Any, Dict, List, Literal, Optional, Type, Union

# Pydantic v2 — already a hard dependency of ai-parrot
from pydantic import BaseModel, Field
```

### Existing Signatures to Use

```python
# pydantic v2 idioms used by this task — verified against pydantic>=2.0
# - Annotated[Union[A, B], Field(discriminator="kind")] is the v2-native way
#   to declare a tagged union over Pydantic models.
# - Each variant declares `kind: Literal["..."] = "..."` so model_validate()
#   dispatches on the literal value.
# - Field(min_length=...) on List[...] applies as `min_length` (NOT v1 `min_items`).
```

### Does NOT Exist

- ~~`parrot.flows`~~ — package does NOT exist yet. This task creates it as
  a brand-new sibling under `parrot/`. (Resolved open question:
  `parrot/flows/dev_loop/` placement is approved.)
- ~~`parrot.bots.flow.dev_loop`~~ — alternative placement was rejected;
  do NOT create the package there.
- ~~`AcceptanceCriterion.kind == "regex_match"` / `"output_match"` /
  `"http_check"` / `"pytest"`~~ — v1 ONLY implements `flowtask` and
  `shell`. Other kinds are extensible later but MUST NOT be added here.
- ~~`pydantic.v1.*`~~ — do NOT import from the v1 compat shim.
  `from pydantic import BaseModel, Field` resolves to v2.
- ~~`Field(..., min_items=1)`~~ — v1 syntax. v2 uses `min_length=1` even
  for List fields.

---

## Implementation Notes

### Pattern to Follow

Verbatim copy from spec §2 "Data Models" (lines ~196-312). The spec is
the source of truth for field names, types, and defaults. Do not rename
fields or change defaults without flagging in the Completion Note.

### Key Constraints

- **Pydantic v2 only**. Use `Annotated`, `Field(discriminator=...)`,
  `model_validate`, `model_validate_json`, `model_dump`. Do NOT call
  `.dict()` or `.parse_obj()` (v1 names).
- **Discriminated union must use `Annotated[Union[...], Field(...)]`**
  at the type-alias level — not a `model_config` hack inside a wrapping
  class. The field on `BugBrief` is then typed
  `acceptance_criteria: List[AcceptanceCriterion]`.
- **Keep the file dependency-free**: only `pydantic` and `typing`. No
  imports from `parrot.*` and especially no top-level imports from
  `claude_agent_sdk.*` (per spec §7 R1).
- **Defaults**:
  - `_AcceptanceCriterionBase.timeout_seconds=300`, `expected_exit_code=0`
  - `ClaudeCodeDispatchProfile.subagent="sdd-worker"`,
    `permission_mode="default"`,
    `setting_sources=["project"]`, `timeout_seconds=1800`,
    `model="claude-sonnet-4-6"`
- **`DispatchEvent.kind`** is the literal union of these eight strings
  (use them verbatim — the dispatcher and the multiplexer match on
  them):
  `"dispatch.queued"`, `"dispatch.started"`, `"dispatch.message"`,
  `"dispatch.tool_use"`, `"dispatch.tool_result"`,
  `"dispatch.output_invalid"`, `"dispatch.failed"`, `"dispatch.completed"`.

### Re-exports in `__init__.py`

```python
from parrot.flows.dev_loop.models import (
    LogSource,
    FlowtaskCriterion, ShellCriterion, AcceptanceCriterion,
    BugBrief,
    ResearchOutput, DevelopmentOutput,
    CriterionResult, QAReport,
    ClaudeCodeDispatchProfile, DispatchEvent,
)

__all__ = [
    "LogSource",
    "FlowtaskCriterion", "ShellCriterion", "AcceptanceCriterion",
    "BugBrief",
    "ResearchOutput", "DevelopmentOutput",
    "CriterionResult", "QAReport",
    "ClaudeCodeDispatchProfile", "DispatchEvent",
]
```

### References in Codebase

- `packages/ai-parrot/src/parrot/auth/permission.py` (or any
  `pydantic.BaseModel` subclass already in the repo) for v2 style.

---

## Acceptance Criteria

- [ ] `parrot/flows/__init__.py` exists.
- [ ] `parrot/flows/dev_loop/__init__.py` exists and re-exports every
  public symbol listed under "Re-exports in `__init__.py`".
- [ ] `parrot/flows/dev_loop/models.py` defines all 11 contracts named
  in scope.
- [ ] `BugBrief(acceptance_criteria=[])` raises `pydantic.ValidationError`
  (driven by `min_length=1`).
- [ ] `BugBrief.model_validate({...,"acceptance_criteria":[
  {"kind":"flowtask","name":"x","task_path":"a.yaml"}]})` returns a
  `FlowtaskCriterion` (discriminator works).
- [ ] `from parrot.flows.dev_loop import BugBrief, ClaudeCodeDispatchProfile,
  DispatchEvent` succeeds without any `claude_agent_sdk` import side-effects
  (test by `python -c "import parrot.flows.dev_loop"` in a fresh venv
  where `claude-agent-sdk` is NOT installed — note this for the reviewer).
- [ ] All tests in `tests/flows/dev_loop/test_models.py` pass:
  `pytest packages/ai-parrot/tests/flows/dev_loop/test_models.py -v`.
- [ ] No linting errors in the new files:
  `ruff check packages/ai-parrot/src/parrot/flows/`.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_models.py
import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop import (
    AcceptanceCriterion,
    BugBrief, ClaudeCodeDispatchProfile, DispatchEvent,
    FlowtaskCriterion, LogSource, ShellCriterion,
)


class TestBugBrief:
    def test_bug_brief_rejects_empty_criteria(self):
        with pytest.raises(ValidationError):
            BugBrief(
                summary="x" * 20,
                affected_component="etl/customers/sync.yaml",
                log_sources=[],
                acceptance_criteria=[],
                escalation_assignee="557058:abc",
                reporter="557058:def",
            )

    def test_bug_brief_accepts_valid_payload(self):
        brief = BugBrief(
            summary="customer sync drops the last row",
            affected_component="etl/customers/sync.yaml",
            log_sources=[LogSource(kind="cloudwatch", locator="/etl/x")],
            acceptance_criteria=[
                FlowtaskCriterion(name="run", task_path="etl/customers/sync.yaml"),
            ],
            escalation_assignee="557058:abc",
            reporter="557058:def",
        )
        assert brief.acceptance_criteria[0].kind == "flowtask"


class TestDiscriminatedUnion:
    def test_round_trip_flowtask(self):
        brief = BugBrief.model_validate(
            {
                "summary": "x" * 20,
                "affected_component": "etl/customers/sync.yaml",
                "log_sources": [],
                "acceptance_criteria": [
                    {"kind": "flowtask", "name": "x",
                     "task_path": "etl/customers/sync.yaml"},
                ],
                "escalation_assignee": "a",
                "reporter": "b",
            }
        )
        criterion = brief.acceptance_criteria[0]
        assert isinstance(criterion, FlowtaskCriterion)
        assert criterion.task_path == "etl/customers/sync.yaml"

    def test_round_trip_shell(self):
        brief = BugBrief.model_validate(
            {
                "summary": "x" * 20,
                "affected_component": "etl/customers/sync.yaml",
                "log_sources": [],
                "acceptance_criteria": [
                    {"kind": "shell", "name": "lint",
                     "command": "ruff check ."},
                ],
                "escalation_assignee": "a",
                "reporter": "b",
            }
        )
        assert isinstance(brief.acceptance_criteria[0], ShellCriterion)


class TestDispatchProfile:
    def test_defaults(self):
        profile = ClaudeCodeDispatchProfile()
        assert profile.subagent == "sdd-worker"
        assert profile.permission_mode == "default"
        assert profile.setting_sources == ["project"]
        assert profile.model == "claude-sonnet-4-6"
        assert profile.timeout_seconds == 1800

    def test_generic_session_when_subagent_none(self):
        profile = ClaudeCodeDispatchProfile(
            subagent=None, system_prompt_override="be terse"
        )
        assert profile.subagent is None
        assert profile.system_prompt_override == "be terse"


class TestDispatchEvent:
    @pytest.mark.parametrize(
        "kind",
        [
            "dispatch.queued", "dispatch.started",
            "dispatch.message", "dispatch.tool_use", "dispatch.tool_result",
            "dispatch.output_invalid", "dispatch.failed", "dispatch.completed",
        ],
    )
    def test_kind_literal_round_trip(self, kind):
        ev = DispatchEvent(kind=kind, ts=0.0, run_id="r", node_id="n",
                           payload={})
        assert ev.kind == kind

    def test_invalid_kind_rejected(self):
        with pytest.raises(ValidationError):
            DispatchEvent(kind="dispatch.bogus", ts=0.0, run_id="r",
                          node_id="n", payload={})
```

---

## Agent Instructions

When you pick up this task:

1. Read spec §2 (Data Models) verbatim — copy field names and defaults.
2. Verify the Codebase Contract: `pydantic` v2 is in `pyproject.toml`,
   no `parrot.flows` package exists yet.
3. Update `sdd/tasks/.index.json` → `"in-progress"` with your session ID.
4. Implement; run `pytest packages/ai-parrot/tests/flows/dev_loop/test_models.py -v`.
5. `ruff check packages/ai-parrot/src/parrot/flows/`.
6. Move this file to `sdd/tasks/completed/TASK-874-dev-loop-models.md`.
7. Update index → `"done"`. Fill in Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
