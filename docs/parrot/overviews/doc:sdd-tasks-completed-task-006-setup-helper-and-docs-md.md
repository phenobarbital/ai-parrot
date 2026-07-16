---
type: Wiki Overview
title: 'TASK-006: setup_teams_hitl boot helper, per-agent override & docs'
id: doc:sdd-tasks-completed-task-006-setup-helper-and-docs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 5 (wiring + override + docs). Provides the one-call boot helper
relates_to:
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.channels.teams
  rel: mentions
- concept: mod:parrot.human.manager
  rel: mentions
---

# TASK-006: setup_teams_hitl boot helper, per-agent override & docs

**Feature**: FEAT-205 — TeamsHumanChannel
**Spec**: `sdd/specs/hitl-teams-channel.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-005
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (wiring + override + docs). Provides the one-call boot helper
that constructs the shared HITL bot, registers it as the `"teams"` channel on
the default `HumanInteractionManager`, and scaffolds the per-agent `BotConfig`
override (OQ-9). Adds end-to-end integration tests and the usage/migration doc.

---

## Scope

- Implement `async def setup_teams_hitl(app, manager, config: TeamsHitlConfig) -> TeamsHumanChannel`:
  - build adapter (TASK-001), GraphClient (TASK-002), Redis stores (TASK-004),
    `TeamsHumanChannel` (TASK-005);
  - register the `/api/messages`-style webhook route on the aiohttp `app`;
  - `manager.register_channel("teams", channel)` (or `set_default_human_manager`
    wiring when no manager is passed);
  - analogous to `set_default_human_manager` / existing setup helpers.
- `TeamsHitlConfig` Pydantic model sourced from navconfig (`MSTEAMS_HITL_APP_ID/PASSWORD`,
  `MSTEAMS_TENANT_ID`, Graph creds, Redis URL, `convref_ttl`).
- **Per-agent override scaffolding (OQ-9 / OQ-9-impl)**: allow an agent to
  present a distinct HITL identity via its own `BotConfig`, exposed as keyed
  channels (`"teams"` default + optional keyed entries). Decide & document the
  selection mechanism (keyed channels vs BotConfig at construction).
- Integration tests covering the dispatch loop and escalate routing.
- Usage/migration doc under `docs/`.

**NOT in scope**: channel internals (TASK-005), packaging (TASK-001), the
escalation `TargetResolver` (escalation feature).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/human/channels/teams.py` | MODIFY | add `setup_teams_hitl` + `TeamsHitlConfig` (or a sibling `teams_setup.py`) |
| `packages/ai-parrot-integrations/tests/test_teams_hitl_integration.py` | CREATE | dispatch-loop + escalate-routing + late-reply tests |
| `docs/` (new page) | CREATE | Teams HITL setup + deployment prerequisite (org-wide install) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.human import set_default_human_manager, get_default_human_manager
#   verified: packages/ai-parrot/src/parrot/human/__init__.py:63,69
from parrot.human.manager import HumanInteractionManager   # manager.py:51
# from TASK-005:
from parrot.human.channels.teams import TeamsHumanChannel
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/human/manager.py
class HumanInteractionManager:                                            # line 51
    def register_channel(self, name: str, channel: HumanChannel) -> None  # line 252
    async def startup(self) -> None                                        # line 256 (registers response+cancel handlers on all channels)
    async def advance_chain(self, interaction_id, cause=...) -> None       # line 521
    async def receive_response(self, response: HumanResponse) -> None      # line 580 (intercepts ESCALATE_OPTION_KEY)
    async def _dispatch_to_channel(self, interaction, channel) -> None     # line 391 (loops target_humans → send_interaction, line 411)

# packages/ai-parrot/src/parrot/human/__init__.py
def set_default_human_manager(manager) -> None                            # line 63
def get_default_human_manager() -> Optional[HumanInteractionManager]      # line 69
```

### Does NOT Exist
- ~~`setup_teams_hitl` / `TeamsHitlConfig`~~ — net-new in this task.
- ~~a manager method to "send teams card" directly~~ — the manager only loops `target_humans` calling `channel.send_interaction` (manager.py:411); do not add manager-side Teams logic.
- ~~`MSTeamsAgentWrapper` involvement~~ — HITL transport is a separate identity (spec §2 / Non-Goals).

---

## Implementation Notes

### Key Constraints
- No secrets in code — all creds via navconfig `${VAR}` into `TeamsHitlConfig`.
- `manager.startup()` is what wires `register_response_handler`/`register_cancel_handler`; ensure the helper leaves the channel ready for it.
- Document the org-wide install deployment prerequisite prominently (fail-fast behavior, OQ-COLD).
- Resolve OQ-9-impl: pick keyed-channels vs per-agent `BotConfig`; document the tier `channel_type` → identity selection.

### References in Codebase
- `telegram.py` setup/registration patterns; `set_default_human_manager` (human/__init__.py:63).

---

## Acceptance Criteria

- [ ] `setup_teams_hitl(app, manager, config)` registers the `"teams"` channel and webhook route in one call.
- [ ] `TeamsHitlConfig` populated from navconfig; no hardcoded secrets.
- [ ] Per-agent override path exists; OQ-9-impl selection mechanism documented.
- [ ] Integration: `_dispatch_to_channel` loops `target_humans` → `send_interaction`; escalate submit → `advance_chain(cause="reject")`.
- [ ] Docs page added (setup + org-install prerequisite).
- [ ] No linting errors: `ruff check .../human/channels/teams.py`
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/test_teams_hitl_integration.py -v`

---

## Test Specification
```python
# packages/ai-parrot-integrations/tests/test_teams_hitl_integration.py
import pytest

async def test_setup_registers_teams_channel(app, manager, config): ...
async def test_dispatch_loop_over_target_humans(manager_with_teams): ...
async def test_escalate_button_routes_to_advance_chain(manager_with_teams): ...
async def test_late_reply_after_expiry_acks(manager_with_teams): ...
```

---

## Agent Instructions
Standard SDD flow. Confirm TASK-005 is in `completed/`, verify the contract,
implement, move to `completed/`, update index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-29
**Notes**: TeamsHitlConfig (Pydantic model with env-var defaults) and setup_teams_hitl added to teams.py.
Per-agent override via keyed channels documented (OQ-9-impl: "teams:my-agent" pattern).
6 integration tests pass. Docs added at docs/hitl-teams-channel.md.
HitlCloudAdapter and GraphClient imported lazily inside setup_teams_hitl function body (not at module top) to maintain lazy-import isolation.
**Notes**:
**Deviations from spec**: none | describe if any
