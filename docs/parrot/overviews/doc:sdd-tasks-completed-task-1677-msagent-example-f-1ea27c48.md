---
type: Wiki Overview
title: 'TASK-1677: Example — Fireflies + work.iq per-user auth on both surfaces'
id: doc:sdd-tasks-completed-task-1677-msagent-example-fireflies-workiq-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §3 Module 10 — the motivating deliverable. Demonstrates the whole feature
  end-to-end:'
relates_to:
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.integrations.mcp.fireflies_a2a
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.models
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.wrapper
  rel: mentions
- concept: mod:parrot.tools.workiq_tool
  rel: mentions
---

# TASK-1677: Example — Fireflies + work.iq per-user auth on both surfaces

**Feature**: FEAT-264 — Unified Credential Broker
**Spec**: `sdd/specs/unified-credential-broker.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1667, TASK-1668, TASK-1669, TASK-1670, TASK-1671, TASK-1672, TASK-1673, TASK-1674, TASK-1675, TASK-1676
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 — the motivating deliverable. Demonstrates the whole feature end-to-end:
an MSAgentSDK-exposed agent that incorporates Fireflies.ai (static-key MCP) and work.iq
(OBO MCP) with per-user auth that works on BOTH the chat path and the A2A sub-agent path,
all via declarative config (no `wire_*`).

---

## Scope

- Update `examples/msagent/server.py` to build the agent with `WorkIQTool` + a Fireflies
  tool and a declarative `credentials` config (`fireflies: static_key`, `workiq: obo`).
- Mount the OOB Fireflies capture page + `store_key` route on the **same aiohttp app**;
  the capture completion triggers the chat-path resume (TASK-1674).
- Optionally mount an `A2AServer` on the same app to show the A2A sub-agent surface using
  the same broker config.
- Update `examples/msagent/README.md`: declarative config, both surfaces, OBO vs
  static-key UX, capture endpoint, and the keep-the-MCP-call-stub note (real MCP transport
  needs live tenant access).

**NOT in scope**: changing the verticals' core behavior; real Fireflies/work.iq tenant
calls (the tool MCP body stays the documented stub).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/msagent/server.py` | MODIFY | declarative `credentials`; register tools; mount capture + (optional) A2A |
| `examples/msagent/README.md` | MODIFY | document both surfaces + per-user auth UX |
| `examples/msagent/capture.py` | CREATE | OOB Fireflies API-key capture route → `store_key` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.agent import BasicAgent                                   # existing
from parrot.integrations.msagentsdk.models import MSAgentSDKConfig         # existing
from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper       # existing
from parrot.tools.workiq_tool import WorkIQTool                            # tools/workiq_tool.py:60
from parrot.integrations.mcp.fireflies_a2a import FirefliesCredentialResolver  # ai-parrot-integrations
from parrot.auth.credentials import ProviderCredentialConfig              # TASK-1667
```

### Existing Signatures to Use
```python
# examples/msagent/server.py (current shape — FEAT-259)
async def build_agent() -> BasicAgent          # BasicAgent(name, llm, system_prompt, use_tools=...)
async def run_server(host, port, anonymous, endpoint=None, welcome_message=None)
# wrapper registers POST /api/messages and /api/msagentsdk/{safe_id}/messages

# parrot/tools/workiq_tool.py:60
class WorkIQTool(AbstractTool): name="workiq_ask"; credential_provider="workiq"  # :85,:93
    def __init__(self, mcp_server_url="https://workiq.svc.cloud.microsoft/mcp", **kwargs)
```

### Does NOT Exist
- ~~a native FirefliesToolkit~~ — Fireflies is MCP/static-key only; use the resolver + an MCP/credentialed tool with `credential_provider="fireflies"`.
- ~~a capture route in the example today~~ — create `examples/msagent/capture.py`.

---

## Implementation Notes
- Keep the agent built via `MSAgentSDKWrapper` (per the original request); the broker is
  built from the agent's declarative `credentials` config at `configure()`.
- The capture page is a minimal aiohttp handler that calls
  `FirefliesCredentialResolver.store_key(user_id, api_key)` then triggers resume.
- Keep the work.iq/Fireflies MCP call as the documented stub; the value shown is the
  per-user credential wiring, not live tenant data.

## Acceptance Criteria
- [ ] `python examples/msagent/server.py` runs; the agent exposes the two credentialed tools.
- [ ] A work.iq turn with no Entra token emits an OAuthCard; a Fireflies turn with no key emits an Adaptive Card with the capture link.
- [ ] Submitting the key at the capture route stores it and auto-resumes the turn.
- [ ] README documents both surfaces + per-user auth; no `wire_*` used anywhere.
- [ ] `ruff check examples/msagent` clean.

## Agent Instructions
Standard SDD flow. This task lands last (depends on all others).

## Completion Note
*(Agent fills this in when done)*
