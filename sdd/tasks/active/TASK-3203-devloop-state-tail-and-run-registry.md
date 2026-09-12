# TASK-3203: Run state tail (Redis actions stream → RunEvent) and run registry

**Feature**: FEAT-555 — Dev-Loop Slack Kick-off
**Spec**: `sdd/specs/dev-loop-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3200
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (+ §7 "Registry keys", "Re-attach on start", "Redis outage
while tailing", G7). The headless child publishes every session-state action
on `flow:{run_id}:actions` exactly as it does for the HTML console. `RunStateTail`
wraps the existing `FlowStreamMultiplexer(view="state")` and reduces each
envelope frame to a `RunEvent` for the service/transport. `RunRegistry` keeps
`RunRecord`s in memory and mirrors them in Redis so a restarted bot can
re-attach (AC13). Nothing in `streaming.py` or `session_state.py` changes.

---

## Scope

- `devloop/tail.py`: `RunStateTail(redis, run_id)` with `events(*, last_seen=None) -> AsyncIterator[RunEvent]` (`state_replay(last_seen=...)` then `state_tail()`), the frame → `RunEvent` mapping table below, exponential backoff 1→30 s on Redis errors resuming from the last seen `server_seq`, and `close()`.
- `devloop/registry.py`: `RunRegistry(redis, *, retention_seconds, namespace="devloop")` with `save`, `get`, `list_for(actor)`, `live()`, `mark_terminal(run_id)`; keys hash `devloop:runs:{run_id}` (field `record` = `RunRecord.model_dump_json()`), set `devloop:runs:live`.
- Tests with the shared `FakeRedis` fixture (TASK-3200 `conftest.py`): `test_tail.py`, `test_registry.py`.

**NOT in scope**: spawning, command channel, Slack rendering, the service loop that consumes the events (TASK-3204).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/tail.py` | CREATE | `RunStateTail` |
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/registry.py` | CREATE | `RunRegistry` |
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/__init__.py` | MODIFY | re-exports |
| `packages/ai-parrot-integrations/tests/integrations/devloop/test_tail.py` | CREATE | mapping, terminal stop, resume, backoff |
| `packages/ai-parrot-integrations/tests/integrations/devloop/test_registry.py` | CREATE | round-trip, live set, retention |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
import asyncio, json, logging, time
from typing import Any, AsyncIterator, Dict, List, Optional
from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer       # verified: packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py:73
from parrot.flows.dev_loop.session_state import (                        # verified: session_state.py
    ActionEnvelope,   # :626
    ApprovalGate,     # :257
    DevLoopSessionState,  # :330
    Snapshot,         # :636
    reduce,           # :879
    session_channel,  # :88
)
from parrot.integrations.devloop.models import GateView, RunEvent, RunRecord   # TASK-3200
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py
class FlowStreamMultiplexer:                                              # line 73
    def __init__(self, redis: Any, *, run_id: str, view: ViewLiteral = "both",
                 dispatch_refresh_seconds: float = 2.0, block_ms: int = 1000) -> None   # line 76
    #   self._actions_key = f"flow:{run_id}:actions" (line 106); self._state_cursor = "$" (line 107)
    async def state_replay(self, *, last_seen: Optional[int] = None) -> AsyncIterator[Dict[str, Any]]   # line 291
    #   last_seen None → ONE frame {"source":"state","node_id":None,"event_kind":"snapshot","ts":…,"payload": Snapshot.model_dump()}  (lines 336-347)
    #   last_seen N    → frames {"event_kind":"action","ts":…,"payload": ActionEnvelope.model_dump()} for server_seq > N  (lines 349-358)
    _TERMINAL_ACTION_TYPES = frozenset({"run/closed", "run/cancelled"})     # line 360
    async def state_tail(self) -> AsyncIterator[Dict[str, Any]]           # line 410
    #   XREAD BLOCK loop from self._state_cursor; frames {"event_kind":"action","payload": ActionEnvelope.model_dump()} (lines 397-402);
    #   logs and continues on xread failure (line ~437 "state-view xread failed"); yields the terminal frame then returns; stops on close()
    async def close(self) -> None                                         # line 251 — sets self._closed

# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
class ActionEnvelope(_Frozen): channel: str; server_seq: int; action: DevLoopAction; origin; rejection_reason  # line 626
class Snapshot(_Frozen): channel: str; state: DevLoopSessionState; from_seq: int                            # line 636
class DevLoopSessionState(_Frozen): run_id, channel, phase, summary, jira_issue_key, pr_url, nodes: Dict[str, NodeState], gates: Dict[str, ApprovalGate], cancel_requested_by, error, docs_artifacts, ...   # line 330
class ApprovalGate(_Frozen): gate_id, kind, node_id, status, on_expiry, title, instructions, payload_ref, opened_at, expires_at, resolved_by, resolved_at, comment, questions: List[str], answers: Dict[str,str]   # line 257
class RunCancelled: type="run/cancelled"; requested_by: str                     # line 384
class RunClosed:    type="run/closed"; outcome: Literal["succeeded","failed"]; jira_issue_key=""; pr_url=""   # line 389
class NodeStarted:  type="node/started";   node_id                              # line 399
class NodeCompleted:type="node/completed"; node_id; summary: Dict[str,str]      # line 404
class NodeFailed:   type="node/failed";    node_id; error: str = ""             # line 410
class NodeSkipped:  type="node/skipped";   node_id                              # line 416
class GateOpened:   type="gate/opened";    gate: ApprovalGate                   # line 492
class GateResolved: type="gate/resolved";  gate_id; resolution; resolved_by; comment; answers   # line 497
class GateExpired:  type="gate/expired";   gate_id                              # line 511
class JiraLinked:   type="run/jiraLinked"; issue_key: str                       # line 519
def session_channel(run_id: str) -> str                                         # line 88
def reduce(state: DevLoopSessionState, action) -> DevLoopSessionState           # line 879
```
Frame → `RunEvent` mapping (fixed by spec M7):
| frame / `payload["action"]["type"]` | `RunEvent.kind` | fields |
|---|---|---|
| `event_kind == "snapshot"` | `snapshot` | `state=payload["state"]`, `seq=payload["from_seq"]` |
| `gate/opened` | `gate_opened` | `gate=GateView(**subset of action["gate"])` |
| `gate/resolved` | `gate_resolved` | `gate=GateView(gate_id, kind="", title="", status=resolution, resolved_by, answers)` |
| `gate/expired` | `gate_expired` | `gate=GateView(gate_id, kind="", title="", status="expired")` |
| `node/started|completed|failed|skipped` | `node_changed` | `node_id`, `node_status` = `running|completed|failed|skipped` |
| `run/jiraLinked` | `jira_linked` | `state={"jira_issue_key": issue_key}` |
| `run/closed` | `run_closed` | `state={"outcome", "jira_issue_key", "pr_url"}` (terminal) |
| `run/cancelled` | `run_cancelled` | `state={"requested_by"}` (terminal) |
| anything else (`dispatch/*`, `feature/*`, `run/prLinked`, `run/qaAttemptRecorded`, `run/created`) | *skipped* | — |
`seq` = `payload["server_seq"]` for action frames.

### Does NOT Exist
- ~~`flow:{run_id}:commands` inbound stream~~ — Redis is publish-only; commands go through TASK-3202's channel.
- ~~`FlowStreamMultiplexer.state_tail(last_seen=...)`~~ — `state_tail` takes no arguments; the cursor comes from a preceding `state_replay(last_seen=...)` on the SAME instance (streaming.py:318-320). A NEW multiplexer starts at `"$"` (new entries only) — this is why resume must call `state_replay(last_seen=<seq>)` first.
- ~~Live entries carry field `event`~~ — the actions stream entry field is `"envelope"` (streaming.py:386-389); the `event` field belongs to the flow/dispatch streams.
- ~~`redis.asyncio` at import time~~ — the tail/registry receive an already-built client (`redis.asyncio.Redis(decode_responses=True)` or the test fake); never construct one here.
- ~~`fakeredis`~~ — NOT a declared dependency in any pyproject; never import it. Use `tests/integrations/devloop/conftest.py::FakeRedis` (TASK-3200), a copy of `_FakeStreamsRedis` (`packages/ai-parrot/tests/flows/dev_loop/test_streaming.py:26`) extended with `hset`/`hget`/`hgetall`, `sadd`/`srem`/`smembers`, `expire`.
- ~~`RunRegistry` storing per-field hashes~~ — store the whole record JSON in one hash field `record` so a Pydantic upgrade never leaves half-migrated hashes.

---

## Implementation Notes

### Pattern to Follow
```python
# streaming.py:291-359 — replay first (sets the cursor), then tail on the SAME multiplexer instance
mux = FlowStreamMultiplexer(redis, run_id=run_id, view="state")
async for frame in mux.state_replay(last_seen=last_seen):
    ...
async for frame in mux.state_tail():
    ...
```

### Key Constraints
- Backoff: on any exception raised out of `state_replay`/`state_tail` (connection loss) — sleep `min(30, 2**attempt)` seconds, rebuild the multiplexer, resume with `state_replay(last_seen=<last seq yielded>)`; reset `attempt` after a successful frame. The generator ends only after a terminal event or `close()`.
- Never yield the same `server_seq` twice (dedupe by `seq > last_yielded`).
- `RunRegistry.save` writes memory first, then Redis (`hset name=key, mapping={"record": json}`, `sadd live` unless terminal); `mark_terminal` does `srem` + `expire(key, retention_seconds)`; `live()` reads the set and each hash, drops missing hashes with a warning.
- Redis failures in the registry are logged, never raised (the in-memory copy is authoritative for the running bot).

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/test_streaming_state_view.py:83-92` — how tests seed the stream: `host.apply(action)` → `redis.xadd(key, {"envelope": envelope.model_dump_json()})`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py:1134` — `SessionHost(run_id=...)` to produce sequenced envelopes in tests.

---

## Implementation Blueprint

### Steps (in order)
1. Write `tail.py` with the mapping function as a pure `_frame_to_event(run_id, frame) -> RunEvent | None` — *why*: unit-testable without Redis.
2. Write `registry.py` — *why*: independent of the tail.
3. Extend `FakeRedis` (conftest, TASK-3200) only if a method is missing; write tests seeding the stream with a real `SessionHost`.
4. Exports, `ruff`, `black`.

### `packages/ai-parrot-integrations/src/parrot/integrations/devloop/tail.py` (CREATE)
```python
"""``flow:{run_id}:actions`` → :class:`RunEvent` (spec §3 Module 7)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, Optional

from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer  # verified: streaming.py:73
from parrot.integrations.devloop.models import GateView, RunEvent

_NODE_STATUS = {"node/started": "running", "node/completed": "completed", "node/failed": "failed", "node/skipped": "skipped"}
_MAX_BACKOFF = 30.0


def _gate_view(raw: Dict[str, Any]) -> GateView:
    """Project an ``ApprovalGate.model_dump()`` (session_state.py:257) onto ``GateView``."""
    return GateView(**{k: raw[k] for k in GateView.model_fields if k in raw})


def _frame_to_event(run_id: str, frame: Dict[str, Any]) -> Optional[RunEvent]:
    """Apply the M7 mapping table; ``None`` for frames the integration ignores."""
    payload = frame.get("payload") or {}
    if frame.get("event_kind") == "snapshot":
        return RunEvent(run_id=run_id, kind="snapshot", seq=int(payload.get("from_seq", 0)), state=payload.get("state"))
    action = payload.get("action") or {}
    seq = int(payload.get("server_seq", 0))
    atype = action.get("type", "")
    if atype == "gate/opened":
        return RunEvent(run_id=run_id, kind="gate_opened", seq=seq, gate=_gate_view(action.get("gate") or {}))
    # FILL IN: gate/resolved, gate/expired, node/* (via _NODE_STATUS), run/jiraLinked, run/closed, run/cancelled per the
    # contract table; return None for every other type — bounded by spec M7 mapping table.
    return None


class RunStateTail:
    """Replay + live tail of one run's state stream with bounded reconnects."""

    def __init__(self, redis: Any, run_id: str) -> None:
        self._redis = redis
        self._run_id = run_id
        self._mux: Optional[FlowStreamMultiplexer] = None
        self._closed = asyncio.Event()
        self.logger = logging.getLogger(__name__)

    async def events(self, *, last_seen: Optional[int] = None) -> AsyncIterator[RunEvent]:
        """Yield RunEvents until a terminal one (run_closed/run_cancelled) or close(); never yields a seq twice."""
        last_yielded = last_seen or 0
        attempt = 0
        while not self._closed.is_set():
            self._mux = FlowStreamMultiplexer(self._redis, run_id=self._run_id, view="state")
            try:
                # FILL IN: for frame in state_replay(last_seen=last_yielded or None) then state_tail(): map via
                # _frame_to_event; skip seq <= last_yielded (snapshot exempt); yield; update last_yielded; attempt = 0;
                # return after a terminal kind — bounded by streaming.py:291-460 and the dedupe rule.
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - connection loss: back off and resume from last_yielded
                attempt += 1
                delay = min(_MAX_BACKOFF, 2.0**attempt)
                self.logger.warning("state tail for %s failed (%s); retrying in %.0fs", self._run_id, exc, delay)
                await asyncio.sleep(delay)

    async def close(self) -> None:
        self._closed.set()
        if self._mux is not None:
            await self._mux.close()
```
**Why this shape**: the mapping is a pure function so the Slack lane can be tested with hand-built frames; resume always goes through `state_replay(last_seen=…)` on a fresh multiplexer because `state_tail` alone starts at `"$"` (streaming.py:107) and would drop everything published during the outage (AC13, spec §7 "Redis outage while tailing").

### `packages/ai-parrot-integrations/src/parrot/integrations/devloop/registry.py` (CREATE)
```python
"""RunRecord registry — memory + Redis mirror (spec §3 Module 7, §7 "Registry keys")."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from parrot.integrations.devloop.models import RunRecord

_TERMINAL = {"completed", "failed", "cancelled"}


class RunRegistry:
    """Keys: hash ``{ns}:runs:{run_id}`` (field ``record`` = RunRecord JSON) and set ``{ns}:runs:live``."""

    def __init__(self, redis: Any, *, retention_seconds: int, namespace: str = "devloop") -> None:
        self._redis = redis
        self._retention = int(retention_seconds)
        self._ns = namespace
        self._records: Dict[str, RunRecord] = {}
        self.logger = logging.getLogger(__name__)

    def _key(self, run_id: str) -> str:
        return f"{self._ns}:runs:{run_id}"

    @property
    def _live_key(self) -> str:
        return f"{self._ns}:runs:live"

    async def save(self, record: RunRecord) -> None:
        """Memory first, then Redis (hset + sadd unless terminal). Redis errors are logged, never raised."""
        self._records[record.run_id] = record
        # FILL IN: hset(self._key(run_id), mapping={"record": record.model_dump_json()}); sadd live unless
        # record.phase in _TERMINAL; wrap in try/except Exception → self.logger.warning — bounded by AC13.
        raise NotImplementedError

    async def get(self, run_id: str) -> Optional[RunRecord]:
        """Memory hit, else Redis hash (and cache it)."""
        # FILL IN: hgetall → RunRecord.model_validate_json(data["record"]) — bounded by AC13.
        raise NotImplementedError

    async def list_for(self, actor: str) -> List[RunRecord]:
        """Records whose requester.actor == actor (memory + live set), newest first."""
        # FILL IN — bounded by AC12 (status lists only the caller's runs).
        raise NotImplementedError

    async def live(self) -> List[RunRecord]:
        """Records in the live set whose phase is not terminal; missing hashes are dropped with a warning."""
        # FILL IN: smembers(live) → get each → filter — bounded by AC13 re-attach.
        raise NotImplementedError

    async def mark_terminal(self, run_id: str) -> None:
        """srem from live; expire the hash to the retention window; keep the memory copy."""
        # FILL IN — bounded by spec §7 "Registry keys" (EX retention on terminal).
        raise NotImplementedError
```
**Why this shape**: one JSON field per hash keeps the record atomic and versionable; the live set makes `start()` re-attach O(live runs) instead of scanning keys (spec §7 "Re-attach on start"); memory stays authoritative so a Redis blip never hides a run from `/devloop status`.

### `packages/ai-parrot-integrations/src/parrot/integrations/devloop/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3200: grep -c '^__all__ = \[' packages/ai-parrot-integrations/src/parrot/integrations/devloop/__init__.py)
# BEFORE `__all__ = [` add:
from .registry import RunRegistry
from .tail import RunStateTail
# and append "RunRegistry", "RunStateTail" to __all__.
```
**Why**: public import path for TASK-3204 and the Slack lane.

### `packages/ai-parrot-integrations/tests/integrations/devloop/test_tail.py` (CREATE)
```python
"""Tests for RunStateTail (TASK-3203) — stream seeded with a real SessionHost, FakeRedis from conftest."""
import asyncio

import pytest

from parrot.flows.dev_loop.session_state import (
    ApprovalGate, GateOpened, NodeCompleted, NodeStarted, RunClosed, RunCreated, SessionHost,
)
from parrot.integrations.devloop.tail import RunStateTail, _frame_to_event

RUN = "run-tail0001"


def _key() -> str:
    return f"flow:{RUN}:actions"


async def _seed(redis, host, *actions):
    for a in actions:
        env = host.apply(a)
        await redis.xadd(_key(), {"envelope": env.model_dump_json()})


async def test_events_map_and_stop_on_terminal(fake_redis):
    host = SessionHost(run_id=RUN)  # FILL IN: constructor kwargs per session_state.py:1134-1160 (RunCreated seed etc.)
    gate = ApprovalGate(gate_id="oq-1", kind="open_questions", node_id="ideation", title="Open questions — x", questions=["Q1?"])
    await _seed(fake_redis, host, NodeStarted(node_id="ideation"), GateOpened(gate=gate),
                NodeCompleted(node_id="ideation"), RunClosed(outcome="succeeded", pr_url="http://pr"))
    kinds = [e.kind async for e in RunStateTail(fake_redis, RUN).events(last_seen=0)]
    assert kinds == ["node_changed", "gate_opened", "node_changed", "run_closed"]


def test_frame_to_event_skips_dispatch_frames():
    frame = {"event_kind": "action", "payload": {"server_seq": 5, "action": {"type": "dispatch/delta"}}}
    assert _frame_to_event(RUN, frame) is None


# FILL IN: snapshot frame when last_seen is None; resume from last_seen skips ≤N (AC13); gate_resolved carries answers;
# backoff on a redis that raises once then recovers (patch FakeRedis.xread) — spec §7 "Redis outage while tailing".
```

### `packages/ai-parrot-integrations/tests/integrations/devloop/test_registry.py` (CREATE)
```python
"""Tests for RunRegistry (TASK-3203)."""
import time

from parrot.integrations.devloop.models import Requester, RunRecord
from parrot.integrations.devloop.registry import RunRegistry


def _rec(run_id="run-1", actor_user="U1", phase="running") -> RunRecord:
    return RunRecord(run_id=run_id, kind="bug", title="t", channel_id="C1", phase=phase, started_at=time.time(),
                     requester=Requester(transport="slack", tenant_id="T", user_id=actor_user))


async def test_roundtrip_and_live(fake_redis):
    reg = RunRegistry(fake_redis, retention_seconds=60)
    await reg.save(_rec())
    fresh = RunRegistry(fake_redis, retention_seconds=60)  # simulates a restarted bot
    assert (await fresh.get("run-1")).run_id == "run-1" and [r.run_id for r in await fresh.live()] == ["run-1"]


async def test_mark_terminal_expires_and_leaves_live_set(fake_redis):
    reg = RunRegistry(fake_redis, retention_seconds=60)
    await reg.save(_rec()); await reg.mark_terminal("run-1")
    assert await reg.live() == [] and fake_redis.expirations["devloop:runs:run-1"] == 60


# FILL IN: list_for filters by actor (AC12); Redis error on save is logged and memory still holds the record.
```

### FILL IN checklist
- [ ] `tail.py::_frame_to_event` — remaining rows of the mapping table; bounded by spec M7.
- [ ] `tail.py::RunStateTail.events` — replay→tail loop, dedupe, terminal stop; bounded by streaming.py:291-460.
- [ ] `registry.py` — the five method bodies; bounded by §7 "Registry keys" / AC12 / AC13.
- [ ] `conftest.py::FakeRedis` — add any method the multiplexer/registry calls that TASK-3200 left out.
- [ ] Stubbed tests.

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/devloop/test_tail.py packages/ai-parrot-integrations/tests/integrations/devloop/test_registry.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/devloop`
- [ ] Imports work: `from parrot.integrations.devloop import RunStateTail, RunRegistry`
- [ ] Spec AC13 groundwork: a fresh registry on the same Redis lists the live run; a tail resumed with `last_seen=N` never re-yields ≤N; no change to `streaming.py` / `session_state.py`

---

## Test Specification

See the two test blueprints above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/dev-loop-slack.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3203-devloop-state-tail-and-run-registry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
