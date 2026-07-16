---
type: Wiki Overview
title: 'Feature Specification: Per-Agent Cost & Usage Metrics'
id: doc:sdd-specs-per-agent-cost-usage-metrics-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'traces**, not in metrics. Today:'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events.client
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events.invoke
  rel: mentions
- concept: mod:parrot.observability
  rel: mentions
- concept: mod:parrot.observability.context
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Per-Agent Cost & Usage Metrics

**Feature ID**: FEAT-228
**Date**: 2026-06-08
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.x

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

`parrot.observability` attributes telemetry to a specific agent **only in
traces**, not in metrics. Today:

- The agent root span carries `parrot.agent.name = self.name`
  (`bots/base.py` emits `BeforeInvokeEvent(agent_name=self.name, ...)`, and
  `subscribers/trace.py:349` writes it onto the invoke span).
- But the **metrics** for LLM client calls — cost (USD), token usage, and
  request duration — are labelled with `gen_ai.system` (provider) and
  `gen_ai.response.model` **only**. See
  `subscribers/metrics.py:_on_client_after`, where
  `base = {"gen_ai.system": system, "gen_ai.response.model": model}` and
  `self._client_cost_total.add(cost, attributes=base)`.

Consequence: in a process that hosts **dozens of agents** behind a
`BotManager`/`AgentRegistry`, you **cannot** slice "USD cost per agent" or
"tokens per agent" from the metrics layer. The only way to get per-agent cost
today is to walk the trace tree (sum each client child span's
`parrot.cost.usd` grouped by the parent invoke span's `parrot.agent.name`),
which does not feed aggregated cost/billing dashboards.

The root cause is structural: cost is computed in the **client** call event
(`AfterClientCallEvent`), and the client (`clients/base.py`) holds **no
reference** to the invoking agent. So at the moment a metric is recorded, the
agent identity is unknown.

`OBSERVABILITY_SERVICE_NAME` (OTel `service.name`) is the correct identifier
for the **facility/process** (e.g. `navigator-agent-server`) and is shared by
the whole process — it is *not* and should not be a per-agent dimension. The
per-agent grain must come from a per-record attribute.

### Goals

- Add the invoking agent's identity (`parrot.agent.name`, sourced from
  `AbstractBot.name`) as a dimension on the **client-level metrics**: cost
  counter, token-usage histogram, and client operation-duration histogram.
- Use a `contextvars.ContextVar` set by the bot around each public invocation
  and read by the client when it constructs its lifecycle events — so the
  identity rides on the event itself and nesting (crew / agent-calls-agent) is
  handled naturally by task-local context semantics.
- Also expose `parrot.agent.name` on the **client child span** (trace layer)
  for symmetry, so per-agent attribution is available both as a flat span
  attribute and via the trace tree.
- Keep `AbstractBot.name` (`self.name`) as the only identity carried — it
  covers both `Chatbot` and `Agent` subclasses. No `chatbot_id`/UUID is
  required (confirmed by the requester).
- Attribution must be best-effort: a missing/failed lookup degrades to
  `"unknown"` and **never** breaks an LLM call.

### Non-Goals (explicitly out of scope)

- Adding `chatbot_id`/UUID to telemetry — only the human `name` is in scope.
- Re-labelling `OBSERVABILITY_SERVICE_NAME` semantics — `service.name` stays
  process/facility-scoped.
- Capturing prompts/completions or any PII — the PII contract is unchanged
  (`user_id`, `session_id`, prompt/completion content NEVER enter labels;
  `subscribers/metrics.py` docstring lines 9–10).
- Per-agent dimensioning of the OpenLIT auto-instrumented spans — OpenLIT owns
  those; we only enrich AI-Parrot's native subscribers.
- Subscriber-side `trace_id → agent_name` correlation map — rejected in favour
  of the ContextVar approach because a flat map keyed by `trace_id` mis-attributes
  nested agents that share a trace (see §2 Overview).

---

## 2. Architectural Design

### Overview

**Chosen mechanism: a `contextvars.ContextVar` carrying the active agent name.**

1. A new module exposes a module-level
   `current_agent_name: ContextVar[Optional[str]]` plus a small context-manager
   helper `agent_identity(name)` that does `set()`/`reset()` with a token.
2. Each public invocation entry point on `AbstractBot`
   (`conversation`, `invoke`, `ask`, `ask_stream`) wraps its body in
   `agent_identity(self.name)`. Because `ContextVar` values are task-local and
   are **copied** into tasks spawned via `asyncio.create_task`, any LLM client
   call made within the invocation — including fire-and-forget event emission —
   observes the correct name. Nested invocations push/pop their own token, so an
   inner agent's calls are attributed to the inner agent and the outer value is
   restored on exit.
3. The three client lifecycle events
   (`BeforeClientCallEvent`/`AfterClientCallEvent`/`ClientCallFailedEvent`) gain
   an optional `agent_name: Optional[str] = None` field. `clients/base.py` reads
   `current_agent_name.get()` at the point it **constructs** each event
   (`_send_before`/`_send_after`/`_send_failed`, lines 455/497/534) — these run
   in the bot's async context, so the value is present.
4. `MetricsSubscriber` adds `"parrot.agent.name": event.agent_name or "unknown"`
   to the `base` label dict for the cost counter, token histogram, and client
   duration histogram. `GenAIOpenTelemetrySubscriber` adds the same key to the
   client span via the attribute builders.

Why not the subscriber-correlation alternative: a `trace_id → agent_name` map
in the subscriber cannot disambiguate nested agents (an `AgentCrew` or an agent
that invokes another agent shares one `trace_id`); the inner agent's LLM calls
would be mis-attributed to whichever agent last emitted `BeforeInvokeEvent`.
ContextVars nest correctly by construction.

### Component Diagram
```
AbstractBot.ask/ask_stream/invoke/conversation
        │  with agent_identity(self.name):   ← sets current_agent_name (ContextVar)
        ▼
AbstractClient._send_before/_send_after/_send_failed
        │  agent_name = current_agent_name.get()
        ▼
*ClientCallEvent(agent_name=...)  ──(bridged to global registry)──┐
        ├──────────────────────────────┐                          │
        ▼                               ▼                          ▼
MetricsSubscriber                GenAIOpenTelemetrySubscriber   (other providers)
  base += {parrot.agent.name}      client span += parrot.agent.name
  → cost / tokens / duration
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot` (`bots/base.py`) | wraps | `ask`/`ask_stream`/`invoke`/`conversation` set the ContextVar around their body. |
| `Agent` (`bots/agent.py`) | inherits / may wrap | If its invoke paths bypass `base.py`'s wrapping, apply `agent_identity(self.name)` there too (lines 364, 586 emit `BeforeInvokeEvent`). |
| `AbstractClient` (`clients/base.py`) | reads ContextVar | Populate `agent_name` when building the 3 client events (455/497/534). |
| `BeforeClientCallEvent` / `AfterClientCallEvent` / `ClientCallFailedEvent` | extend | New optional `agent_name` field (frozen dataclass). |
| `MetricsSubscriber` (`subscribers/metrics.py`) | modifies | Add label to `base` in `_on_client_after` / `_on_client_before` / `_on_client_fail`. |
| `GenAIOpenTelemetrySubscriber` (`subscribers/trace.py`) | modifies | Add `parrot.agent.name` via client attribute builders. |
| `attributes.py` builders | modifies | `build_*_client_attrs` include `parrot.agent.name` when present. |

### Data Models
```python
# core/events/lifecycle/events/client.py — add ONE optional field to each
# of the three frozen dataclasses (defaults keep backward compatibility).
@dataclass(frozen=True)
class AfterClientCallEvent(LifecycleEvent):
    client_name: str = ""
    model: str = ""
    duration_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    agent_name: Optional[str] = None        # NEW — invoking agent's self.name
```

### New Public Interfaces
```python
# parrot/observability/context.py  (NEW module)
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

current_agent_name: ContextVar[Optional[str]] = ContextVar(
    "parrot_current_agent_name", default=None
)

@contextmanager
def agent_identity(name: Optional[str]) -> Iterator[None]:
    """Bind ``name`` as the active agent for the duration of the block.

    Token-based set/reset so nested invocations restore the prior value.
    """
    token = current_agent_name.set(name)
    try:
        yield
    finally:
        current_agent_name.reset(token)
```

---

## 3. Module Breakdown

> These map directly to Task Artifacts in Phase 2.

### Module 1: agent-identity ContextVar
- **Path**: `packages/ai-parrot/src/parrot/observability/context.py` (new)
- **Responsibility**: Define `current_agent_name` ContextVar + `agent_identity`
  context manager. Re-export from `parrot/observability/__init__.py`.
- **Depends on**: nothing (stdlib only).

### Module 2: client event schema
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py`
- **Responsibility**: Add optional `agent_name: Optional[str] = None` to
  `BeforeClientCallEvent`, `AfterClientCallEvent`, `ClientCallFailedEvent`.
- **Depends on**: nothing.

### Module 3: bot invocation wrapping
- **Path**: `packages/ai-parrot/src/parrot/bots/base.py` (and `bots/agent.py`
  if its invoke paths bypass base).
- **Responsibility**: Wrap the four public entry points
  (`conversation`/`invoke`/`ask`/`ask_stream`) in `agent_identity(self.name)`.
- **Depends on**: Module 1.

### Module 4: client event population
- **Path**: `packages/ai-parrot/src/parrot/clients/base.py`
- **Responsibility**: At `_send_before`/`_send_after`/`_send_failed`, set
  `agent_name=current_agent_name.get()` on the constructed event.
- **Depends on**: Modules 1 & 2.

### Module 5: metrics label
- **Path**: `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py`
- **Responsibility**: Add `"parrot.agent.name": event.agent_name or "unknown"`
  to the `base` label dict used by cost counter, token histogram, and client
  duration histogram.
- **Depends on**: Module 2.

### Module 6: trace/client-span label
- **Path**: `packages/ai-parrot/src/parrot/observability/attributes.py` +
  `subscribers/trace.py`
- **Responsibility**: `build_before_client_attrs`/`build_after_client_attrs`/
  `build_client_failed_attrs` include `parrot.agent.name` when `event.agent_name`
  is set (omit when None — never write a null attribute).
- **Depends on**: Module 2.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_agent_identity_sets_and_resets` | Module 1 | ContextVar is set inside the block and restored to prior value (incl. None) after. |
| `test_agent_identity_nested` | Module 1 | Nested `agent_identity("a")`/`agent_identity("b")` restores "a" after inner exits. |
| `test_client_events_have_agent_name_field` | Module 2 | New field defaults to None; events remain frozen & `to_dict()`-serializable. |
| `test_client_reads_contextvar` | Module 4 | With `current_agent_name` set, emitted `AfterClientCallEvent.agent_name` equals it; unset → None. |
| `test_metrics_label_includes_agent` | Module 5 | Cost/token/duration records carry `parrot.agent.name`; missing → `"unknown"`. |
| `test_client_span_attr_includes_agent` | Module 6 | Client span gets `parrot.agent.name`; omitted when event.agent_name is None. |

### Integration Tests
| Test | Description |
|---|---|
| `test_per_agent_cost_attribution` | Two bots with distinct `name` each make a mocked client call under their own invoke; assert metric records carry the right `parrot.agent.name` and costs do not cross-attribute. |
| `test_nested_agent_attribution` | Outer bot invokes inner bot; inner LLM call attributes to inner name, outer call to outer name. |
| `test_attribution_failure_is_non_fatal` | Forcing the ContextVar lookup path to raise still completes the LLM call (records `"unknown"`). |

### Test Data / Fixtures
```python
# Reuse the existing in-memory exporter/reader fixtures in
# tests/integration/observability/ (test_poc.py pattern: span exporter +
# metric reader wired to a local provider). Add two minimal stub bots with
# distinct .name and a mocked AbstractClient that emits the 3 call events.
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `current_agent_name` ContextVar + `agent_identity` context manager exist
      in `parrot/observability/context.py` and are exported from
      `parrot/observability/__init__.py`.
- [ ] The 3 client events carry an optional `agent_name` field (default None),
      remain `@dataclass(frozen=True)`, and pass the `to_dict()` JSON check.
- [ ] `ask`, `ask_stream`, `invoke`, `conversation` on `AbstractBot` bind
      `self.name` for the duration of the call.
- [ ] LLM client metrics (cost counter, token histogram, client duration
      histogram) include `parrot.agent.name`, falling back to `"unknown"` when
      absent.
- [ ] The client child span includes `parrot.agent.name` (omitted when None).
- [ ] Nested-agent attribution is correct (inner ≠ outer) — covered by
      `test_nested_agent_attribution`.
- [ ] Attribution never raises into the LLM call path
      (`test_attribution_failure_is_non_fatal`).
- [ ] PII contract intact: no `user_id`/`session_id`/prompt content added to any
      label.
- [ ] All observability tests pass: `pytest packages/ai-parrot/tests/integration/observability/ -v`.
- [ ] Perf budget unchanged: `pytest packages/ai-parrot/tests/integration/observability/test_perf.py -v`
      (ContextVar get/set is ~ns; must not regress the documented p50 budgets).
- [ ] No breaking changes to existing public API (new field is optional; new
      label is additive).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
# verified: subscribers/metrics.py:23 imports from core.events.lifecycle
from parrot.core.events.lifecycle.events.client import (   # verified: file exists, lines 18/38/62
    BeforeClientCallEvent, AfterClientCallEvent, ClientCallFailedEvent,
)
from parrot.core.events.lifecycle.events.invoke import (   # verified: BeforeInvokeEvent line 14
    BeforeInvokeEvent, AfterInvokeEvent,
)
# NEW (this feature):
from parrot.observability.context import current_agent_name, agent_identity
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(...):
    name: str                       # line 321: self.name = name (ctor arg default 'Nav' line 249)
    chatbot_id: uuid.UUID | str     # line 313/318 (NOT used by this feature)
    def _init_events(self, *, event_bus=None, forward_to_global=True) -> None:  # mixin.py:45

# packages/ai-parrot/src/parrot/bots/base.py  (public invoke entry points — wrap these)
async def conversation(self, ...)   # line 123  — emits BeforeInvokeEvent(agent_name=self.name) ~line 197
async def invoke(self, ...)         # line 501
async def ask(self, ...)            # line 727
async def ask_stream(self, ...)     # line 1310

# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):           # line 242
    # ctor calls self._init_events(forward_to_global=False)   # line 340 (ISOLATED registry)
    def _send_before(...) -> TraceContext:    # ~line 430; builds BeforeClientCallEvent line 455; emit_nowait line 465
    async def _send_after(...) -> None:       # ~line 484; builds AfterClientCallEvent line 497; await emit line 508
    async def _send_failed(...) -> None:      # ~line 523; builds ClientCallFailedEvent line 534; await emit line 544

# packages/ai-parrot/src/parrot/observability/subscribers/metrics.py
class MetricsSubscriber:
    _client_cost_total   = meter.create_counter(...)    # line 103
    _client_op_duration  = meter.create_histogram(...)  # line 122
    _client_token_usage  = meter.create_histogram(...)  # line 127
    def register(self, registry): ...                   # line 155 (subscribes the handlers)
    async def _on_client_before(self, event): ...        # line 174
    async def _on_client_after(self, event): ...         # line 185
        # base = {"gen_ai.system": system, "gen_ai.response.model": event.model}  ~line 188
        # self._client_cost_total.add(cost, attributes=base)                       ~line 217
    async def _on_client_fail(self, event): ...          # line 219

# packages/ai-parrot/src/parrot/observability/subscribers/trace.py
async def _on_client_start(self, event): ...   # line 268; attrs = build_before_client_attrs(event) line 271
async def _on_client_end(self, event):   ...   # line 274; build_after_client_attrs(event, cost_usd=cost) line 283
# invoke span already sets "parrot.agent.name": event.agent_name  # line 349

# packages/ai-parrot/src/parrot/observability/attributes.py
def build_before_client_attrs(event) -> dict[str, Any]:   # line 126
def build_after_client_attrs(event, *, cost_usd=None) -> dict: # line 150
def build_client_failed_attrs(event) -> dict[str, Any]:   # line 181

# packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py
@dataclass(frozen=True) class BeforeClientCallEvent(LifecycleEvent):  # line 18
@dataclass(frozen=True) class AfterClientCallEvent(LifecycleEvent):   # line 38
@dataclass(frozen=True) class ClientCallFailedEvent(LifecycleEvent):  # line 62

# packages/ai-parrot/src/parrot/core/events/lifecycle/base.py
class LifecycleEvent(ABC):   # line 21 — has trace_context, source_type, source_name, event_id, timestamp
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `agent_identity(self.name)` | `AbstractBot.ask/ask_stream/invoke/conversation` | `with` wrap | `bots/base.py:727/1310/501/123` |
| `current_agent_name.get()` | `AbstractClient._send_*` | read at event build | `clients/base.py:455/497/534` |
| `event.agent_name` | `MetricsSubscriber._on_client_*` | label in `base` | `subscribers/metrics.py:185/217` |
| `event.agent_name` | `build_*_client_attrs` | attr dict entry | `attributes.py:126/150/181` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.observability.context`~~ — NEW module created by this feature (no
  ContextVar for agent identity exists today; `grep` confirms only unrelated
  `current_agent_id` params in `memory/unified/routing.py` and a `_current_agent_id`
  attr read in `tools/infographic_toolkit.py`).
- ~~`AfterClientCallEvent.agent_name`~~ — does NOT exist yet (added by Module 2).
- ~~`parrot.agent.name` on client metrics/spans~~ — NOT present today; only the
  invoke span has it (`trace.py:349`).
- ~~`chatbot_id` in any lifecycle event~~ — does not exist and is out of scope.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first; ContextVars are the idiomatic async-task-local carrier. Do NOT
  use threading.local (breaks under asyncio) or instance/global mutable state.
- New event field is optional with a default → frozen dataclass stays backward
  compatible and `to_dict()` JSON-serializable (`LifecycleEvent` contract).
- Never write a `None` attribute onto a span (the builders already omit None
  values — follow that convention for `parrot.agent.name`).
- Best-effort + non-fatal: wrap the ContextVar read defensively; on any failure
  fall back to `None`/`"unknown"`. Observability must never break a call
  (mirrors the auto-boot guard in `bootstrap.py:_do_bootstrap`).

### Known Risks / Gotchas
- **Metric cardinality**: adding `parrot.agent.name` multiplies series by the
  number of agents (provider × model × agent). Bounded (dozens of agents) and
  desired — acceptable. Document it so operators with hundreds of agents can
  opt out if needed (future: a config flag; not in this spec).
- **Nesting via `create_task`**: ContextVars copy on task creation, so a child
  task sees the value set at creation time. For a sub-agent spawned as its own
  task, ensure its own invoke wrapping runs inside that task (it does — the
  public entry point wraps the body). Verified by `test_nested_agent_attribution`.
- **`emit_nowait` for BeforeClientCallEvent** (`clients/base.py:465`): the event
  is *constructed* synchronously in the bot's context (where the ContextVar is
  set) before being dispatched fire-and-forget, so `agent_name` is captured
  correctly even though the subscriber runs later.
- **Client isolated registry** (`forward_to_global=False`, line 340): the 3 call
  events are explicitly bridged to the global registry (per observability
  README "How events reach the recorder"). Do not change that bridge — the
  global `MetricsSubscriber`/trace subscriber must keep receiving the events.
- **`bots/agent.py` extra emit sites** (lines 364, 586): if `Agent` overrides
  the invoke path rather than delegating to `base.py`, apply `agent_identity`
  there too, or the wrapping in `base.py` may not cover it. Verify during impl.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (none) | — | `contextvars` is stdlib; no new third-party dependency. |

---

## 8. Open Questions

- [x] Identity grain — *Resolved by requester*: `agent_name` (= `AbstractBot.name`)
      is sufficient; it covers both Chatbots and Agents. No `chatbot_id`/UUID.
- [x] Propagation mechanism — *Resolved by requester*: ContextVar set by the bot
      and read by the client (over subscriber `trace_id→agent_name` correlation),
      for natural nesting and uniform metrics+traces attribution.
- [ ] Should `parrot.agent.name` also label the **tool** metrics
      (`_on_tool_after`, `subscribers/metrics.py:230`)? Tools run within the same
      invoke scope so the ContextVar is available. Default: include it for
      symmetry unless cardinality concerns say otherwise — *Owner: implementer,
      decide during Module 5*.
- [ ] Provide a config switch to disable the per-agent label for very-high-agent-
      count deployments? Out of scope for v1; revisit if cardinality bites —
      *Owner: Jesus Lara*.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one
  worktree. The modules form a short dependency chain
  (1 → 2 → {3,4} → {5,6}) and all touch the same observability/events/bots
  surface, so parallel worktrees would conflict and add overhead.
- **Cross-feature dependencies**: none. Builds on FEAT-176 (lifecycle events)
  and FEAT-177 (observability), both already merged.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-08 | Jesus Lara | Initial draft — ContextVar-based per-agent metric/span attribution. |
