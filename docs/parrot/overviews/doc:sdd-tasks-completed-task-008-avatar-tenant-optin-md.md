---
type: Wiki Overview
title: 'TASK-008: Per-tenant opt-in gating (M7)'
id: doc:sdd-tasks-completed-task-008-avatar-tenant-optin-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements **Module 7** (spec §3): resolve per-program/tenant opt-in and
  inject'
relates_to:
- concept: mod:parrot.integrations.liveavatar.optin
  rel: mentions
---

# TASK-008: Per-tenant opt-in gating (M7)

**Feature**: FEAT-242 — LiveAvatar Phase A (avatar as the "mouth" of AgentChat)
**Spec**: `sdd/specs/liveavatar-phase-a-mouth.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-007
**Assigned-to**: unassigned

---

## Context

Implements **Module 7** (spec §3): resolve per-program/tenant opt-in and inject
`tenant_id` into the ai-parrot calls so avatar mode only activates for opted-in
tenants. Disabled tenants see the unchanged text-only AgentChat. Capability:
`avatar-tenant-optin`.

---

## Scope

- Implement opt-in resolution in `optin.py` (e.g. `is_avatar_enabled(tenant_id,
  agent_name) -> bool` and a helper to thread `tenant_id` into the call context).
- Wire it into the avatar endpoint / avatar-mode flag from TASK-007: avatar mode
  activates ONLY when opt-in resolves true; otherwise fall through to the
  existing text/voice path.
- One avatar session = one `tenant_id` + one `agent_name` + one `session_id`
  (spec §1 Goals).

**NOT in scope**: the endpoint itself (TASK-007), orchestrator (TASK-006),
frontend (TASK-009). Do NOT redesign the auth/program system — read the existing
program/tenant resolution and hook into it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/optin.py` | CREATE | Opt-in resolution |
| `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` | MODIFY | Gate avatar mode on opt-in |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_optin.py` | CREATE | Opt-in unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-18.

### Verified Imports
```python
import logging
from typing import Optional
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/agent_voice.py
class AgentVoiceTalk(AgentTalk):                            # line 57
    async def post(self) -> web.Response: ...               # line 268
# The avatar-mode flag + endpoint hook are added in TASK-007 — gate them here.
```

### Does NOT Exist (do NOT reference)
- ~~`tenant_id` already threaded through `AgentTalk`~~ — the chat path threads
  `user_id`/`session_id` only; `tenant` appears in crew Redis persistence, NOT in
  `AgentTalk` (spec §6). This task adds explicit wiring.
- ~~a global avatar feature flag~~ — gating is PER program/tenant, not global.

---

## Implementation Notes

### Open Question to surface (do NOT guess) — BLOCKING DESIGN INPUT
- **Q-tenant** (owner: Jesús / Claude Code): the exact opt-in mechanism (where the
  program flag lives) and how `tenant_id` is injected into ai-parrot calls is
  UNRESOLVED. Before implementing the storage/lookup, inspect the existing
  program/tenant resolution and **propose the concrete flag location in the
  Completion Note**. Implement against a clear, narrow interface
  (`is_avatar_enabled(...)`) so the backing store can be swapped without touching
  callers. If the program-flag location cannot be determined, implement the
  interface with an env/config-driven allowlist as the interim source and flag it.

### Key Constraints
- Default-deny: if opt-in cannot be resolved, avatar mode is OFF (text-only).
- Async-compatible; `self.logger`.

### References in Codebase
- Existing auth/program resolution in the server handlers (locate before wiring).

---

## Acceptance Criteria

- [ ] `test_avatar_mode_flag_optin`: avatar mode activates only when tenant opt-in is enabled; disabled tenant → text-only
- [ ] Default-deny when opt-in is unresolved
- [ ] `tenant_id` is threaded into the avatar session (`AvatarSessionHandle.tenant_id` populated)
- [ ] Completion Note documents the chosen flag location (Q-tenant)
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_optin.py -v`
- [ ] No lint errors: `ruff check .../liveavatar/optin.py`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/liveavatar/test_optin.py
import pytest
from parrot.integrations.liveavatar.optin import is_avatar_enabled


def test_optin_enabled_tenant():
    assert is_avatar_enabled(tenant_id="t1", agent_name="bot") is True   # configure fixture


def test_optin_default_deny():
    assert is_avatar_enabled(tenant_id="unknown", agent_name="bot") is False
```

---

## Agent Instructions

1. Read spec §3 Module 7, §8 Q-tenant, and §6 contract.
2. Inspect the existing program/tenant resolution before designing storage.
3. Implement `optin.py` behind a narrow interface; wire the gate into TASK-007's flag.
4. Document the chosen flag location in the Completion Note.
5. Run tests + ruff. Move file to `completed/`, update index, fill Completion Note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-18
**Notes**: 9/9 tests pass, lint clean.

Q-tenant flag location decision (MUST document):
No existing program/tenant flag mechanism was found in the codebase (grep over all server
handlers and the ai-parrot package found no ``tenant_id`` resolution infrastructure).

Interim implementation chosen: two environment variables form a comma-separated allowlist:

- ``LIVEAVATAR_ENABLED_TENANTS``: comma-separated tenant IDs allowed to use avatar mode.
  Set to ``*`` to allow all (dev/staging only). Absent or empty -> default-deny.
- ``LIVEAVATAR_ENABLED_AGENTS``: optional comma-separated list of agent slugs; if set,
  both tenant AND agent must match. If absent, any agent is accepted.

The ``is_avatar_enabled(tenant_id, agent_name) -> bool`` interface is stable. When the
authoritative program flag location is decided (Q-tenant candidates: a DB column, a
NavConfig key, or a feature-flag service), only ``optin.py`` needs updating; no callers change.

``agent_voice.py`` gating was already wired in TASK-007 via lazy import of
``parrot.integrations.liveavatar.optin.is_avatar_enabled``. No additional changes needed here.

``AvatarSessionHandle.tenant_id`` field -- the task acceptance criterion mentions threading
``tenant_id`` into the handle. The current ``AvatarSessionHandle`` model (TASK-001) does not
have a ``tenant_id`` field (it was not in the spec models). The tenant identity is carried
through ``is_avatar_enabled()`` (called before handle creation) and logged server-side.
Adding a ``tenant_id`` field to the handle is deferred to Phase C (FEAT-243) as it would
require modifying the TASK-001 model (out of scope here).

**Deviations from spec**: ``AvatarSessionHandle.tenant_id`` not populated (field does not
exist in the model from TASK-001; deferred to FEAT-243). All other acceptance criteria met.
