---
type: Wiki Overview
title: 'Feature Specification: JiraSpecialist `trigger_agent` → Orchestrator Dispatch'
id: doc:sdd-specs-jiraspecialist-trigger-agent-orchestrator-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: classifies the event, and the agent routes it through
relates_to:
- concept: mod:parrot.autonomous
  rel: mentions
- concept: mod:parrot.autonomous.orchestrator
  rel: mentions
- concept: mod:parrot.bots._types
  rel: mentions
- concept: mod:parrot.bots.jira_specialist
  rel: mentions
- concept: mod:parrot.core.hooks.models
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: JiraSpecialist `trigger_agent` → Orchestrator Dispatch

**Feature ID**: FEAT-265
**Date**: 2026-07-01
**Author**: Jesus Lara
**Status**: approved
**Target version**: (next minor)

> Follow-up to **FEAT (jiraspecialist-webhooks)** — see
> `sdd/specs/jiraspecialist-webhooks.spec.md`, *Known Risks* and
> *Open Questions*, which explicitly deferred this integration.

---

## 1. Motivation & Business Requirements

### Problem Statement

`JiraSpecialist` already consumes Jira webhooks end-to-end: the
`JiraWebhookHook` receives the POST, validates the HMAC signature,
classifies the event, and the agent routes it through
`handle_hook_event()` → `_dispatch_transition()` → a registry of
`TransitionAction`s. Three of the four action types work:
`NOTIFY_CHANNEL`, `CALL_HANDLER`, and `LOG`.

The fourth, **`TRIGGER_AGENT`**, is an intentional stub. Today
`_action_trigger_agent()` only logs the intent
(`"...(orchestrator integration pending)"`) and returns a *synthetic*
`{"status": "triggered", ...}` without invoking any agent
(`packages/ai-parrot/src/parrot/bots/jira_specialist.py:1282-1330`).
The reason: `JiraSpecialist` holds **no reference** to anything that can
dispatch another agent. `AutonomousOrchestrator` already exposes a
public `execute_agent(agent_name, task, ...)` API
(`packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py:406`),
but the agent cannot reach it.

This means a Jira transition cannot kick off downstream automation
(e.g. "when NAV-xxxx moves to *Ready For Deploy*, trigger the
`deploy_bot` agent"). The capability is configured-but-inert.

### Goals

- Make `TRIGGER_AGENT` actually dispatch the configured agent with the
  rendered task when a Jira transition matches.
- Preserve the documented architectural boundary: `JiraSpecialist` lives
  in the `ai-parrot` (core) package; `AutonomousOrchestrator` lives in
  `ai-parrot-server`. **Core must not import server.**
- Keep full backward compatibility: when no dispatcher is wired, the
  action must keep its current log-only behaviour (no crash, no change
  to the return contract beyond a clearer `status`).
- Provide tests that assert a *real* dispatch occurs (not just a log).

### Non-Goals (explicitly out of scope)

- Changing the webhook reception path (`JiraWebhookHook`,
  signature validation, event classification) — unchanged.
- Changing the other three action types (`NOTIFY_CHANNEL`,
  `CALL_HANDLER`, `LOG`).
- Importing `AutonomousOrchestrator` into core, or moving
  `JiraSpecialist` into the server package — rejected, see §1 boundary
  goal. A hard core→server import is a layering violation.
- Crew/flow dispatch (`execute_crew`, `run_flow`) from a transition —
  may be a later follow-up; this feature wires single-agent dispatch
  only.
- Result fan-back (sending the triggered agent's output back to Jira as
  a comment) — out of scope; only fire-and-forward dispatch is required.

---

## 2. Architectural Design

### Overview

Introduce a **narrow, injectable async dispatcher** on `JiraSpecialist`
— a duck-typed callable, not a concrete orchestrator type. This avoids
the core→server import while letting the server wire the real
orchestrator at startup.

Define a `Protocol` (`AgentDispatcher`) in core describing the single
method the action needs:

```python
async def __call__(agent_name: str, task: str, *,
                   user_id: str | None = None,
                   session_id: str | None = None) -> Any
```

`AutonomousOrchestrator.execute_agent` already satisfies this shape
(its extra params are keyword-only with defaults), so wiring is simply:

```python
jira_specialist.set_agent_dispatcher(orchestrator.execute_agent)
```

`_action_trigger_agent()` changes from "log only" to:

1. Resolve `agent_id` + render `task` from the template (unchanged).
2. If a dispatcher is set → `await self._agent_dispatcher(agent_id, task, ...)`,
   return `{"status": "dispatched", "agent_id", "task", "result": <summary>}`.
3. If no dispatcher is set → log the intent and return
   `{"status": "skipped", "reason": "no dispatcher wired", ...}`
   (today it returns `"triggered"`; see §8 for the status-value decision).

Errors from the dispatcher are caught and returned as
`{"status": "error", ...}` — a downstream agent failure must not break
the webhook response or the transition loop (mirrors `_action_notify_channel`).

### Component Diagram

```
Jira  ──POST──▶ JiraWebhookHook ──HookEvent──▶ handle_hook_event()
                                                     │
                                              _dispatch_transition()
                                                     │
                                          _invoke_transition_action()
                                                     │  TRIGGER_AGENT
                                                     ▼
                                          _action_trigger_agent()
                                                     │  (NEW: real call)
                                                     ▼
                                       self._agent_dispatcher(...)   ◀── injected
                                                     │                    at startup
                                                     ▼
                              AutonomousOrchestrator.execute_agent()  (server)
                                                     │
                                              _execute() → agent.ask()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `JiraSpecialist` | extends | New `_agent_dispatcher` attr + `set_agent_dispatcher()` setter; `_action_trigger_agent` body |
| `AutonomousOrchestrator.execute_agent` | called (via injected callable) | Already matches the `AgentDispatcher` protocol; no change to the orchestrator |
| `TransitionAction` / `TransitionActionType.TRIGGER_AGENT` | uses (unchanged) | `action_config` keys `agent_id`, `task_template` already defined |
| App startup wiring | new call | Wherever the orchestrator and the concrete Jira agent are constructed, call `set_agent_dispatcher` |

### Data Models

The `AgentDispatcher` protocol lives in a **shared** module,
`parrot/bots/_types.py` (resolved §8), so other agents can reuse it:

```python
# parrot/bots/_types.py  (NEW shared module)
from typing import Any, Optional, Protocol

class AgentDispatcher(Protocol):
    """Duck-typed async callable that dispatches a named agent.

    AutonomousOrchestrator.execute_agent satisfies this shape.
    """
    async def __call__(
        self,
        agent_name: str,
        task: str,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Any: ...
```

No new Pydantic model is required — `TransitionAction.action_config`
already carries `agent_id` and `task_template`.

### New Public Interfaces

```python
class JiraSpecialist(Agent):
    def set_agent_dispatcher(self, dispatcher: "AgentDispatcher") -> None:
        """Wire an async dispatcher so TRIGGER_AGENT actions can invoke
        other agents. Without this, TRIGGER_AGENT degrades to log-only."""
        ...
```

---

## 3. Module Breakdown

### Module 1: `AgentDispatcher` protocol + dispatcher slot

- **Path (protocol)**: `packages/ai-parrot/src/parrot/bots/_types.py`
  (NEW shared module — resolved §8; reusable by other agents).
- **Path (slot)**: `packages/ai-parrot/src/parrot/bots/jira_specialist.py`
- **Responsibility**: Define the `AgentDispatcher` Protocol in the shared
  module; import it into `jira_specialist.py`; add
  `self._agent_dispatcher: Optional[AgentDispatcher] = None` in
  `__init__`; add `set_agent_dispatcher()`.
- **Depends on**: nothing new.

### Module 2: Real dispatch in `_action_trigger_agent`

- **Path**: `packages/ai-parrot/src/parrot/bots/jira_specialist.py`
- **Responsibility**: Replace the log-only body with the
  dispatcher-call logic (dispatch / skip / error branches). Keep
  `agent_id` resolution and `task_template` rendering exactly as-is.
- **Depends on**: Module 1.

### Module 3: Startup wiring

- **Path**: the deployment project's **`app.py`** (resolved §8). Dispatch
  is never driven from this pure repo — deployment runs a separate project
  with `ai-parrot` installed, whose `app.py` is the startup entrypoint
  where both the `AutonomousOrchestrator` and the concrete Jira agent are
  constructed. This means the wiring is **documented here but applied in
  the consuming project**, not committed to this repo. Provide a copy-paste
  snippet + a short doc note rather than an in-repo code change.
- **Responsibility**: after both objects exist, call
  `agent.set_agent_dispatcher(orchestrator.execute_agent)`.
- **Depends on**: Module 1.

### Module 4: Tests

- **Path**: `packages/ai-parrot/tests/test_jira_transition_dispatch.py`
  (extend existing `TestActionTriggerAgent`).
- **Responsibility**: assert real dispatch, skip-when-unwired, and
  error-handling branches.
- **Depends on**: Modules 1–2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_dispatches_to_wired_dispatcher` | 2 | With a fake dispatcher set, `_action_trigger_agent` awaits it once with the resolved `agent_id` and rendered `task`; returns `status="dispatched"` |
| `test_skips_when_no_dispatcher` | 2 | With no dispatcher, returns `status="skipped"` and logs intent; does NOT raise (backward-compatible degrade) |
| `test_dispatcher_error_is_caught` | 2 | Dispatcher raises → returns `status="error"` with the message; transition loop continues |
| `test_task_template_rendered_before_dispatch` | 2 | `task_template` placeholders (`{issue_key}`, `{from_status}`, `{to_status}`, `{summary}`, `{assignee}`) are filled in the task passed to the dispatcher |
| `test_no_agent_id_skips` | 2 | Missing `agent_id` → `status="skipped"` (unchanged guard) |
| `test_set_agent_dispatcher_sets_attr` | 1 | `set_agent_dispatcher()` stores the callable |
| `test_execute_agent_satisfies_protocol` | 1/3 | `AutonomousOrchestrator.execute_agent` is accepted as an `AgentDispatcher` (call-shape compatibility, structural) |

### Integration Tests

| Test | Description |
|---|---|
| `test_transition_triggers_agent_end_to_end` | A `jira.transitioned` payload with a `TRIGGER_AGENT` action, dispatcher wired to a stub orchestrator, drives `handle_hook_event` → stub orchestrator records one `execute_agent` call |

### Test Data / Fixtures

```python
@pytest.fixture
def trigger_agent_action():
    return TransitionAction(
        from_status="*",
        to_status="Ready For Deploy",
        action_type=TransitionActionType.TRIGGER_AGENT,
        action_config={"agent_id": "deploy_bot",
                       "task_template": "Deploy {issue_key}"},
    )

class _RecordingDispatcher:
    def __init__(self): self.calls = []
    async def __call__(self, agent_name, task, *, user_id=None, session_id=None):
        self.calls.append((agent_name, task)); return {"ok": True}
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `JiraSpecialist` exposes `set_agent_dispatcher()` and stores an
      optional `_agent_dispatcher` (default `None`).
- [ ] When a dispatcher is wired, a `TRIGGER_AGENT` transition action
      `await`s it exactly once with the resolved `agent_id` and the
      rendered `task`, and returns `status="dispatched"`.
- [ ] When no dispatcher is wired, `_action_trigger_agent` logs intent
      and returns a non-error status **without raising** (backward
      compatible — the webhook still returns 200).
- [ ] A dispatcher exception is caught and surfaced as `status="error"`;
      the transition action loop continues for remaining matched actions.
- [ ] `task_template` rendering behaviour is unchanged (same placeholders,
      same `KeyError` fallback to the raw template).
- [ ] **No import of `AutonomousOrchestrator` (or any
      `parrot.autonomous.*` / `ai-parrot-server` symbol) is added to the
      `ai-parrot` core package.** (`grep` proof in the PR.)
- [ ] `AgentDispatcher` protocol is defined in the shared module
      `parrot/bots/_types.py` and imported by `jira_specialist.py`.
- [ ] Startup wiring is documented for the consuming project's `app.py`
      (`set_agent_dispatcher(orchestrator.execute_agent)`) — shipped as a
      doc snippet, not committed into this repo's `agents/`.
- [ ] New + existing unit tests pass:
      `pytest packages/ai-parrot/tests/test_jira_transition_dispatch.py -v`
- [ ] No breaking change to `handle_hook_event` / `_dispatch_transition`
      public behaviour for the other three action types.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified against the tree on
> branch `dev` at spec time. Re-verify line numbers before editing — the
> file is large and shifts.

### Verified Imports

```python
# core agent (the file being modified)
from parrot.bots.jira_specialist import JiraSpecialist
# verified: packages/ai-parrot/src/parrot/bots/jira_specialist.py:154

# NEW shared protocol module (to be created by this feature)
from parrot.bots._types import AgentDispatcher
# NEW: packages/ai-parrot/src/parrot/bots/_types.py (does not exist yet)

# transition models (already imported in jira_specialist.py)
from parrot.core.hooks.models import TransitionAction, TransitionActionType
# verified: TransitionAction packages/ai-parrot/src/parrot/core/hooks/models.py:119
#           JiraWebhookConfig                                  ...:155

# orchestrator (server side — used ONLY at startup wiring, NOT imported by core)
from parrot.autonomous.orchestrator import AutonomousOrchestrator
# verified: packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py
#           execute_agent at :406
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py
class JiraSpecialist(Agent):                                    # line 154
    def __init__(self, **kwargs): ...                           # line 204
        self._wrapper = None                                    # line 232
        self.jira_toolkit: Optional[JiraToolkit] = None         # line 234
        self._transition_actions: List[TransitionAction] = ...  # line 236

    async def handle_hook_event(self, event) -> Optional[dict]  # ~line 1098 (router)
    async def _dispatch_transition(self, payload) -> dict       # ~line 1135
    async def _invoke_transition_action(
        self, action: TransitionAction, payload: dict) -> dict  # line 1194
    async def _action_notify_channel(self, payload, config)     # line 1221 (error-handling pattern to mirror)
    async def _action_trigger_agent(self, payload, config)      # line 1282 (STUB — to replace)
    def _action_log_transition(self, payload, config)           # line 1332
    async def _action_call_handler(self, payload, config)       # line 1361

# packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py
class AutonomousOrchestrator:
    async def execute_agent(                                    # line 406
        self, agent_name: str, task: str, *,
        method_name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs) -> ExecutionResult: ...
    async def _handle_hook_event(self, event: HookEvent) -> None  # line 348
    async def _execute(self, request) -> ExecutionResult          # line 847
    async def _get_agent(self, agent_name) -> "AbstractBot"        # line 1102

# packages/ai-parrot/src/parrot/core/hooks/mixins.py
class HookableAgent:                                            # line 9
    def _init_hooks(self) -> None                               # line 40
    async def handle_hook_event(self, event) -> None            # line 81 (default impl; overridden by JiraSpecialist)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `JiraSpecialist._agent_dispatcher` | `AutonomousOrchestrator.execute_agent` | injected callable | orchestrator.py:406 |
| `_action_trigger_agent` (new body) | `self._agent_dispatcher(...)` | `await` call | jira_specialist.py:1282 |
| startup wiring | `JiraSpecialist.set_agent_dispatcher` | method call | new |

### Does NOT Exist (Anti-Hallucination)

- ~~`JiraSpecialist.orchestrator`~~ / ~~`JiraSpecialist._orchestrator`~~ —
  no such attribute (confirmed in `__init__`, lines 204-236). This
  feature adds `_agent_dispatcher`, **not** a typed orchestrator handle.
- ~~`AutonomousOrchestrator.dispatch_agent`~~ — the public method is
  `execute_agent` (line 406); also `execute_crew` (line 441).
- ~~core importing `parrot.autonomous`~~ — does NOT exist today and MUST
  NOT be introduced (layering rule).
- ~~`TransitionActionType.TRIGGER_AGENT` extra config keys~~ — only
  `agent_id` and `task_template` are read by the current code; do not
  invent others without updating `action_config` docs.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Mirror `_action_notify_channel` (jira_specialist.py:1221) for the
  try/except → `{"status": "error", ...}` shape; never let a downstream
  failure escape the action handler.
- async-first: `_agent_dispatcher` is an async callable; always `await`.
- Logging via `self.logger`; keep an INFO line on dispatch and a WARNING
  on skip, consistent with the existing handlers.
- Use `typing.Protocol` (structural typing) so any object with a matching
  `execute_agent`-shaped callable qualifies — no inheritance coupling.

### Known Risks / Gotchas

- **Layering**: the single most important constraint — keep the import
  graph core-clean. Wiring happens at the app/server edge, where both
  objects already exist.
- **`agents/` is gitignored** (see project memory) and is NOT the
  dispatch host. Deployment uses a separate project with `ai-parrot`
  installed; the wiring lives in that project's **`app.py`** (resolved
  §8). So this repo ships the `set_agent_dispatcher` API + a doc snippet,
  not an in-repo wiring commit. Do not add the call to any file under
  `agents/`.
- **Return-status change**: today the stub returns `status="triggered"`.
  Existing test `test_logs_trigger_intent` asserts that value. This spec
  changes semantics to `dispatched`/`skipped`/`error` (resolved §8). The
  existing test MUST be updated, not left asserting the old synthetic
  status — call this out so it isn't treated as a regression.
- **Fire-and-forward vs await** (resolved §8): v1 `await`s the dispatcher
  inline so the action return dict carries the real result/error. This
  ties webhook latency to the downstream agent's runtime — **verify after
  rollout** that slow agents don't push the response past Jira's webhook
  timeout; if they do, move to `asyncio.create_task` in a follow-up.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| (none) | — | Uses stdlib `typing.Protocol`; no new deps |

---

## 8. Open Questions

- [x] **Dispatch concurrency model** — *Resolved*: `await` the dispatcher
      **inline** for v1 (simple; the action return dict carries the real
      result/error). Accept that webhook latency is tied to the downstream
      agent's runtime; **verify after rollout** whether slow agents push
      the response past Jira's webhook timeout and, if so, revisit
      `asyncio.create_task` fire-and-forget in a follow-up.
- [x] **Where does the startup wiring live** — *Resolved*: in **`app.py`**.
      Dispatch is never driven from the pure repo; deployment uses a
      separate project with `ai-parrot` installed, and its `app.py` is the
      standard startup entrypoint where both the orchestrator and the
      concrete Jira agent exist. `agents/` is gitignored precisely because
      it is not the dispatch host (see project memory), so the wiring does
      NOT belong there.
- [x] **Return-status vocabulary** — *Resolved*: adopt
      `dispatched` / `skipped` / `error`, replacing the synthetic
      `triggered`. No external consumer relies on `"triggered"`; the only
      caller is `_invoke_transition_action`, and the existing test that
      asserts `"triggered"` will be updated (see §7 Known Risks).
- [x] **Protocol location** — *Resolved*: **promote** `AgentDispatcher`
      to a shared module **`parrot/bots/_types.py`** so other agents that
      later need dispatch can reuse it (not local to
      `jira_specialist.py`).

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (all tasks sequential in one
  worktree). The change is small and the modules are tightly coupled to a
  single file plus its tests.
- **Cross-feature dependencies**: none. Builds on the already-merged
  `jiraspecialist-webhooks` feature; no other spec must merge first.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-01 | Jesus Lara | Initial draft (follow-up to jiraspecialist-webhooks) |
| 0.2 | 2026-07-01 | Jesus Lara | Resolved all 4 open questions: shared `_types.py` protocol, wiring in consuming `app.py`, await-inline v1, `dispatched/skipped/error` status vocab |
