# TASK-4575: FirefliesInsightsAgent integration tests: isolation and confirmation flow

**Feature**: FEAT-715 — FirefliesInsightsAgent
**Spec**: `sdd/specs/fireflies-insights-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4574
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests, agent rows, and design-research **S10**. Unit tests pin each
method; this module proves the **cross-path guarantees** that no unit test can:
ingestion and insights are independent (G6, AC9), and the full report → confirm → ticket
→ replay flow behaves (AC12/AC13/AC23). Everything external is stubbed: **no network, no
real LLM** (never a `real_llm` test — it would be excluded from the Validation Contract).

---

## Scope

- Create `packages/ai-parrot/tests/bots/test_fireflies_insights_integration.py` with fixtures: a stub MCP (`_call_fireflies_tool` returning canned
  listing / transcript / summary results), a stub `_llm` whose `invoke` returns an object
  with `.output = MeetingInsights(...)`, a recording Telegram bot behind a stub wrapper,
  and a recording Jira toolkit.
- Cases:
  1. **AC9 (insights survive ingest failure)** — `_drop_to_inbox` raises; insights are still
     sent; `report.errors` names the meeting.
     → FILL IN: *note* — with TASK-4571's structure the insight step runs only after a
     successful drop. If that holds, this case must assert the **spec-level** guarantee
     instead: the failed meeting is reported and the *next* meeting's insights are still
     sent. Record whichever behaviour the code has in the Completion Note — do not change
     production code in this task.
  2. **AC9 (ingest survives insight failure)** — `invoke` raises; the file is in the inbox;
     `report.dropped_to_inbox == 1`.
  3. **AC12/AC13** — report, confirm via `/fireflies_ticket <id>` inside
     `telegram_chat_scope(channel)`, confirm again → one Jira call, same key twice.
  4. **AC23** — confirm from another chat → refused, no Jira call.
  5. **AC10** — a 10 000-char transcript producing many action items → every sent chunk ≤ 4096.

**NOT in scope**: any production-code change. A failure here is a bug in an earlier task:
report it, do not patch around it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/bots/test_fireflies_insights_integration.py` | CREATE | End-to-end agent run with stubbed MCP / LLM / Telegram / Jira |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.fireflies_insights import FirefliesInsightsAgent, MeetingInsights, ActionItem  # TASK-4569/4570
from parrot.integrations.telegram.context import telegram_chat_scope                           # telegram/context.py:20
```

### Does NOT Exist
- ~~a shared Fireflies MCP fake fixture~~ — write one here.
- ~~`pytest.mark.real_llm` usage in this file~~ — forbidden.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/bots/test_fireflies_insights_integration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Build the fixtures — *why*: one place to stub every external system.
2. Write the five cases — *why*: G6 and the confirmation protocol end to end.

### `packages/ai-parrot/tests/bots/test_fireflies_insights_integration.py` (CREATE)
```python
"""Integration: FirefliesInsightsAgent end to end with every external system stubbed (FEAT-715)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from parrot.bots.fireflies_insights import ActionItem, FirefliesInsightsAgent, MeetingInsights
from parrot.integrations.telegram.context import telegram_chat_scope


class RecordingBot:
    def __init__(self) -> None:
        self.sent: list[dict] = []
    async def send_message(self, **kwargs) -> None:
        self.sent.append(kwargs)


class RecordingJira:
    def __init__(self) -> None:
        self.calls: list[dict] = []
    async def jira_create_issue(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {"ok": True, "id": "1", "key": "NAV-1", "issue": {}}


@pytest.fixture
def agent(tmp_path, monkeypatch) -> FirefliesInsightsAgent:
    # FILL IN: construct (FirefliesInsightsAgent.__new__ + required attributes, or the real
    #   constructor with Agent.configure/post_configure patched), set inbox_dir=tmp_path/"inbox",
    #   public_channel_id="-100", _wrapper=SimpleNamespace(bot=RecordingBot()),
    #   jira_toolkit=RecordingJira(), working_memory=None, a stub registry (available=False),
    #   FIREFLIES_REGISTRY_DIR -> tmp_path, _ensure_fireflies_mcp -> no-op, and a stub
    #   _call_fireflies_tool + _llm.invoke returning SimpleNamespace(output=MeetingInsights(...))
    raise NotImplementedError
```
> FILL IN: the five case bodies from Scope.

### FILL IN checklist
- [ ] `agent` fixture.
- [ ] five cases; case 1 per its note.

---

## Acceptance Criteria

- [ ] All five cases pass with no network and no real LLM.
- [ ] Case 1's recorded behaviour is written in the Completion Note.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/bots/test_fireflies_insights_integration.py -q`

---

## Test Specification

See the CREATE block and the Scope case list.

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
   `feat(fireflies-insights-agent): TASK-4575 — <title>`.
9. **Close** with `scripts/sdd/close_task.sh TASK-4575 fireflies-insights-agent verified` — never move
   the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (manual — attempt 3 after mistral timeout + glm max_turns)
**Date**: 2026-10-22
**Notes**: Created test_fireflies_insights_integration.py with 5 cases: (1) AC9 insights
survive drop failure — confirmed TASK-4571 structure: when _drop_to_inbox fails, that
meeting is skipped entirely (insights never generated for it); the NEXT meeting's insights
still send. (2) AC9 ingest survives insight failure — file stays in inbox. (3) AC12/AC13
report+confirm+replay — one Jira call, same key. (4) AC23 foreign chat refused — 0 Jira
calls. (5) AC10 long transcript — all chunks <= 4096. All external systems stubbed
(MCP, LLM, Telegram, Jira). No real_llm marker.

**Case 1 recorded behaviour**: with TASK-4571's sync_meetings structure, _drop_to_inbox
runs before generate_insights. A drop failure skips that meeting (continue), so insights
are never attempted for it. The spec-level guarantee holds: a failed meeting is reported
in errors and the next meeting's insights are still sent.

**Deviations from spec**: none
