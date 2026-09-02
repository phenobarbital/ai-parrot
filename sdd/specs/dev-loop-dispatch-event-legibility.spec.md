---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Dev-Loop Dispatch Event Legibility

**Feature ID**: FEAT-496
**Date**: 2026-09-02
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.29.0

---

## 1. Motivation & Business Requirements

### Problem Statement

A dev-loop / dev-flow run streams hundreds of events to the console
(`examples/dev_loop/server_dev.py` + `static/dev.html`), and almost none of
them say anything. The observed console output is literally:

```
dispatch.message   message_class=SystemMessage
{ "message_class": "SystemMessage" }

dispatch.tool_result   message_class=UserMessage
{ "message_class": "UserMessage", "tools": ["toolu_01DJTbBETmR3cVWEy8t9BxLu"] }
```

An operator watching a multi-hour run cannot answer the three questions that
matter: *what is the flow doing right now*, *which task is it doing it for*,
and *which sub-agent is doing it*. The DevelopmentNode — the node that does
95% of the work — reports **nothing at all** in its card.

Seven verified root causes, all on the **emission** side (the multiplexer at
`packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py` is a faithful
pipe and needs no change):

1. **Message class instead of message content.**
   `ClaudeCodeDispatcher._publish_message_event`
   (`dispatchers/claude.py:1116`) builds every payload from
   `type(message).__name__`. The SDK's `SystemMessage` — which carries the
   resolved `model`, `cwd`, `tools`, `mcp_servers`, `slash_commands` and
   `session_id` of the session that is starting — is reduced to
   `{"message_class": "SystemMessage"}`. The terminal `ResultMessage` loses
   `subtype` / `num_turns` / `duration_ms` unless `is_error` is set
   (`claude.py:1160-1164`).

2. **Opaque tool-use ids in place of tool names.** For a `ToolResultBlock`
   the same function stores `tool_use_id` into `payload["tools"]`
   (`claude.py:1149-1152`) — that is the `toolu_01DJ...` string above. The
   tool *name* was known one message earlier (on the matching
   `ToolUseBlock`) and is thrown away; no `tool_use_id → tool_name`
   correlation is kept for the life of the dispatch.

3. **A key-name mismatch that silently empties the session state.** The
   dispatcher emits `payload["tools"]` (a list), while
   `action_from_dispatch_event` (`session_state.py:1337-1338`) reads
   `payload["tool_name"]`. `DispatchToolUse.tool_name` is therefore
   **always the empty string**, for every Claude-backed dispatch that has
   ever run. Downstream, `dev.html`'s `briefOf()` (`dev.html:494-511`)
   checks `p.tool_name`, misses, and falls through to its last-resort
   `keys[0]=value` branch (`dev.html:509-510`) — which is exactly how
   `message_class=SystemMessage` ends up on screen.

4. **Raw provider events dumped under one nested key.**
   `codex.py:388-401`, `gemini.py:317-330` and `google_coding.py:393-415`
   publish `{"codex_event": {...}}` / `{"gemini_event": {...}}` /
   `{"agy_event": {...}}`. `briefOf`'s fallback renders these as
   `codex_event=[object Object]`. Only `dispatchers/llm.py` (and its
   Nova/Grok/Z.ai/Moonshot subclasses) publishes usable payloads today —
   `tool_name`, `arguments`, `result`, `turn` (`llm.py:352-508`).

5. **No task identity anywhere, and the DevelopmentNode card is empty.**
   No event kind, on any backend, carries the `TASK-<NNN>` being worked on.
   Worse, pool seats dispatch with `node_id="development.w1"`
   (`agent_pool.py:293`), `_owning_node_id` (`dispatchers/_shared.py:53-74`)
   rolls the seat up to `"development"` for session state, and
   `nodesForRender` (`dev.html:995-1009`) only reads
   `app.events.get(n.id)` for the ten fixed `TOPOLOGY.dev` ids
   (`dev.html:384-397`). Every `development.w1` / `development.w2` /
   `development.resolver` event is received over the socket, stored in
   `app.events` (`dev.html:649-651`), and **never rendered** — the card
   says *"This node has not been dispatched yet"* (`dev.html:1013`) for the
   entire run.

6. **N judges, one indistinguishable stream.**
   `JudgePanelReviewDispatcher.review` (`code_review.py:775-800`) fans out
   every judge concurrently with the same `node_id=node_id` (`"qa"`), so
   the panel's events interleave on one stream with no way to tell which
   judge produced which. `JudgeVerdictRecorded` only lands at the *end*, so
   during the review there is no per-judge signal at all.

7. **`google_coding` events never reach the UI or session state at all.**
   Found while decomposing this spec (2026-09-02). Unlike the other four,
   `GoogleCodingDispatcher._publish_event` (`google_coding.py:77-99`) does
   **not** build a `DispatchEvent` and does **not** XADD a single `"event"`
   field — it writes five flat fields (`kind`, `run_id`, `node_id`,
   `timestamp`, `payload`-as-JSON-string). `FlowStreamMultiplexer._envelope`
   (`streaming.py:497-506`) looks for `fields["event"]`, does not find it,
   and takes the fallback branch: **every `agy` dispatch event surfaces in
   the console as `event_kind="flow.unknown"`** with the raw field dict as
   its payload. The same method also never calls `_apply_to_session_host`,
   so an `agy`-backed dispatch contributes nothing to session state — no
   status, no `message_count`, no `tool_use_count`. This is a distinct
   defect from causes 1–6 (a wire-format divergence, not a thin payload)
   and is fixed as part of Module 4c.

### Goals

- **G1** — Every event published by every dev-loop dispatcher carries a
  display-ready, human-legible `summary` string, so the console never has
  to guess a gist from raw keys.
- **G2** — Tool events carry the tool **name** (not an opaque id) plus a
  compact input digest (the file path, the command, the pattern), and a
  tool result is correlated back to the tool that produced it.
- **G3** — Every event carries the identity of the work it belongs to:
  `task_id`, `task_title`, `seat`, `agent`, `model`, `subagent`. An
  operator can read *which TASK-`<NNN>` on which seat* off any single event.
- **G4** — The DevelopmentNode card shows its pool: one row per seat, each
  naming the task it is running, with that seat's events rendered under it.
- **G5** — The QA judge panel is attributable per judge while it runs.
- **G6** — `DispatchToolUse.tool_name` is actually populated in session
  state, for every backend.
- **G7** — Backends reach parity: `claude-code`, `codex`, `gemini`,
  `google_coding` and the `llm` family all emit the same normalized
  payload contract.
- **G8** — Every backend publishes in the **same wire format**, so no
  backend's events arrive as `flow.unknown` or bypass session state.

### Non-Goals (explicitly out of scope)

- Changing the wire transport. The multiplexer, the Redis stream layout
  (`flow:{run_id}:dispatch:{node_id}`), the `{source, node_id, event_kind,
  ts, payload}` envelope and the WebSocket views stay exactly as they are.
- Streaming full tool outputs or full assistant text to the console. The
  AHP lazy-loading rule holds: session state and event payloads carry
  display-ready projections; heavy content stays by reference on the
  terminal channel.
- New event *kinds*. The `DispatchEvent.kind` Literal
  (`models/base.py:745-754`) is unchanged — this feature enriches payloads,
  it does not add a taxonomy.
- Reworking `examples/dev_loop/static/afd.html`. It does not render a node
  event log and is untouched. (`index.html`, the bug/feature-mode console,
  **is** in scope — see §8's resolved question and Module 9.)
- Persisting a per-seat projection into `DevLoopSessionState.nodes` keyed by
  seat. `NodeId` is a closed `Literal` (`session_state.py:140-159`) and
  widening it is a breaking change to every persisted envelope; see §2
  "Seat projection" for the chosen alternative.

---

## 2. Architectural Design

### Overview

The fix is a **single normalized payload contract**, produced by one shared
helper, adopted by all five dispatchers, stamped automatically with the
identity of the work in flight, and finally *read* by the console.

Four layers, in dependency order:

**Layer 1 — `DispatchLabels`: who/what, stamped once per dispatch.**
A new frozen Pydantic model carrying `task_id`, `task_title`, `task_file`,
`seat`, `agent`, `model`, `subagent`, `judge_id`, `attempt`. It is passed to
`dispatch()` as a new optional keyword argument and bound into a
`ContextVar` for the duration of the call — reusing verbatim the pattern
`_SESSION_HOST_CTX` already established for `session_host`
(`dispatchers/_shared.py:30-51`), and for the same stated reason: every
dispatcher already funnels *all* of its publishing through a single
`_publish_event` choke point, so a ContextVar read there stamps ~40 call
sites across 5 classes without threading a parameter through every internal
helper. `ContextVar` values are copied per `asyncio.Task`, so concurrent
seats on a shared dispatcher instance never observe each other's labels.

**Layer 2 — `normalize_payload()`: the display contract.**
A pure function in `dispatchers/_shared.py` that takes a raw
backend-specific payload plus the event kind and returns a payload
guaranteed to contain a `summary` (one line, ≤ 160 chars, human-readable)
and, where applicable, `tool_name` and `tool_input`. It never mutates or
drops the backend's own keys — `codex_event`, `agy_event`, `gemini_event`,
`message_class` and friends all survive for the expanded-JSON view; the
normalizer only *adds* the display projection on top. Called from
`_publish_event` in each dispatcher, so enrichment and label stamping
happen at the same single point.

**Layer 3 — per-backend extractors.**
Small, well-tested functions that map one backend's raw event onto
`(tool_name, tool_input, text, summary)`:

- `claude.py` — walk the content blocks properly: `ToolUseBlock` →
  `tool_name` + a digest of `block.input`; `ToolResultBlock` → resolve
  `tool_use_id` through a **per-dispatch correlation map** back to the
  originating tool name, plus `is_error` and a truncated result snippet;
  `TextBlock` / `ThinkingBlock` → a text snippet; `SystemMessage` →
  `subtype`, `model`, `cwd`, tool/mcp counts; `ResultMessage` → `subtype`,
  `num_turns`, `duration_ms`, `total_cost_usd`.
- `codex.py` — read `event["item"]["type"]` and the item's own fields
  (`command`, `path`, `status`, `aggregated_output`) instead of nesting the
  whole event.
- `gemini.py` — read `event["type"]`, `name`, `args`, `response`.
- `google_coding.py` — read `step_update.step_type`, `tool_call.name`,
  `text_delta`.
- `llm.py` — already emits `tool_name`/`arguments`/`result`; it only needs
  the `summary` line and label stamping.

**Layer 4 — the console reads it.**
`briefOf` (`dev.html:494`) gains one leading branch: `if (p.summary) return
p.summary`. `nodesForRender` learns that a node id owns every event whose
`node_id` is `"<id>"` **or** starts with `"<id>."`, and groups the seat
events into per-seat sub-sections with a seat + task badge derived from the
stamped labels. Nothing else in the console changes.

**Seat projection (why not a new NodeId).** `NodeId`
(`session_state.py:140`) is a closed `Literal` and appears in every
persisted `ActionEnvelope`; widening it to accept `development.w1` would
invalidate replay of existing runs and is rejected. Instead the
`DispatchState` model (`session_state.py:188`) gains an optional
`seats: Dict[str, SeatState]` map, populated by the same
`_apply_to_session_host` shim that already rolls seats up — it keeps the
existing roll-up (so `message_count` / `tool_use_count` aggregates are
unchanged) **and** additionally records the per-seat detail under the
owning node. Optional-with-default, so pre-FEAT-496 envelopes re-validate
untouched.

### Component Diagram

```
                        DevelopmentNode / QANode / JudgePanel
                                     │  builds DispatchLabels
                                     ▼
   DevAgentPool._dispatch_one ──► dispatcher.dispatch(..., labels=)
                                     │
                                     │  binds _DISPATCH_LABELS_CTX
                                     ▼
                          ┌── <Backend>Dispatcher ──┐
                          │  raw provider events    │
                          │           │             │
                          │           ▼             │
                          │  _extract_display()  ◄──┼── per-backend, Layer 3
                          │           │             │
                          │           ▼             │
                          │     _publish_event()    │  ← single choke point
                          └───────────┬─────────────┘
                                      │
                     normalize_payload(kind, payload)   ← Layer 2
                     + stamp DispatchLabels             ← Layer 1
                                      │
                    ┌─────────────────┴──────────────────┐
                    ▼                                    ▼
        _apply_to_session_host(event)            redis XADD
        (roll-up + NEW per-seat detail)          flow:{run}:dispatch:{node}
                    │                                    │
                    ▼                                    ▼
             SessionHost state  ──────────────►  FlowStreamMultiplexer
                                                         │
                                                         ▼
                                                  dev.html console
                                          briefOf(summary) + seat grouping
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DevLoopCodeDispatcher` (Protocol, `_shared.py:128`) | extends signature | new optional `labels: Optional[DispatchLabels] = None` kwarg — additive, defaulted, so every existing caller keeps working |
| `_SESSION_HOST_CTX` pattern (`_shared.py:48`) | mirrors | a sibling `_DISPATCH_LABELS_CTX`, set/reset in the same `try/finally` blocks |
| `_apply_to_session_host` (`_shared.py:76`) | extends | keeps the roll-up, additionally folds per-seat detail |
| `ClaudeCodeDispatcher._publish_event` (`claude.py:1077`) | wraps | calls `normalize_payload` before building the `DispatchEvent` |
| `CodexCodeDispatcher._publish_event` (`codex.py:517`) | wraps | idem |
| `GeminiCodeDispatcher._publish_event` (`gemini.py:454`) | wraps | idem |
| `GoogleCodingDispatcher._publish_event` (`google_coding.py:77`) | wraps | idem |
| `LLMCodeDispatcher._publish_event` (`llm.py:2395`) | wraps | idem; covers Nova/Grok/Z.ai/Moonshot by inheritance |
| `DevAgentPool._dispatch_one` (`agent_pool.py:225`) | passes labels | `TaskRef.id` / `.title` / `.file` + `worker.worker_id` + `worker.spec.agent` / `.model` |
| `DevelopmentNode._resolve_conflict` (`development.py:1309`) | passes labels | seat `development.resolver`, `task_id="RESOLVE_MERGE_CONFLICT"` |
| `AbstractCodeReviewDispatcher.review` (`code_review.py:108`) | passes labels | `judge_id` + backend + model |
| `JudgePanelReviewDispatcher.review` (`code_review.py:775`) | passes labels | one `DispatchLabels` per judge in the `asyncio.gather` fan-out |
| `DispatchState` (`session_state.py:188`) | extends | optional `seats` map |
| `action_from_dispatch_event` (`session_state.py:1315`) | fixes | now finds `tool_name` because the dispatchers emit it |
| `dev.html` `briefOf` / `nodesForRender` | extends | summary branch + seat grouping |
| `FlowStreamMultiplexer` (`streaming.py`) | **untouched** | pure pass-through; listed so no task edits it |

### Data Models

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py

class DispatchLabels(BaseModel):
    """Identity of the work a dispatch is doing (FEAT-496).

    Stamped onto every DispatchEvent payload published during the
    dispatch, so any single event answers "what task, which seat, which
    agent". Every field defaults to empty — a dispatch without labels
    publishes exactly the payloads it publishes today, minus the labels.
    """

    model_config = ConfigDict(frozen=True)

    task_id: str = ""        # "TASK-1857", or "RESOLVE_MERGE_CONFLICT"
    task_title: str = ""     # human title from the per-spec index
    task_file: str = ""      # "sdd/tasks/active/TASK-1857-<slug>.md"
    seat: str = ""           # "development.w1" | "development.resolver" | ""
    agent: str = ""          # "claude-code" | "codex" | "gemini" | ...
    model: str = ""          # resolved model id
    subagent: str = ""       # "sdd-worker", "sdd-qa", "sdd-secondopinion"
    judge_id: str = ""       # QA panel attribution
    attempt: int = 1         # QA repair-loop attempt / retry number

    def as_payload(self) -> Dict[str, Any]:
        """Non-empty fields only — never pads a payload with blanks."""


class SeatState(_Frozen):     # session_state.py
    """Per-seat detail under a node's DispatchState (FEAT-496)."""

    seat: str
    task_id: str = ""
    task_title: str = ""
    agent: str = ""
    model: str = ""
    status: DispatchStatus = "queued"
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    message_count: int = 0
    tool_use_count: int = 0
    last_tool: str = ""
    last_summary: str = ""
    last_error: str = ""


class DispatchState(_Frozen):     # EXTENDED — session_state.py:188
    ...                            # every existing field unchanged
    seats: Dict[str, SeatState] = Field(default_factory=dict)
```

**Normalized payload contract** (the keys `normalize_payload` guarantees;
backend-specific keys are preserved alongside them):

| Key | Type | Present on | Meaning |
|---|---|---|---|
| `summary` | `str` | **every** event | one line, ≤ 160 chars, human-readable |
| `tool_name` | `str` | `tool_use`, `tool_result` | `"Read"`, `"Bash"`, `"shell"` — never an id |
| `tool_input` | `str` | `tool_use` | compact digest: path, command, pattern |
| `tool_use_id` | `str` | `tool_use`, `tool_result` | correlation id, kept for pairing |
| `is_error` | `bool` | `tool_result`, `failed` | result/dispatch failed |
| `text` | `str` | `message` | assistant/thinking snippet (≤ 400 chars) |
| `task_id`, `seat`, `agent`, `model`, … | `str` | every event, when labelled | from `DispatchLabels.as_payload()` |

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py

_DISPATCH_LABELS_CTX: ContextVar[Optional[DispatchLabels]]

def current_labels() -> Optional[DispatchLabels]:
    """Return the labels bound by the active dispatch() call, if any."""

def bind_labels(labels: Optional[DispatchLabels]) -> contextvars.Token:
    """Bind labels for the duration of a dispatch. Mirrors the
    _SESSION_HOST_CTX set/reset discipline."""

def normalize_payload(kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return `payload` plus the guaranteed display keys and the active
    dispatch's labels. Never raises; never removes an existing key."""

def summarize_tool_input(tool_name: str, tool_input: Any,
                         *, max_chars: int = 120) -> str:
    """Compact one-line digest of a tool's arguments."""


# Protocol change — _shared.py:131
class DevLoopCodeDispatcher(Protocol):
    async def dispatch(
        self, *, brief: BaseModel, profile: BaseModel,
        output_model: Type[T], run_id: str, node_id: str, cwd: str,
        session_host: Optional[SessionHost] = None,
        labels: Optional[DispatchLabels] = None,   # NEW — additive
    ) -> T: ...
```

---

## 3. Module Breakdown

### Module 1: `DispatchLabels` model + shared label context

- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py`
- **Responsibility**: define `DispatchLabels`; add `_DISPATCH_LABELS_CTX`,
  `bind_labels()`, `current_labels()`. No dispatcher wiring yet.
- **Depends on**: nothing (foundation module).

### Module 2: `normalize_payload` + `summarize_tool_input`

- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py`
- **Responsibility**: the Layer-2 normalizer — guarantee `summary`, stamp
  labels, preserve every backend key, never raise.
- **Depends on**: Module 1.

### Module 3: Claude dispatcher extractor + tool correlation

- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py`
- **Responsibility**: rewrite `_publish_message_event` (`:1116`) to walk
  blocks properly; add a per-dispatch `tool_use_id → tool_name` map (bound
  in `dispatch()` alongside the existing ContextVars, so concurrent seats
  do not share it); enrich `SystemMessage` / `ResultMessage`; route
  `_publish_event` (`:1077`) through `normalize_payload`; accept and bind
  `labels`.
- **Depends on**: Modules 1, 2.

### Module 4: Codex / Gemini / GoogleCoding extractors

- **Path**: `dispatchers/codex.py`, `dispatchers/gemini.py`,
  `dispatchers/google_coding.py`
- **Responsibility**: replace the single-nested-key payloads
  (`codex.py:388`, `gemini.py:317`, `google_coding.py:393`) with extracted
  `tool_name` / `tool_input` / `text` **plus** the preserved raw event;
  route each `_publish_event` through `normalize_payload`; accept and bind
  `labels`.
- **Depends on**: Modules 1, 2.

### Module 5: LLM-family parity

- **Path**: `dispatchers/llm.py` (inherited by `nova.py`, `grok.py`,
  `zai.py`, `moonshot.py`)
- **Responsibility**: route `_publish_event` (`llm.py:2395`) through
  `normalize_payload`; accept and bind `labels` in `LLMCodeDispatcher.dispatch`
  (`:110`) and in each subclass's overriding `dispatch` (`nova.py:219`,
  `grok.py:52`, `zai.py:96`, `moonshot.py:111`).
- **Depends on**: Modules 1, 2.

### Module 6: Session-state seat projection

- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py`,
  `dispatchers/_shared.py`
- **Responsibility**: add `SeatState`; add `DispatchState.seats`; extend
  `reduce()` (`:748`) to fold seat detail; extend
  `action_from_dispatch_event` (`:1315`) to carry `seat` / `task_id` /
  `summary` onto the dispatch actions; extend `_apply_to_session_host`
  (`_shared.py:76`) to keep the roll-up **and** record seat detail.
- **Depends on**: Modules 1, 2.

### Module 7: Pool, resolver and judge-panel wiring

- **Path**: `agent_pool.py`, `nodes/development.py`, `code_review.py`,
  `nodes/qa.py`
- **Responsibility**: build and pass `DispatchLabels` at
  `agent_pool.py:288` (from `TaskRef` + `PoolWorker`),
  `development.py:1359`/`:1381` (resolver seat), and
  `code_review.py:775-800` (one per judge, carrying `judge_id`).
- **Depends on**: Modules 1, 3, 4, 5.

### Module 8: Console — summary + seat grouping (`dev.html`)

- **Path**: `examples/dev_loop/static/dev.html`
- **Responsibility**: `briefOf` (`:494`) prefers `p.summary`;
  `nodesForRender` (`:995`) collects `node_id === id || node_id.startsWith(id + ".")`;
  `eventRowsHtml` (`:1011`) renders a seat + task badge per row;
  `nodeMetaHtml` (`:1031`) renders the seat table from `dispatch.seats`.
- **Depends on**: Modules 2, 6, 7.

### Module 9: Console parity — `index.html`

- **Path**: `examples/dev_loop/static/index.html`
- **Responsibility**: apply the identical Module 8 treatment to the
  bug/feature-mode console, which carries its own copy of every one of
  those functions at different line numbers: `briefOf` (`:447`, `tool_name`
  at `:455`, the `keys[0]` fallback at `:463`), `foldAction` (`:498`),
  the `app.events` keying (`:602-604`), `nodesForRender` (`:774-788`, whose
  `TOPOLOGY[app.mode]` at `:775` covers both the `bug` and `feature`
  topologies at `:336-350`), `eventRowsHtml` (`:790`, the "not been
  dispatched yet" string at `:792`) and `nodeMetaHtml` (`:810-818`).
  Deliberately a separate module from Module 8: same change, different
  file, no shared symbols — so the two can run on different seats.
  **No divergence permitted** — if Module 8 changes the seat-grouping rule
  or the badge shape, this module matches it exactly.
- **Depends on**: Module 8 (adopts its resolved rendering decisions rather
  than re-deciding them).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_dispatch_labels_as_payload_omits_empty` | 1 | only non-empty fields reach the payload |
| `test_labels_ctx_is_task_local` | 1 | two concurrent `asyncio.Task`s never see each other's labels |
| `test_normalize_payload_always_has_summary` | 2 | every `DispatchEvent.kind` yields a non-empty `summary` |
| `test_normalize_payload_preserves_backend_keys` | 2 | `codex_event` / `message_class` survive normalization |
| `test_normalize_payload_never_raises` | 2 | malformed/`None`/deeply-nested payloads degrade, never raise |
| `test_summarize_tool_input_digests` | 2 | `Read{file_path}` → path; `Bash{command}` → command; long input truncated |
| `test_claude_tool_use_emits_tool_name` | 3 | `ToolUseBlock` → `payload["tool_name"] == "Read"` (the FEAT-496 key-mismatch fix) |
| `test_claude_tool_result_resolves_name` | 3 | `ToolResultBlock` with a known `tool_use_id` reports the originating tool name, not `toolu_…` |
| `test_claude_tool_result_unknown_id` | 3 | an unpaired `tool_use_id` degrades to a summary, never crashes |
| `test_claude_system_message_enriched` | 3 | `SystemMessage` payload carries `subtype`/`model`/`cwd` and a real summary |
| `test_claude_result_message_enriched` | 3 | terminal `ResultMessage` carries `num_turns`/`duration_ms` on the success path |
| `test_claude_correlation_map_is_per_dispatch` | 3 | two concurrent dispatches do not cross-resolve tool ids |
| `test_codex_event_extracts_tool_name` | 4 | `item.started`/`item.completed` → `tool_name` + `tool_input`, raw event preserved |
| `test_gemini_event_extracts_tool_name` | 4 | `tool_call`/`tool_response` → `tool_name`, raw event preserved |
| `test_agy_event_extracts_tool_name` | 4 | `step_update.tool_call` → `tool_name`, raw event preserved |
| `test_llm_dispatch_stamps_labels` | 5 | `tool_use` payload carries `task_id` + `seat` |
| `test_seat_state_folded_under_owning_node` | 6 | a `development.w1` event updates `nodes["development"].dispatch.seats["development.w1"]` **and** the roll-up counters |
| `test_dispatch_state_seats_defaults_empty` | 6 | a pre-FEAT-496 persisted `ActionEnvelope` still validates |
| `test_action_from_dispatch_event_tool_name` | 6 | `DispatchToolUse.tool_name` is populated from a real Claude-shaped payload |
| `test_pool_dispatch_passes_labels` | 7 | `_dispatch_one` forwards `task_id`/`task_title`/`seat`/`agent`/`model` |
| `test_judge_panel_labels_per_judge` | 7 | each judge in the fan-out gets its own `judge_id` |

### Integration Tests

| Test | Description |
|---|---|
| `test_claude_dispatch_stream_is_legible` | drive the fake SDK message sequence already used by the dispatcher tests; assert every published event has a non-empty `summary` and that **no** payload's only key is `message_class` |
| `test_pool_wave_events_carry_task_identity` | run a 2-seat, 2-task fake wave; assert every dispatch event carries the correct `task_id` for its seat |
| `test_multiplexer_passes_enriched_payload_through` | enriched payload survives `FlowStreamMultiplexer` unchanged (guards against a regression that strips keys) |

### Test Data / Fixtures

```python
# Reuse the existing fake-SDK/fake-subprocess fixtures already present in
# packages/ai-parrot/tests/flows/dev_loop/ — e.g. the message doubles in
# test_codex_dispatcher.py, test_gemini_dispatcher.py,
# test_llm_code_dispatcher.py and test_dual_publish.py. New fixtures:

@pytest.fixture
def claude_tool_cycle():
    """AssistantMessage(ToolUseBlock 'Read', id 'toolu_x') followed by
    UserMessage(ToolResultBlock tool_use_id='toolu_x') — the exact shape
    that produced the unreadable console output."""

@pytest.fixture
def dispatch_labels():
    return DispatchLabels(task_id="TASK-1857", task_title="Wire the shim",
                          seat="development.w1", agent="claude-code")
```

---

## 5. Acceptance Criteria

- [ ] **AC1** — No published dispatch event, on any backend, has a payload
      whose only informative key is a class name. Asserted by
      `test_claude_dispatch_stream_is_legible`.
- [ ] **AC2** — Every `dispatch.*` payload contains a non-empty `summary`
      string of ≤ 160 characters.
- [ ] **AC3** — `dispatch.tool_use` payloads contain `tool_name` (a real
      tool name) and `tool_input` (a compact digest); `dispatch.tool_result`
      payloads contain the **originating tool's name**, never a bare
      `toolu_…` id.
- [ ] **AC4** — `DispatchToolUse.tool_name` in session state is populated
      for a Claude-shaped `tool_use` event (the `payload["tools"]` vs
      `payload["tool_name"]` mismatch is gone).
- [ ] **AC5** — Every event dispatched by a pool seat carries `task_id`,
      `task_title`, `seat`, `agent` and `model`.
- [ ] **AC6** — `nodes["development"].dispatch.seats` reports one entry per
      active seat, each naming its current task; the existing roll-up
      counters (`message_count`, `tool_use_count`) are unchanged in value.
- [ ] **AC7** — In `dev.html`, the Development card renders its seats and
      their events; it never shows *"This node has not been dispatched
      yet"* while seats are running.
- [ ] **AC7b** — `index.html` behaves identically to `dev.html` on both its
      `bug` and `feature` topologies: `briefOf` prefers `summary`, seat
      events render under their owning node, and no rendering decision
      diverges from Module 8.
- [ ] **AC8** — Each QA judge's events are attributable via `judge_id`.
- [ ] **AC9** — `codex`, `gemini` and `google_coding` events expose
      `tool_name`/`summary` while still carrying their raw provider event
      for the expanded JSON view.
- [ ] **AC9b** — A `google_coding` dispatch event reaches
      `FlowStreamMultiplexer` with its real `event_kind` (never
      `"flow.unknown"`) and folds into session state through
      `_apply_to_session_host`, exactly like the other four backends.
- [ ] **AC10** — A publishing/normalization failure never breaks a
      dispatch: `normalize_payload` is total, and the existing swallow-and-log
      discipline in `_publish_event` / `_apply_to_session_host` is preserved.
- [ ] **AC11** — Backward compatibility: an `ActionEnvelope` persisted
      before FEAT-496 still validates and replays (`DispatchState.seats`
      defaults to `{}`); every `dispatch()` caller that omits `labels`
      still works.
- [ ] **AC12** — All existing tests pass:
      `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] **AC13** — `ruff check` and the project's type checks pass on every
      changed file.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every entry below was verified by reading the file at the stated line on
> 2026-09-02, on `dev` @ `352edd8a6`.

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py:19-20
from parrot.flows.dev_loop.models import DispatchEvent
from parrot.flows.dev_loop.session_state import SessionHost, action_from_dispatch_event

# verified: dispatchers/claude.py:50 (imports _SESSION_HOST_CTX from _shared)
from parrot.flows.dev_loop.dispatchers._shared import _SESSION_HOST_CTX

# verified: agent_pool.py:47
from parrot.flows.dev_loop.task_scheduler import TaskRef

# verified: session_state.py:1274-1276 (_DISPATCH_KIND_MAP entries)
from parrot.flows.dev_loop.session_state import (
    DispatchDelta, DispatchToolUse, DispatchToolResult,
)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py
_SESSION_HOST_CTX: ContextVar[Optional[SessionHost]]          # line 48
def _owning_node_id(node_id: str) -> str:                     # line 53
    return node_id.split(".", 1)[0]                           # line 74
def _apply_to_session_host(event: DispatchEvent) -> None:     # line 76

class DevLoopCodeDispatcher(Protocol):                        # line 128
    async def dispatch(                                       # line 131
        self, *, brief: BaseModel, profile: BaseModel,
        output_model: Type[T], run_id: str, node_id: str, cwd: str,
        session_host: Optional[SessionHost] = None,           # line 140
    ) -> T: ...

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py
class ClaudeCodeDispatcher:                                   # line 94
    async def dispatch(...)                                   # line 170
    #   stream_key = f"flow:{run_id}:dispatch:{node_id}"       # line 204
    #   _host_token = _SESSION_HOST_CTX.set(session_host)      # line 211
    #   _SESSION_HOST_CTX.reset(_host_token)                   # lines 231, 456
    async def _ensure_redis(self) -> Any:                     # line 1066
    async def _publish_event(self, stream_key, *, kind, run_id,
                             node_id, payload) -> None:       # line 1077
    async def _publish_message_event(self, stream_key, message,
                                     run_id, node_id) -> None:# line 1116
    #   payload = {"message_class": type(message).__name__}    # line 1136-1138
    #   ToolUseBlock  -> kind = "dispatch.tool_use"            # line 1146
    #   ToolResultBlock -> tool_use_id appended to tool_names  # line 1149-1152
    #   payload["tools"] = tool_names                          # line 1156-1157

# dispatchers/codex.py
class CodexCodeDispatcher:                                    # line 38
    _TOOL_ITEM_TYPES = {...}                                  # line 46
    async def dispatch(...)                                   # line 70
    async def _publish_codex_event(...)                       # line 388
    #   payload={"codex_event": event}                         # line 399
    def _codex_event_kind(self, event) -> str:                # line 403
    async def _publish_event(...)                             # line 517

# dispatchers/gemini.py
class GeminiCodeDispatcher:                                   # line 38
    async def dispatch(...)                                   # line 75
    async def _publish_gemini_event(...)                      # line 317
    #   payload={"gemini_event": event}                        # line 328
    def _gemini_event_kind(self, event) -> str:               # line 332
    async def _publish_event(...)                             # line 454

# dispatchers/google_coding.py
class GoogleCodingDispatcher:                                 # line 41
    async def _publish_event(...)                             # line 77
    async def dispatch(...)                                   # line 100
    async def _publish_agy_event(...)                         # line 393
    #   payload={"agy_event": event}                           # line 414

# dispatchers/llm.py
class LLMCodeDispatcher:                                      # line 48
    async def dispatch(...)                                   # line 110
    #   emits dispatch.message  {"turn", "text"}               # line 353-360
    #   emits dispatch.tool_use {"tool_call_id","tool_name",
    #                            "arguments"}                  # line 445-455
    #   emits dispatch.tool_result {"tool_call_id","tool_name",
    #                               "result"}                  # line 500-510
    @staticmethod
    def _tool_call_id(call: Any) -> str:                      # line 2168
    @staticmethod
    def _tool_call_name(call: Any) -> str:                    # line 2172
    async def _publish_event(...)                             # line 2395

# Subclasses that override dispatch() and must also accept `labels`:
#   dispatchers/nova.py:61   NovaCodeDispatcher(LLMCodeDispatcher)  -> dispatch at :219
#   dispatchers/grok.py:16   GrokCodeDispatcher(LLMCodeDispatcher)  -> dispatch at :52
#   dispatchers/zai.py:18    ZaiCodeDispatcher(LLMCodeDispatcher)   -> dispatch at :96
#   dispatchers/moonshot.py:18 MoonshotCodeDispatcher(LLMCodeDispatcher) -> dispatch at :111

# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class DispatchEvent(BaseModel):                               # line 735
    kind: Literal["dispatch.queued", "dispatch.started",      # lines 745-754
                  "dispatch.message", "dispatch.tool_use",
                  "dispatch.tool_result", "dispatch.output_invalid",
                  "dispatch.failed", "dispatch.completed"]
    ts: float; run_id: str; node_id: str
    payload: Dict[str, Any]
class WorkerSummary(BaseModel):                               # line 481
    worker_id: str; agent: str; model: str                    # lines 489-491
    tasks_completed: List[str]; tasks_failed: List[str]       # lines 492-493
    summary: str                                              # line 494

# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
NodeId = Literal[...]                                         # line 140-159 (CLOSED)
class DispatchState(_Frozen):                                 # line 188
    status: DispatchStatus; dispatcher: str                   # lines 197-198
    started_at / finished_at: Optional[float]                 # lines 199-200
    message_count: int; tool_use_count: int                   # lines 201-202
    last_error: str; terminal: str                            # lines 203-204
class NodeState(_Frozen):                                     # line 216
    node_id: NodeId; status: NodeStatus                       # lines 219-220
    dispatch: Optional[DispatchState]                         # line 224
    summary: Dict[str, str]                                   # line 227
class DispatchDelta(_DispatchAction)                          # line 411
class DispatchToolUse(_DispatchAction): tool_name: str = ""   # lines 418-420
class DispatchToolResult(_DispatchAction)                     # line 423
def reduce(state, action)                                     # line 748
class SessionHost                                             # line 999
_DISPATCH_KIND_MAP: Dict[str, type]                           # line 1271
def action_from_dispatch_event(kind, node_id, ts,
                               payload=None)                  # line 1315
#   kwargs["tool_name"] = str(payload.get("tool_name", ""))    # line 1337-1338

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py
@dataclass
class PoolWorker:                                             # line 73
    worker_id: str; spec: DevAgentSpec                        # lines 85-86
    dispatcher: DevLoopCodeDispatcher; profile: BaseModel     # lines 87-88
@dataclass
class WaveResult:                                             # line 91
class DevAgentPool:                                           # line 107
    def build(...)                                            # line 129
    async def _dispatch_one(self, task: TaskRef, worker: PoolWorker, *,
        research, run_id, cwd_for, escalate=False,
        session_host=None) -> _DispatchAttempt                # line 225
    #   await worker.dispatcher.dispatch(..., node_id=worker.worker_id,
    #       cwd=cwd_for(worker.worker_id), session_host=...)   # lines 288-295
    async def run_wave(...)                                   # line 371

# packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py
class TaskRef(BaseModel):                                     # line 25
    id: str; title: str = ""; status: str                     # lines 33-37
    depends_on: List[str]; file: str = ""                     # lines 38-49

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py
    @staticmethod
    def _task_label(task: TaskRef) -> str                     # line 1069
    @staticmethod
    def _find_feature_slug(worktree_path, feat_id)            # line 1081
    async def _resolve_conflict(...)                          # line 1309
    #   node_id="development.resolver"                         # lines 1359, 1381

# packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py
class AbstractCodeReviewDispatcher(ABC):                      # line 87
    async def review(self, *, brief, run_id, node_id, cwd,
                     session_host=None, round="")             # line 108
class JudgePanelReviewDispatcher(AbstractCodeReviewDispatcher)# line 574
    def _build_judge(self, spec) -> Tuple[str, Abstract...]   # line 712
    async def review(...)                                     # line 775
    #   asyncio.gather over judges, all with node_id=node_id   # lines 786-800

# packages/ai-parrot/src/parrot/flows/dev_loop/flow.py
class FlowEventPublisher:                                     # line 212
    #   envelope payload strips only "flow"/"context"          # line 258

# packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py — NOT MODIFIED
#   envelope: {"source", "node_id", "event_kind", "ts", "payload"}  # lines 16-17, 519-522
```

```javascript
// examples/dev_loop/static/dev.html
const TOPOLOGY = { dev: [ ...10 fixed node ids... ] }        // line 384-397
function briefOf(kind, p)                                     // line 494
//   if (p.tool_name) return String(p.tool_name);             // line 502
//   const keys = Object.keys(p);                             // line 509
//   return keys.length ? `${keys[0]}=${...}` : "";           // line 510  ← the bug's surface
function adoptSnapshot(snap)                                  // line 520
function foldAction(a)                                        // line 545
//   case "dispatch/tool_use": ... tool_use_count += 1        // line 575-576
function connect(runId)                                       // line 639
//   app.events keyed by env.node_id (seats included)         // lines 648-651
function nodesForRender()                                     // line 995
//   const events = app.events.get(n.id) || [];               // line 999  ← seats dropped
function eventRowsHtml(nodeId, events)                        // line 1011
//   "This node has not been dispatched yet."                 // line 1013
function nodeMetaHtml(n)                                      // line 1031

// examples/dev_loop/static/index.html — an INDEPENDENT copy of the same
// functions at different line numbers. Nothing is shared between the two
// consoles; both must be edited.
const TOPOLOGY = { bug: [...8 ids...], feature: [...] }      // line 336-350
function briefOf(kind, p)                                     // line 447
//   if (p.tool_name) return String(p.tool_name);             // line 455
//   return keys.length ? `${keys[0]}=${...}` : "";           // line 463  ← same bug surface
function foldAction(a)                                        // line 498
//   app.events keyed by env.node_id (seats included)         // lines 602-604
function nodesForRender()                                     // line 774
//   const spec = TOPOLOGY[app.mode] || TOPOLOGY.bug;         // line 775  ← two topologies
//   const events = app.events.get(n.id) || [];               // line 778  ← seats dropped
function eventRowsHtml(nodeId, events)                        // line 790
//   "This node has not been dispatched yet."                 // line 792
function nodeMetaHtml(n)                                      // line 810-818
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `DispatchLabels` | `DevLoopCodeDispatcher.dispatch()` | new kwarg | `dispatchers/_shared.py:131` |
| `_DISPATCH_LABELS_CTX` | `_SESSION_HOST_CTX` set/reset sites | same `try/finally` | `claude.py:211,231,456` |
| `normalize_payload()` | `ClaudeCodeDispatcher._publish_event` | call before `DispatchEvent(...)` | `claude.py:1077-1091` |
| `normalize_payload()` | `CodexCodeDispatcher._publish_event` | idem | `codex.py:517` |
| `normalize_payload()` | `GeminiCodeDispatcher._publish_event` | idem | `gemini.py:454` |
| `normalize_payload()` | `GoogleCodingDispatcher._publish_event` | idem | `google_coding.py:77` |
| `normalize_payload()` | `LLMCodeDispatcher._publish_event` | idem | `llm.py:2395` |
| `SeatState` | `DispatchState` | new optional field | `session_state.py:188` |
| seat fold | `_apply_to_session_host` | after existing roll-up | `_shared.py:76-99` |
| labels build | `DevAgentPool._dispatch_one` | `TaskRef` + `PoolWorker` | `agent_pool.py:267,288-295` |
| labels build | `DevelopmentNode._resolve_conflict` | resolver seat | `development.py:1350-1381` |
| labels build | `JudgePanelReviewDispatcher.review` | per-judge in `gather` | `code_review.py:786-800` |
| `p.summary` branch | `briefOf` | first branch | `dev.html:494-511` |
| seat grouping | `nodesForRender` | prefix match on node id | `dev.html:995-1009` |
| `p.summary` branch + seat grouping | `index.html` copies | same edits, second console | `index.html:447,463,774-788` |

### Does NOT Exist (Anti-Hallucination)

Verified absent from the codebase on 2026-09-02 (`grep -rn` over
`packages/ai-parrot/src/` and `examples/`):

- ~~`parrot.flows.dev_loop.models.DispatchLabels`~~ — created by this spec.
- ~~`parrot.flows.dev_loop.session_state.SeatState`~~ — created by this spec.
- ~~`DispatchState.seats`~~ — added by this spec.
- ~~`_DISPATCH_LABELS_CTX`~~ / ~~`normalize_payload`~~ /
  ~~`summarize_tool_input`~~ / ~~`bind_labels`~~ / ~~`current_labels`~~ —
  none exist; only `_SESSION_HOST_CTX` and `_apply_to_session_host` do.
- ~~`"dispatch.activity"`~~ / ~~`"dispatch.progress"`~~ — not members of the
  `DispatchEvent.kind` Literal, and this spec does **not** add them.
- ~~A shared dispatcher base class~~ — there is none. Each of
  `ClaudeCodeDispatcher`, `CodexCodeDispatcher`, `GeminiCodeDispatcher`,
  `GoogleCodingDispatcher` and `LLMCodeDispatcher` defines its **own**
  `_publish_event`; do not assume inheritance outside the `LLMCodeDispatcher`
  family (`nova`/`grok`/`zai`/`moonshot`).
- ~~`dispatchers/mantle.py` `MantleCodeDispatcher`~~ — `mantle.py` only
  defines `MantleAdversarialReviewProfile` (:65) and
  `MantleAdversarialReviewDispatcher` (:106); there is no development
  dispatcher there to modify.
- ~~`NodeState.seats`~~ — the seat map lives on `DispatchState`, not
  `NodeState`.
- ~~A `summary` branch in `dev.html`'s `briefOf`~~ — the function checks
  `decision`, `command`/`cmd`, `criterion`, `tool_name`, `pr_url`,
  `issue_key`, `step`, `error`, `status`, `kind`, then the `keys[0]`
  fallback. No `summary`.
- ~~Per-seat rendering in `dev.html` or `index.html`~~ — both
  `nodesForRender` implementations read only their fixed `TOPOLOGY` ids
  (`dev.html:999`, `index.html:778`).
- ~~A shared JS module between `dev.html` and `index.html`~~ — there is
  none. `briefOf`, `foldAction`, `nodesForRender`, `eventRowsHtml` and
  `nodeMetaHtml` are each duplicated verbatim in both files; editing one
  does not affect the other.
- ~~A `parrot/` package at the repo root~~ — the source root is
  `packages/ai-parrot/src/parrot/`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Mirror `_SESSION_HOST_CTX` exactly** (`_shared.py:30-51`). The module
  docstring already argues, at length, why a ContextVar beats threading a
  parameter through ~40 publish call sites in a hot, actively-churning
  file. `DispatchLabels` is the same problem; use the same answer, and set
  and reset the token in the same `try/finally` blocks the host token
  already uses (`claude.py:211/231/456`).
- **Telemetry must never break a dispatch.** `normalize_payload` is total:
  it catches everything and, in the worst case, returns the payload it was
  given plus a generic `summary`. `_publish_event`'s existing
  swallow-and-warn on Redis failure and `_apply_to_session_host`'s
  `except Exception: log at DEBUG` stay exactly as they are.
- **Additive schema changes only.** New Pydantic fields are optional with
  defaults so pre-FEAT-496 persisted `ActionEnvelope`s re-validate — the
  precedent is `DispatchCompleted`'s TASK-1927 telemetry fields
  (`session_state.py:441-448`).
- **Lazy loading (AHP).** `summary` ≤ 160 chars, `text` ≤ 400 chars,
  `tool_input` ≤ 120 chars. Full content stays on the terminal channel;
  session state keeps counters and the latest one-liner, never a history.
- Google-style docstrings and strict type hints throughout; `self.logger`,
  never `print`.

### Known Risks / Gotchas

- **The roll-up must not regress.** `_owning_node_id` (`_shared.py:53-74`)
  exists because a seat-keyed action fails `NodeId` validation and is
  silently swallowed — which is why a pooled `development` node once
  reported 0 messages and 0 tool uses. Module 6 **adds** seat detail; it
  must not remove or bypass the roll-up. `test_dual_publish.py:206-218`
  already covers the roll-up and must keep passing unchanged.
- **`briefOf` is duplicated across two consoles, not shared.** `dev.html`
  and `index.html` each carry their own copy of `briefOf`, `foldAction`,
  `nodesForRender`, `eventRowsHtml` and `nodeMetaHtml` — there is no shared
  JS module to edit once. Modules 8 and 9 must apply the *same* change
  twice; a fix landing in only one console is the failure mode to guard
  against, which is why AC7 and AC7b are separate criteria. `index.html`
  additionally switches topology on `app.mode` (`:775`), so its seat
  grouping must work for the `bug` topology as well as `feature`.
- **Concurrency.** The `tool_use_id → tool_name` correlation map must be
  per-dispatch, not per-dispatcher-instance: one dispatcher instance is
  shared across concurrent seats (the reason `session_host` is a
  ContextVar rather than instance state). A `dict` on `self` would
  cross-contaminate seats and mislabel tool results.
- **Payload growth.** Stamping labels onto every event adds ~6 short string
  fields per event. Redis streams are capped (`maxlen` from
  `stream_ttl_seconds // 60` at `claude.py:1109`, `maxlen=10_000` for the
  flow stream at `flow.py:308`); the increase is bounded and acceptable,
  but keep the label set small and do not add `task_file` to *every* event
  — it belongs on `dispatch.queued`/`dispatch.started` only.
- **`DispatchOutputValidationError.raw_payload`** may contain a large blob;
  never route it into a `summary` unclamped.
- **Subclass override drift.** Four `LLMCodeDispatcher` subclasses override
  `dispatch()`; missing one leaves that backend unlabelled with no test
  failure unless Module 5's parity test enumerates all four.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | None. Uses only `contextvars`, `pydantic` and existing project deps. |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree,
  `feat-496-dev-loop-dispatch-event-legibility`, branched from `dev`.
- **Mixed parallelism within the worktree**: Modules 1 and 2 are the
  foundation and must land first, sequentially. Modules 3, 4, 5 and 6 are
  then genuinely independent (different files, no shared symbols beyond the
  Module 1/2 API) and are a natural parallel wave for a dev-agent pool.
  Module 7 depends on 3/4/5; Module 8 depends on 2/6/7; Module 9 depends on
  8 (it copies Module 8's resolved decisions into the second console).
- **Cross-feature dependencies**: none. No other open spec touches
  `dispatchers/`, `session_state.py`, `dev.html` or `index.html`.

```
Module 1 (labels + ctx)
   └── Module 2 (normalizer)
         ├── Module 3 (claude)      ┐
         ├── Module 4 (codex/gemini/agy) ├─ parallel wave
         ├── Module 5 (llm family)  ┘
         └── Module 6 (session state seats)
               └── Module 7 (pool / resolver / judges)
                     └── Module 8 (dev.html)
                           └── Module 9 (index.html — same change, 2nd console)
```

---

## 8. Open Questions

- [x] Scope — which backends? — *Resolved by the user on 2026-09-02*: all
      backends (claude-code, codex, gemini, google_coding and the llm
      family) **plus** seat/task attribution **plus** the `dev.html`
      change. Reflected in §1 G7, §3 Modules 4/5/7/8 and §5 AC9.
- [x] Process — implement now or spec first? — *Resolved by the user on
      2026-09-02*: spec only; no implementation lands with this document.
- [x] Should `index.html` (the bug-mode console) receive the same
      `briefOf`/seat treatment, or is `dev.html` the only supported
      console going forward? — *Resolved by Jesus Lara on 2026-09-02*:
      **Yes** — `index.html` gets the identical treatment. Folded into the
      spec as §3 Module 9, §5 AC7b, the §7 "duplicated across two
      consoles" risk, and the `index.html` anchors in §6; removed from
      §1 Non-Goals.
- [x] Should `summary` be localizable / is English-only acceptable for the
      console? — *Resolved by Jesus Lara on 2026-09-02*: **English-only**.
      No i18n layer for `summary`; `normalize_payload` emits plain English
      strings and nothing downstream translates them.
- [x] Is a per-seat **terminal channel** (`terminal_channel(run_id, seat)`,
      `session_state.py`) worth wiring so the console can open a live tail
      per seat, or is the seat event list in the node card enough for v1?
      — *Resolved by Jesus Lara on 2026-09-02*: **the node card is enough
      for v1**. No per-seat terminal channel is wired by this feature;
      `DispatchState.seats` plus the grouped event rows are the whole
      v1 surface.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-02 | Jesus Lara | Initial draft — FEAT-496 |
| 0.2 | 2026-09-02 | Jesus Lara | Approved. Open questions resolved: `index.html` in scope (new Module 9 + AC7b), summary English-only, no per-seat terminal channel in v1. |
