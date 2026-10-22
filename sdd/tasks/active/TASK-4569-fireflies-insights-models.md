# TASK-4569: FirefliesInsightsAgent data contracts

**Feature**: FEAT-715 — FirefliesInsightsAgent
**Spec**: `sdd/specs/fireflies-insights-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 4** and §2 Data Models. Creates `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` with **only** the Pydantic
contracts both paths share; the agent class is added by TASK-4570 onward, in the same
file. It folds design-research **S2** (`FirefliesMeeting`: `sync_fireflies_transcripts`
returns a report dict, not the raw inputs) and **S8** (`PendingApproval`).

**Two additive fields beyond spec §2**, decided at task time: `FirefliesMeeting` also
carries `duration_minutes` and `summary_fingerprint`, because
`MeetingRegistry.record_synced(...)` (meeting_registry.py:430) requires both as keyword
arguments. Nothing in §2 is removed or renamed.

---

## Scope

- Create `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` containing `ChatId`, `FirefliesMeeting`, `ActionItem`,
  `MeetingInsights`, `PendingApproval`, `InsightRunReport` exactly as below.
- Create `packages/ai-parrot/tests/bots/test_fireflies_insights.py` with the tests below.

**NOT in scope**: the agent class, any import of `Agent`, MCP, Telegram, Jira or the
wiki — all TASK-4570+.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` | CREATE | Data contracts shared by both paths (models only) |
| `packages/ai-parrot/tests/bots/test_fireflies_insights.py` | CREATE | Model validation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field   # repo standard, Pydantic v2
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/agents/meeting_registry.py:430 — why the two extra fields exist
async def record_synced(self, *, fireflies_id: str, note_path: Path, title: str, meeting_date: str,
                        participants: list[str], duration_minutes: float, fingerprint: str,
                        summary_fingerprint: str | None, reset_analysis: bool) -> MeetingRecord: ...
```

### Does NOT Exist
- ~~`from parrot.bots.github_reviewer import ChatId`~~ — it is a module-local alias
  (github_reviewer.py:88); redefine it, do not import it.
- ~~`parrot.bots.fireflies_insights`~~ — this task creates it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/fireflies_insights.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_fireflies_insights.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Delegation Contract

```json
{
  "schema_version": 1,
  "task_id": "TASK-4569",
  "spec_path": "sdd/specs/fireflies-insights-agent.spec.md",
  "design_complete": true,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/fireflies_insights.py",
      "action": "create",
      "expected_sha256": null,
      "planned_changes": "New module holding the FEAT-715 data contracts",
      "blocks": [
        "impl-models"
      ]
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_fireflies_insights.py",
      "action": "create",
      "expected_sha256": null,
      "planned_changes": "New unit tests for the data contracts",
      "blocks": [
        "impl-model-tests"
      ]
    }
  ],
  "references": [],
  "implementation_blocks": [
    "impl-models",
    "impl-model-tests"
  ],
  "acceptance_criteria": [
    "pytest packages/ai-parrot/tests/bots/test_fireflies_insights.py passes"
  ],
  "validation_commands": [
    [
      "pytest",
      "packages/ai-parrot/tests/bots/test_fireflies_insights.py",
      "-q"
    ]
  ]
}
```

```python id=impl-models path=packages/ai-parrot/src/parrot/bots/fireflies_insights.py
"""FirefliesInsightsAgent — Fireflies meetings to wiki inbox, insights, Telegram and Jira (FEAT-715).

This module starts with the data contracts shared by the ingestion path and the
insight path. The agent class is added by later tasks of the same feature.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

#: Telegram chat identifier. GitHubReviewer defines the same alias locally
#: (bots/github_reviewer.py:88); it is not importable from a shared module.
ChatId = int | str


class FirefliesMeeting(BaseModel):
    """One meeting's raw inputs, carried by both the ingestion and the insight paths.

    ``sync_fireflies_transcripts`` returns a report dict rather than these fields,
    so the agent owns its own fetch and builds this model from it.
    """

    fireflies_id: str
    title: str
    meeting_date: str
    transcript: str
    summary: str = ""
    participants: list[str] = Field(default_factory=list)
    duration_minutes: float = 0.0
    fingerprint: str
    summary_fingerprint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionItem(BaseModel):
    """One actionable commitment extracted from a meeting."""

    title: str
    owner: str | None = None
    due_date: str | None = None
    evidence: str


class MeetingInsights(BaseModel):
    """Structured insight set for one meeting; the LLM ``output_type``."""

    meeting_id: str
    meeting_title: str
    meeting_date: str
    decisions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)


class PendingApproval(BaseModel):
    """One outstanding Telegram confirmation for turning an action item into a ticket.

    ``telegram_command`` only attaches slash-command metadata and carries no
    approval state, so this feature owns the protocol explicitly.
    """

    insight_id: str
    fireflies_id: str
    action_index: int
    chat_id: str
    user_id: str | None = None
    expires_at: str
    created_ticket: str | None = None


class InsightRunReport(BaseModel):
    """Outcome of one agent run; never raised into a scheduler."""

    fetched: int = 0
    skipped: int = 0
    dropped_to_inbox: int = 0
    insights_sent: int = 0
    errors: list[str] = Field(default_factory=list)
```

```python id=impl-model-tests path=packages/ai-parrot/tests/bots/test_fireflies_insights.py
"""Unit tests for the FEAT-715 FirefliesInsightsAgent data contracts."""

import pytest
from pydantic import ValidationError

from parrot.bots.fireflies_insights import (
    ActionItem,
    FirefliesMeeting,
    InsightRunReport,
    MeetingInsights,
    PendingApproval,
)


def test_meeting_requires_fingerprint() -> None:
    with pytest.raises(ValidationError):
        FirefliesMeeting(fireflies_id="m1", title="Sync", meeting_date="2026-10-22", transcript="hi")


def test_meeting_defaults_are_independent() -> None:
    a = FirefliesMeeting(fireflies_id="a", title="A", meeting_date="2026-10-22", transcript="x", fingerprint="f")
    b = FirefliesMeeting(fireflies_id="b", title="B", meeting_date="2026-10-22", transcript="y", fingerprint="g")
    a.participants.append("ana@example.test")
    assert b.participants == []
    assert a.summary == ""
    assert a.summary_fingerprint is None


def test_insights_round_trip() -> None:
    item = ActionItem(title="Ship it", owner="Ana", due_date="2026-11-01", evidence="Ana: I'll ship it")
    insights = MeetingInsights(
        meeting_id="m1",
        meeting_title="Sync",
        meeting_date="2026-10-22",
        decisions=["Go"],
        risks=["Late"],
        action_items=[item],
    )
    restored = MeetingInsights.model_validate_json(insights.model_dump_json())
    assert restored == insights


def test_action_item_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        ActionItem(title="No evidence")


def test_pending_approval_ticket_marker_defaults_empty() -> None:
    approval = PendingApproval(
        insight_id="i1", fireflies_id="m1", action_index=0, chat_id="-100", expires_at="2026-10-23T00:00:00+00:00"
    )
    assert approval.created_ticket is None
    assert approval.user_id is None


def test_run_report_starts_at_zero() -> None:
    report = InsightRunReport()
    assert (report.fetched, report.skipped, report.dropped_to_inbox, report.insights_sent) == (0, 0, 0, 0)
    assert report.errors == []
```

---

## Implementation Notes

### Key Constraints
- Do not import anything beyond `typing` and `pydantic` in this task — later tasks add
  the agent imports, and an early heavy import would slow every test of this file.

---

## Implementation Blueprint

### Steps (in order)
1. Write `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` from block `impl-models` verbatim — *why*: the design is complete and
   every later task imports these exact names.
2. Write `packages/ai-parrot/tests/bots/test_fireflies_insights.py` from block `impl-model-tests` verbatim — *why*: pins the contracts.
3. Run the Validation Command.

### `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` (CREATE)
Use the `impl-models` block above verbatim.
**Why this shape**: §2 Data Models plus the two `record_synced`-driven fields; names
are fixed for TASK-4570..4575.

### `packages/ai-parrot/tests/bots/test_fireflies_insights.py` (CREATE)
Use the `impl-model-tests` block above verbatim.

### FILL IN checklist
- [ ] none — this task is fully specified.

---

## Acceptance Criteria

- [ ] `from parrot.bots.fireflies_insights import FirefliesMeeting, ActionItem, MeetingInsights, PendingApproval, InsightRunReport` works.
- [ ] `pytest packages/ai-parrot/tests/bots/test_fireflies_insights.py -q` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/fireflies_insights.py packages/ai-parrot/tests/bots/test_fireflies_insights.py` is clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/bots/test_fireflies_insights.py -q`

---

## Test Specification

See block `impl-model-tests` above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug fireflies-insights-agent --feature-id FEAT-715`).
2. **Read the spec** `sdd/specs/fireflies-insights-agent.spec.md` — §3 (the module this task implements) and §6.
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/fireflies-insights-agent.json`.
4. **Verify the Codebase Contract** before writing code. Anchors were verified at
   `f6a4dbfca`; re-run every `grep -c` in the blueprint and use the fresh count.
   A count of `0` means the anchor moved — stop and report, never invent one.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
   marker; never change a signature, class name or path the blueprint fixes.
7. **Run** the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
   (plus `packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src`
   when the task imports them) — the shared venv is installed against the main
   checkout. Then `ruff check --fix` on every file you touched.
8. **Commit** only the files this task lists (never `git add .` / `-A`):
   `feat(fireflies-insights-agent): TASK-4569 — <title>`.
9. **Close** with `scripts/sdd/close_task.sh TASK-4569 fireflies-insights-agent verified` — never move
   the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
