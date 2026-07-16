---
type: Wiki Overview
title: 'TASK-1751: Semantic UI Model (Pydantic contract)'
id: doc:sdd-tasks-completed-task-1751-semantic-ui-model-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 1** of FEAT-303 (spec §3). The Semantic UI Model is the
relates_to:
- concept: mod:parrot.integrations.msagentsdk.semantic
  rel: mentions
---

# TASK-1751: Semantic UI Model (Pydantic contract)

**Feature**: FEAT-303 — UX for Custom Engine Copilot Agents (Semantic UI Model → Adaptive Cards)
**Spec**: `sdd/specs/ux-custom-engine-copilot.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of FEAT-303 (spec §3). The Semantic UI Model is the
channel-neutral, card-oriented contract that domain agents return as explicit
structured output. Every downstream task (renderer, bridge, invoke shim)
depends on this contract. It must be importable WITHOUT `microsoft_agents.*`
installed — it is pure Pydantic, no SDK imports.

---

## Scope

- Implement `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/semantic.py`
  with the models from spec §2 "Data Models":
  - `UIAction` — `title: str`, `prompt_template: Optional[str]`,
    `params: dict[str, Any]` (default `{}`), `url: Optional[str]`.
    A model validator enforces **exactly one** of `prompt_template` / `url`.
  - `UIField` — `label: str`, `value: str`.
  - `UIMetric` — `label: str`, `value: str`, `delta: Optional[str]`.
  - `TablePayload` — `result_type: Literal["table"]`, `columns: list[str]`,
    `rows: list[list[str]]`, `total_rows: Optional[int]`.
  - `MetricsPayload` — `result_type: Literal["metrics"]`, `metrics: list[UIMetric]`.
  - `DetailPayload` — `result_type: Literal["detail"]`, `fields: list[UIField]`.
  - `StatusPayload` — `result_type: Literal["status"]`,
    `level: Literal["success", "warning", "error", "info"]`, `message: str`,
    `details: Optional[str]`.
  - `SemanticUIResult` — `title: str`, `summary: Optional[str]`,
    `payload: Union[TablePayload, MetricsPayload, DetailPayload, StatusPayload]`
    with `Field(discriminator="result_type")`, `actions: list[UIAction]`
    (default `[]`).
- Google-style docstrings on every model — they are the developer-facing
  contract documentation for agent authors.
- Write unit tests in
  `packages/ai-parrot-integrations/tests/unit/test_msagent_semantic.py`.

**NOT in scope**: card rendering (TASK-1752), bridge wiring / lazy exports
(TASK-1753), invoke handling (TASK-1754). Do NOT modify `__init__.py`,
`agent.py`, or `models.py` in this task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/semantic.py` | CREATE | Semantic UI Model (Pydantic) |
| `packages/ai-parrot-integrations/tests/unit/test_msagent_semantic.py` | CREATE | Unit tests for model validation |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, class names, and method signatures.
> Do NOT invent, guess, or assume anything not listed here. Verified 2026-07-14
> against `dev` @ 16b30ee1a.

### Verified Imports
```python
from __future__ import annotations
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field, model_validator
# pydantic v2 is an existing core dependency; model_validator(mode="after") is available.
# This module must import NOTHING from microsoft_agents.* and NOTHING from
# parrot.* runtime modules (keep it dependency-free so import isolation holds).
```

### Existing Signatures to Use
```python
# Sibling module layout (this task ADDS semantic.py next to these):
# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/
#   __init__.py   (lazy exports — DO NOT TOUCH in this task; TASK-1753 owns it)
#   agent.py      (bridge — untouched here)
#   models.py     (MSAgentSDKConfig — untouched here)

# Discriminated-union pattern (pydantic v2), as specified in spec §2:
#   payload: Union[TablePayload, MetricsPayload, DetailPayload, StatusPayload] = \
#       Field(discriminator="result_type")
```

### Does NOT Exist
- ~~`parrot/integrations/msagentsdk/semantic.py`~~ — YOU are creating it; it
  does not exist yet, nothing imports it.
- ~~`OutputMode.ADAPTIVE_CARD`~~ — no such enum member; do not add one.
- ~~a `SemanticUIModel` class~~ — the class name is `SemanticUIResult`
  (per spec); do not introduce alternate names.
- ~~`packages/ai-parrot-integrations/tests/integrations/msagentsdk/`~~ — no
  such test directory; msagentsdk tests live flat in `tests/unit/` with the
  `test_msagent_*.py` prefix (see `test_msagent_cards.py`,
  `test_msagent_resume.py`).

---

## Implementation Notes

### Pattern to Follow
```python
# UIAction XOR validation (pydantic v2):
@model_validator(mode="after")
def _prompt_xor_url(self) -> "UIAction":
    if bool(self.prompt_template) == bool(self.url):
        raise ValueError("UIAction requires exactly one of prompt_template or url")
    return self
```

### Key Constraints
- Pure data module: no I/O, no logging, no async, no SDK imports.
- Strict type hints; Google-style docstrings on every public model.
- `SemanticUIResult` must round-trip `model_dump()` / `model_validate()`
  (needed later by the bridge and tests).
- Unknown `result_type` values must FAIL validation (discriminated union does
  this by construction — do not add a permissive fallback).

### References in Codebase
- `packages/ai-parrot/src/parrot/outputs/a2ui/models.py` — style reference for
  Pydantic contract modules with validators (do NOT import from it).
- `packages/ai-parrot-integrations/tests/unit/test_msagent_cards.py` — test
  file naming/layout convention for this package.

---

## Acceptance Criteria

- [ ] All models implemented per scope with docstrings and strict type hints
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/unit/test_msagent_semantic.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/semantic.py`
- [ ] Direct import works without the MS SDK installed:
  `python -c "from parrot.integrations.msagentsdk.semantic import SemanticUIResult"`
  succeeds even when `microsoft_agents` is not importable
- [ ] `semantic.py` contains no `microsoft_agents` or `navconfig` imports

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/unit/test_msagent_semantic.py
import pytest
from pydantic import ValidationError

from parrot.integrations.msagentsdk.semantic import (
    DetailPayload, MetricsPayload, SemanticUIResult, StatusPayload,
    TablePayload, UIAction, UIField, UIMetric,
)


class TestPayloadValidation:
    def test_table_payload_valid(self):
        r = SemanticUIResult(
            title="Orders",
            payload=TablePayload(result_type="table", columns=["id", "total"],
                                 rows=[["1", "$10"]], total_rows=1),
        )
        assert r.payload.result_type == "table"

    def test_metrics_detail_status_valid(self):
        ...  # analogous constructions for the other three payloads

    def test_unknown_result_type_rejected(self):
        with pytest.raises(ValidationError):
            SemanticUIResult.model_validate(
                {"title": "x", "payload": {"result_type": "chart", "data": []}}
            )

    def test_discriminator_routes_from_dict(self):
        r = SemanticUIResult.model_validate(
            {"title": "s", "payload": {"result_type": "status",
                                       "level": "error", "message": "boom"}}
        )
        assert isinstance(r.payload, StatusPayload)


class TestUIAction:
    def test_prompt_action_valid(self):
        UIAction(title="Details", prompt_template="Show details for {id}",
                 params={"id": "42"})

    def test_url_action_valid(self):
        UIAction(title="Open", url="https://example.com")

    def test_both_rejected(self):
        with pytest.raises(ValidationError):
            UIAction(title="x", prompt_template="p", url="https://e.com")

    def test_neither_rejected(self):
        with pytest.raises(ValidationError):
            UIAction(title="x")


def test_roundtrip_model_dump_validate():
    r = SemanticUIResult(title="t", payload=DetailPayload(
        result_type="detail", fields=[UIField(label="a", value="b")]))
    assert SemanticUIResult.model_validate(r.model_dump()) == r
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/ux-custom-engine-copilot.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1751-semantic-ui-model.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-14
**Notes**: Implemented all 8 models exactly per spec §2 in
`semantic.py` (UIAction with prompt-xor-url validator, UIField, UIMetric,
TablePayload, MetricsPayload, DetailPayload, StatusPayload,
SemanticUIResult with discriminated union). 9/9 unit tests pass; ruff
clean; zero `microsoft_agents`/`navconfig` imports confirmed via grep.
Direct `python -c` import from an arbitrary cwd resolves to the main
repo's editable install (shared `.venv` across worktrees) rather than
this worktree's copy — a pre-existing environment characteristic of the
worktree workflow, not a code defect. Verified SDK-independence instead
via `pytest` (which correctly resolves the worktree's `src/` first) and
via an explicit `PYTHONPATH` prefix; both confirm the module imports
cleanly with no `microsoft_agents.*` dependency.

**Deviations from spec**: none
