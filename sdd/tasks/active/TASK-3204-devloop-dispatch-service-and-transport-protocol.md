# TASK-3204: Dispatch service and transport protocol

**Feature**: FEAT-555 — Dev-Loop Slack Kick-off
**Spec**: `sdd/specs/dev-loop-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Assigned-to**: unassigned
**Depends-on**: TASK-3201, TASK-3202, TASK-3203

---

## Context

Spec §3 Module 8 (+ §7 "Confirm card for both kinds", "Ownership",
"Cancellation semantics", "Supervisor bounds", "Re-attach on start", Q1/Q3).
`DevLoopDispatchService` is the channel-neutral orchestrator: it owns the run
lifecycle end to end and calls back into a `DevLoopTransport` for every
user-visible moment. The Slack lane implements the transport; this task ships
the protocol and the service with fakes for process/channel/tail/transport.

---

## Scope

- `devloop/transport.py`: `DevLoopTransport` Protocol — `post_confirm(pending_id, kind, fields, requester, channel_id) -> str`, `update_confirm(pending_id, outcome, record)`, `post_run_dispatched(record) -> str`, `post_run_started(record)`, `post_spawn_failed(record, error)`, `post_gate(record, gate)`, `update_gate(record, gate)`, `update_status(record, state)`, `post_terminal(record, event)`; plus `NullTransport` (logs only) for tests/headless use.
- `devloop/service.py`: `DevLoopDispatchService(*, config, transport, redis, identity_resolver=None, jira_toolkit=None)` with `start()` (re-attach live runs), `stop()` (cancel tails only), `dispatch()` (both kinds → `PendingConfirmation` from `models.py`, TTL 15 min, `post_confirm`), `confirm()` / `discard()`, `answer_gate()` / `resolve_gate()` / `cancel()` (ownership → `NotRunOwnerError(owner_user_id)`; cancel escalation via `terminate()` after `config.cancel_grace_seconds`), `status()`, `pending_gate()`, and the three **cross-lane read accessors** the Slack handlers (TASK-3206/3207) call: `record(run_id) -> RunRecord | None` (in-memory, no Redis), `pending(pending_id) -> PendingConfirmation | None`, `record_by_thread(channel_id, thread_ts) -> RunRecord | None`; plus `_launch()`, `_supervise()`, `_handle_event()`.
- Identity: `identity_resolver(requester) -> (reporter, escalation)`; when `None`/empty/raising, fall back to `bootstrap.default_identities(jira_toolkit)` (Q3). Never a raw Slack id.
- Tests `test_service.py` with fakes for `HeadlessRunProcess`, `LoopbackRestChannel`, `RunStateTail` (monkeypatched constructors) and a recording transport.

**NOT in scope**: Slack blocks/handlers (TASK-3206/3207), manager wiring (TASK-3208), the status card rendering (TASK-3209 — the service only calls `update_status`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/transport.py` | CREATE | `DevLoopTransport` protocol, `NullTransport` |
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/service.py` | CREATE | `DevLoopDispatchService` (uses `PendingConfirmation` from `models.py`) |
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/__init__.py` | MODIFY | re-exports |
| `packages/ai-parrot-integrations/tests/integrations/devloop/test_service.py` | CREATE | lifecycle, ownership, cancel escalation, re-attach |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
import asyncio, logging, os, secrets, tempfile, time, uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol
from pydantic import BaseModel, ValidationError
from parrot.cli.devloop.bootstrap import default_identities        # verified: packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py:378 — async (jira_toolkit) -> Tuple[str, str]
from parrot.integrations.devloop.models import (                    # TASK-3200
    BridgeResult, DevLoopCommand, DevLoopIntegrationConfig, GateView, NotRunOwnerError, Requester, RequestType,
    RunEvent, RunNotFoundError, RunRecord, SpawnError,
)
from parrot.integrations.devloop.briefs import (                    # TASK-3201
    brief_summary_fields, brief_to_file, build_bug_brief, build_feature_brief,
)
from parrot.integrations.devloop.process import HeadlessRunProcess  # TASK-3202
from parrot.integrations.devloop.bridge import LoopbackRestChannel, RunCommandChannel   # TASK-3202
from parrot.integrations.devloop.tail import RunStateTail           # TASK-3203
from parrot.integrations.devloop.registry import RunRegistry        # TASK-3203
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py
async def default_identities(jira_toolkit: Any) -> Tuple[str, str]     # line 378 — (reporter, escalation); env JIRA_REPORTER_ACCOUNT_ID / JIRA_ESCALATION_ACCOUNT_ID / FLOW_BOT_JIRA_ACCOUNT_ID, fallback $USER; jira_toolkit may be None

# TASK-3200 models.py
class DevLoopIntegrationConfig: enabled, repo_path, command, redis_url, socket_dir, use_tcp, default_component,
    default_acceptance_criteria, status_card, max_concurrent_runs (None = unlimited), run_retention_seconds,
    handshake_timeout_seconds, cancel_grace_seconds (45.0), tail_drain_seconds (5.0)
class RunRecord: run_id, kind, title, requester, channel_id, thread_ts, command_endpoint, command_token, pid, phase,
    current_node, pending_gate_id, pr_url, jira_issue_key, error, last_seen_seq, status_message_ts, brief_path,
    started_at, finished_at, exit_code
class RunEvent: run_id, kind (snapshot|gate_opened|gate_resolved|gate_expired|node_changed|jira_linked|run_closed|run_cancelled|process_exited), seq, gate, node_id, node_status, state, exit_code, stderr_tail
class BridgeResult: ok, status, reason

# TASK-3202 process.py / bridge.py
class HeadlessRunProcess:
    @classmethod async def spawn(cls, *, config, run_id, brief_path, socket_path, port, token) -> HeadlessRunProcess
    async def wait_ready(self, timeout: float) -> HeadlessHandshakeView   # .run_id .command_endpoint .kind .pid
    async def wait(self) -> int ; def stderr_tail(self) -> str ; async def terminate(self, grace=10.0) ; def cleanup(self) ; pid
class LoopbackRestChannel(endpoint, *, token, timeout=10.0): resolve_gate(...), cancel(...), probe() -> bool

# TASK-3203 tail.py / registry.py
class RunStateTail(redis, run_id): async def events(*, last_seen=None) -> AsyncIterator[RunEvent] ; async def close()
class RunRegistry(redis, *, retention_seconds, namespace="devloop"): save, get, list_for(actor), live(), mark_terminal(run_id)
```

### Does NOT Exist
- ~~`DevLoopRunner.max_concurrent_runs` across processes~~ — per-process semaphore; the ONLY cap is `config.max_concurrent_runs` here (None = unlimited, user decision).
- ~~A cancel that stops the child by itself~~ — `cancel_run` only records `run/cancelled` (runner.py:1064-1067); the child cancels its task (TASK-3197) and THIS service escalates with `terminate()` after `cancel_grace_seconds` (S7).
- ~~`post_bug_confirm`~~ — replaced by `post_confirm(kind=...)` for BOTH kinds (Q1); do not add a bug-only path.
- ~~Redis-backed `PendingConfirmation`~~ — pending confirmations are memory-only with a 15 min TTL (spec §7 "Registry keys"); a restart simply expires them. `PendingConfirmation` is the public pydantic model in `models.py` (TASK-3200), not a service-private dataclass.
- ~~`RunRegistry.peek()`~~ — not defined by TASK-3203's skeleton; `record()` / `record_by_thread()` must be synchronous in-memory lookups — add a small public `peek(run_id)` / `all_records()` pair to `RunRegistry` in this task (additive) rather than reading `_records` directly.
- ~~`NotRunOwnerError(actor)`~~ — the constructor takes the owner's **user_id** (`.owner_user_id`), not the `slack:T:U` actor string.
- ~~Slack identifiers inside `WorkBrief.reporter`~~ — always the resolver result or `default_identities()` (Q3, AC10).
- ~~`redis.asyncio` construction here~~ — the manager (TASK-3208) passes a ready client; tests pass `FakeRedis`.
- ~~`parrot.cli.devloop.headless` / `DevLoopConsole`~~ — never imported by the service (child contract only).
- ~~Killing children on `stop()`~~ — forbidden (G7): `stop()` cancels tail/supervisor tasks only.

---

## Implementation Notes

### Pattern to Follow
```python
# Background tasks tracked for shutdown (wrapper.py:112 pattern)
task = asyncio.create_task(coro, name=f"devloop-tail-{run_id}")
self._tasks.add(task); task.add_done_callback(self._tasks.discard)
```

### Key Constraints
- `_launch` order (spec M8): mint `run_id = f"run-{uuid.uuid4().hex[:8]}"` and `token = secrets.token_urlsafe(32)` → `brief_to_file(brief, socket_dir, run_id)` → `HeadlessRunProcess.spawn(...)` (socket path `<socket_dir>/<run_id>.sock` unless `config.use_tcp` ⇒ `port=0`) → `wait_ready(handshake_timeout_seconds)` (on `SpawnError`: save record `phase="failed"`, `transport.post_spawn_failed`, cleanup, re-raise) → `record = RunRecord(...)`; `thread_ts = await transport.post_run_dispatched(record)` → `registry.save` → start tail task + supervise task → `transport.post_run_started`.
- Socket dir default: `os.path.join(tempfile.gettempdir(), "parrot-devloop")`, created `0o700`; AF_UNIX path length ≤ 100 bytes — warn if longer.
- `_handle_event`: `gate_opened` → `record.pending_gate_id`, `phase="blocked"`, `post_gate`; `gate_resolved|gate_expired` → clear pending, `phase="running"`, `update_gate`; `node_changed` → `current_node`, `update_status` when `config.status_card`; `jira_linked` → `jira_issue_key`; `run_closed|run_cancelled` → terminal (`phase`, `pr_url`, `finished_at`), `post_terminal`, `registry.mark_terminal`; every event updates `last_seen_seq` and saves the record.
- `_supervise`: `code = await process.wait()`; wait up to `tail_drain_seconds` for the tail to deliver a terminal event; if none → emit `RunEvent(kind="process_exited", exit_code=code, stderr_tail=...)` through `_handle_event` (terminal, `phase="failed"` unless code == 0 → `"completed"`); always `mark_terminal` + `process.cleanup()`; cancel the tail.
- Ownership: `_owned(record, requester)` compares `requester.actor` with `record.requester.actor`; mismatch ⇒ `NotRunOwnerError` for confirm/discard/answer/resolve/cancel.
- `cancel`: `channel.cancel()`; if `ok`, arm a task that waits `cancel_grace_seconds` for a terminal phase, else `process.terminate()`.
- `dispatch`: type `bug` ⇒ `reporter, escalation = await self._identities(requester)` then `build_bug_brief`; type `feature` ⇒ `build_feature_brief`; `pydantic.ValidationError` propagates (the Slack layer renders it); `max_concurrent_runs` check counts non-terminal records.
- `start()`: for each `registry.live()` record: `LoopbackRestChannel(record.command_endpoint, token=record.command_token).probe()` → reachable ⇒ tail from `record.last_seen_seq` (no supervise task — the process handle is gone; the tail's terminal event closes it); unreachable ⇒ `phase="failed"`, `post_terminal(process_exited)`, `mark_terminal`.
- Transport calls are wrapped in `try/except Exception` + `self.logger.exception`; a transport failure never affects the run (spec §7).

### References in Codebase
- `examples/dev_loop/server_dev.py:580-831` — `handle_run` (run_id minting + background task precedent; not importable).
- `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:112,157-171` — `_background_tasks` + `start()/stop()` pattern.

---

## Implementation Blueprint

### Steps (in order)
1. Write `transport.py` (protocol + `NullTransport`) — *why*: the service and the Slack lane compile against it; the null transport makes the service testable and usable headless.
2. Write `service.py` skeleton with all public methods and the private helpers as `FILL IN` — *why*: signatures are fixed by spec M8; the Slack lane starts against them immediately.
3. Implement `_launch`, `_handle_event`, `_supervise`, `cancel` escalation, `start()` re-attach.
4. Tests with monkeypatched `HeadlessRunProcess.spawn`, `LoopbackRestChannel`, `RunStateTail`; exports; `ruff`; `black`.

### `packages/ai-parrot-integrations/src/parrot/integrations/devloop/transport.py` (CREATE)
```python
"""Transport protocol the dispatch service renders through (spec §3 Module 8)."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Protocol

from parrot.integrations.devloop.models import GateView, Requester, RequestType, RunEvent, RunRecord


class DevLoopTransport(Protocol):
    """Channel adapter contract. Every method is best-effort: the service logs failures and never lets them reach the run."""

    async def post_confirm(self, pending_id: str, kind: RequestType, fields: Dict[str, str], requester: Requester,
                           channel_id: str) -> str: ...
    async def update_confirm(self, pending_id: str, outcome: str, record: Optional[RunRecord]) -> None: ...
    async def post_run_dispatched(self, record: RunRecord) -> str: ...
    async def post_run_started(self, record: RunRecord) -> None: ...
    async def post_spawn_failed(self, record: RunRecord, error: str) -> None: ...
    async def post_gate(self, record: RunRecord, gate: GateView) -> None: ...
    async def update_gate(self, record: RunRecord, gate: GateView) -> None: ...
    async def update_status(self, record: RunRecord, state: Dict[str, Any]) -> None: ...
    async def post_terminal(self, record: RunRecord, event: RunEvent) -> None: ...


class NullTransport:
    """Logs every call; returns synthetic ids. Used by tests and headless/CLI callers."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.calls: list[tuple[str, tuple]] = []

    async def post_confirm(self, pending_id, kind, fields, requester, channel_id) -> str:
        self.calls.append(("post_confirm", (pending_id, kind)))
        return f"confirm-{pending_id}"

    async def post_run_dispatched(self, record) -> str:
        self.calls.append(("post_run_dispatched", (record.run_id,)))
        return f"thread-{record.run_id}"

    # FILL IN: the remaining seven methods append (name, key args) to self.calls and return None — bounded by the Protocol above.
```
**Why this shape**: a `Protocol` (not an ABC) lets the Slack transport be a plain class; `NullTransport.calls` gives tests a recording double without mocks.

### `packages/ai-parrot-integrations/src/parrot/integrations/devloop/service.py` (CREATE)
```python
"""Channel-neutral dispatch service (spec §3 Module 8, FEAT-555)."""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import tempfile
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel

from parrot.cli.devloop.bootstrap import default_identities  # verified: cli/devloop/bootstrap.py:378
from parrot.flows.dev_flow.models import DevRequestBrief  # verified: dev_flow/models.py:61
from parrot.flows.dev_loop import WorkBrief  # verified: dev_loop/__init__.py:73
from parrot.integrations.devloop.bridge import LoopbackRestChannel, RunCommandChannel
from parrot.integrations.devloop.briefs import brief_summary_fields, brief_to_file, build_bug_brief, build_feature_brief
from parrot.integrations.devloop.models import (
    BridgeResult, DevLoopCommand, DevLoopIntegrationConfig, GateView, NotRunOwnerError, PendingConfirmation,
    Requester, RequestType, RunEvent, RunNotFoundError, RunRecord, SpawnError,
)
from parrot.integrations.devloop.process import HeadlessRunProcess
from parrot.integrations.devloop.registry import RunRegistry
from parrot.integrations.devloop.tail import RunStateTail
from parrot.integrations.devloop.transport import DevLoopTransport

IdentityResolver = Callable[[Requester], Awaitable[Tuple[str, str]]]
_PENDING_TTL = 900.0
_TERMINAL = {"completed", "failed", "cancelled"}
_BRIEF_MODEL = {"bug": WorkBrief, "feature": DevRequestBrief}


class DevLoopDispatchService:
    """Owns the run lifecycle: confirm → spawn → tail → gates → terminal; enforces initiator ownership."""

    def __init__(self, *, config: DevLoopIntegrationConfig, transport: DevLoopTransport, redis: Any,
                 identity_resolver: Optional[IdentityResolver] = None, jira_toolkit: Any = None) -> None:
        self.config = config
        self.transport = transport
        self.registry = RunRegistry(redis, retention_seconds=config.run_retention_seconds)
        self._redis = redis
        self._identity_resolver = identity_resolver
        self._jira_toolkit = jira_toolkit
        self._pending: Dict[str, PendingConfirmation] = {}
        self._processes: Dict[str, HeadlessRunProcess] = {}
        self._channels: Dict[str, RunCommandChannel] = {}
        self._gates: Dict[str, GateView] = {}
        self._tasks: set[asyncio.Task] = set()
        self.logger = logging.getLogger(__name__)

    # -- lifecycle -----------------------------------------------------------------
    async def start(self) -> None:
        """Re-attach every live record: probe its endpoint; reachable ⇒ tail from last_seen_seq, else mark failed (AC13)."""
        # FILL IN — bounded by spec §7 "Re-attach on start".
        raise NotImplementedError

    async def stop(self) -> None:
        """Cancel tail/supervisor tasks only. Children keep running (G7)."""
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # -- intake --------------------------------------------------------------------
    async def dispatch(self, command: DevLoopCommand, requester: Requester, channel_id: str) -> str:
        """Both kinds: build the brief, park it as a PendingConfirmation, post the confirm card; returns pending_id (Q1)."""
        self._expire_pending()
        self._check_capacity()
        if command.type == "bug":
            reporter, escalation = await self._identities(requester)
            brief: BaseModel = build_bug_brief(command, requester, self.config, reporter=reporter, escalation_assignee=escalation)
        else:
            brief = build_feature_brief(command, self.config)
        now = time.time()
        pending = PendingConfirmation(pending_id=uuid.uuid4().hex[:12], kind=command.type or "feature",
                                      brief=brief.model_dump(mode="json"), fields=brief_summary_fields(brief),
                                      requester=requester, channel_id=channel_id, created_at=now, expires_at=now + _PENDING_TTL)
        self._pending[pending.pending_id] = pending
        pending.message_ts = await self.transport.post_confirm(pending.pending_id, pending.kind, pending.fields,
                                                               requester, channel_id)
        return pending.pending_id

    # -- cross-lane read accessors (used by the Slack handlers, TASK-3206/3207) ----
    def record(self, run_id: str) -> Optional[RunRecord]:
        """In-memory lookup only (no Redis) — safe inside a Slack 3 s ack / trigger_id window."""
        return self.registry._records.get(run_id)  # FILL IN: expose a public RunRegistry.peek(run_id) in TASK-3203 style instead of touching _records

    def pending(self, pending_id: str) -> Optional[PendingConfirmation]:
        return self._pending.get(pending_id)

    def record_by_thread(self, channel_id: str, thread_ts: str) -> Optional[RunRecord]:
        """Match RunRecord.channel_id + thread_ts (thread-reply interceptor)."""
        return next((r for r in self.registry._records.values() if r.channel_id == channel_id and r.thread_ts == thread_ts), None)

    async def confirm(self, pending_id: str, requester: Requester, overrides: Optional[Dict[str, Any]] = None) -> RunRecord:
        """Ownership check; re-validate with Edit-modal overrides; launch; update the card."""
        # FILL IN: pop pending (RunNotFoundError), ownership check (NotRunOwnerError(pending.requester.user_id)),
        # brief = _BRIEF_MODEL[pending.kind](**{**pending.brief, **(overrides or {})}) (pydantic re-validates),
        # record = await self._launch(...), transport.update_confirm(pending_id, "confirmed", record) — bounded by AC10.
        raise NotImplementedError

    async def discard(self, pending_id: str, requester: Requester) -> None:
        # FILL IN: pop + ownership + transport.update_confirm(pending_id, "discarded", None) — bounded by AC10.
        raise NotImplementedError
```
**Why this shape**: `dispatch()` never spawns (Q1 — both kinds confirm first); pending confirmations are memory-only so a restart expires them (spec §7); identities come from the resolver or `default_identities()` (Q3).

### `packages/ai-parrot-integrations/src/parrot/integrations/devloop/service.py` (CREATE — second half, append)
```python
    # -- commands ------------------------------------------------------------------
    async def answer_gate(self, run_id: str, gate_id: str, requester: Requester, answers: Dict[str, str]) -> BridgeResult:
        record = await self._require_owned(run_id, requester)
        return await self._channel(record).resolve_gate(run_id, gate_id, resolution="approved",
                                                        resolved_by=requester.actor, answers=answers)

    async def resolve_gate(self, run_id: str, gate_id: str, requester: Requester, resolution: str,
                           comment: str = "") -> BridgeResult:
        record = await self._require_owned(run_id, requester)
        return await self._channel(record).resolve_gate(run_id, gate_id, resolution=resolution,
                                                        resolved_by=requester.actor, comment=comment)

    async def cancel(self, run_id: str, requester: Requester) -> BridgeResult:
        """channel.cancel(); on success arm the S7 escalation (terminate after cancel_grace_seconds without a terminal phase)."""
        record = await self._require_owned(run_id, requester)
        result = await self._channel(record).cancel(run_id, requested_by=requester.actor)
        # FILL IN: if result.ok and run_id in self._processes → self._track(self._escalate_cancel(run_id)) — bounded by AC21.
        return result

    async def status(self, requester: Requester) -> List[RunRecord]:
        return await self.registry.list_for(requester.actor)

    def pending_gate(self, run_id: str) -> Optional[GateView]:
        return self._gates.get(run_id)

    # -- internals -----------------------------------------------------------------
    async def _identities(self, requester: Requester) -> Tuple[str, str]:
        """Resolver first (Q3); empty/raising resolver ⇒ default_identities(jira_toolkit); never a raw Slack id."""
        # FILL IN — bounded by AC10.
        raise NotImplementedError

    async def _require_owned(self, run_id: str, requester: Requester) -> RunRecord:
        record = await self.registry.get(run_id)
        if record is None:
            raise RunNotFoundError(run_id)
        if record.requester.actor != requester.actor:
            raise NotRunOwnerError(record.requester.user_id)  # .owner_user_id → Slack renders "<@owner>"
        return record

    def _channel(self, record: RunRecord) -> RunCommandChannel:
        return self._channels.setdefault(record.run_id, LoopbackRestChannel(record.command_endpoint, token=record.command_token))

    def _track(self, coro: Awaitable[Any], name: str = "") -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _launch(self, brief: BaseModel, kind: RequestType, title: str, requester: Requester, channel_id: str) -> RunRecord:
        """mint ids → brief file → spawn → handshake → thread root → registry → tail + supervise (spec M8)."""
        run_id, token = f"run-{uuid.uuid4().hex[:8]}", secrets.token_urlsafe(32)
        # FILL IN: socket_dir default (tempfile.gettempdir()/parrot-devloop, 0o700, warn > 100 bytes), brief_to_file, spawn,
        # wait_ready → on SpawnError: record phase="failed"+error, post_spawn_failed, cleanup, raise; build RunRecord
        # (endpoint from the handshake), thread_ts = post_run_dispatched, registry.save, self._track(self._tail(record)),
        # self._track(self._supervise(record)), post_run_started — bounded by AC6/AC14/AC15.
        raise NotImplementedError

    async def _tail(self, record: RunRecord, *, last_seen: Optional[int] = None) -> None:
        tail = RunStateTail(self._redis, record.run_id)
        async for event in tail.events(last_seen=last_seen):
            await self._handle_event(record, event)

    async def _handle_event(self, record: RunRecord, event: RunEvent) -> None:
        """Fold one RunEvent into the record and render it (see Key Constraints); transport errors are logged, never raised."""
        # FILL IN — bounded by spec §7 and AC7/AC9/AC16.
        raise NotImplementedError

    async def _supervise(self, record: RunRecord) -> None:
        """Bounded supervisor (S8): child exit → drain window → process_exited if no terminal → mark_terminal + cleanup."""
        # FILL IN — bounded by config.tail_drain_seconds and AC14.
        raise NotImplementedError

    async def _escalate_cancel(self, run_id: str) -> None:
        # FILL IN: sleep cancel_grace_seconds; if record.phase not terminal → self._processes[run_id].terminate() — S7/AC21.
        raise NotImplementedError

    def _expire_pending(self) -> None:
        now = time.time()
        for pid in [p for p, pc in self._pending.items() if now > pc.expires_at]:
            self._pending.pop(pid, None)

    def _check_capacity(self) -> None:
        # FILL IN: when config.max_concurrent_runs is not None and non-terminal records ≥ cap → raise DevLoopError — spec §7 (None = unlimited).
        pass
```
**Why this shape**: every outbound Slack effect goes through the transport so the service is channel-neutral (G5); ownership is enforced before any command reaches the child because the REST routes are auth-agnostic (S4, AC8); the cancel escalation exists because the runner only records the cancel action (S7, AC21).

### `packages/ai-parrot-integrations/src/parrot/integrations/devloop/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3200: grep -c '^__all__ = \[' packages/ai-parrot-integrations/src/parrot/integrations/devloop/__init__.py)
# BEFORE `__all__ = [` add:
from .service import DevLoopDispatchService
from .transport import DevLoopTransport, NullTransport
# and append the three names to __all__ (PendingConfirmation is already exported from models by TASK-3200).
```
**Why**: the Slack lane imports `DevLoopDispatchService` / `DevLoopTransport` from the package root.

### `packages/ai-parrot-integrations/tests/integrations/devloop/test_service.py` (CREATE)
```python
"""Tests for DevLoopDispatchService (TASK-3204) with fakes for process/channel/tail and a NullTransport."""
import asyncio

import pytest

from parrot.integrations.devloop import service as svc
from parrot.integrations.devloop.models import (
    BridgeResult, DevLoopCommand, DevLoopIntegrationConfig, NotRunOwnerError, Requester,
)
from parrot.integrations.devloop.transport import NullTransport

_REQ = Requester(transport="slack", tenant_id="T", user_id="U1")
_OTHER = Requester(transport="slack", tenant_id="T", user_id="U2")


class _FakeProc:
    pid = 4242
    def __init__(self): self.terminated = False; self._exit = asyncio.get_event_loop().create_future()
    async def wait_ready(self, timeout): return type("HS", (), {"run_id": "run-x", "command_endpoint": "unix:///tmp/x.sock", "kind": "bug", "pid": 4242})()
    async def wait(self): return await self._exit
    def stderr_tail(self): return "tail"
    async def terminate(self, grace=10.0): self.terminated = True; self._exit.set_result(-15)
    def cleanup(self): pass


@pytest.fixture
def service(fake_redis, monkeypatch, tmp_path):
    cfg = DevLoopIntegrationConfig(name="t", enabled=True, repo_path=str(tmp_path), socket_dir=str(tmp_path),
                                   cancel_grace_seconds=0.05, tail_drain_seconds=0.05,
                                   default_acceptance_criteria=[{"kind": "shell", "name": "u", "command": "pytest -q"}])
    proc = _FakeProc()
    async def _spawn(**kw): return proc
    monkeypatch.setattr(svc.HeadlessRunProcess, "spawn", _spawn)
    # FILL IN: monkeypatch svc.RunStateTail with a fake whose events() yields from an asyncio.Queue the test feeds;
    # monkeypatch svc.LoopbackRestChannel with a fake recording resolve_gate/cancel and returning BridgeResult(ok=True, status=200).
    s = svc.DevLoopDispatchService(config=cfg, transport=NullTransport(), redis=fake_redis,
                                   identity_resolver=lambda r: asyncio.sleep(0, ("rep@x", "esc@x")))
    return s, proc


async def test_dispatch_confirms_before_spawn(service):
    s, proc = service
    pid = await s.dispatch(DevLoopCommand(action="dispatch", type="feature", prompt="Build the thing. Now"), _REQ, "C1")
    assert s.transport.calls[-1][0] == "post_confirm" and s._processes == {}
    with pytest.raises(NotRunOwnerError):
        await s.confirm(pid, _OTHER)
    record = await s.confirm(pid, _REQ)
    assert record.phase in ("starting", "running") and record.thread_ts == f"thread-{record.run_id}"


# FILL IN: bug dispatch uses identity_resolver; answer_gate/cancel by non-owner → NotRunOwnerError (AC8); cancel escalation
# terminates when no terminal event within cancel_grace (AC21); gate_opened event → post_gate + pending_gate; run_closed →
# post_terminal + mark_terminal; process exit without terminal → process_exited (AC14); start() re-attaches a live record
# whose channel.probe() is True (AC13); pending confirmation expires after TTL; max_concurrent_runs=None never blocks.
```

### FILL IN checklist
- [ ] `transport.py::NullTransport` — remaining recording methods.
- [ ] `service.py::start` — re-attach; bounded by §7 "Re-attach on start" / AC13.
- [ ] `service.py::confirm` / `discard` — ownership + relaunch with overrides; bounded by AC10.
- [ ] `service.py::cancel` + `_escalate_cancel` — S7; bounded by AC21.
- [ ] `service.py::_identities` — resolver then `default_identities`; bounded by Q3 / AC10.
- [ ] `service.py::_launch` — spec M8 order; bounded by AC6/AC14/AC15.
- [ ] `service.py::_handle_event` — event folding + transport calls; bounded by AC7/AC9/AC16.
- [ ] `service.py::_supervise` — S8 bounds; bounded by AC14.
- [ ] `service.py::_check_capacity` — optional cap; `None` = unlimited.
- [ ] Test fakes for tail/channel and the stubbed scenarios.

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/devloop -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/devloop`
- [ ] Imports work: `from parrot.integrations.devloop import DevLoopDispatchService, DevLoopTransport, NullTransport`
- [ ] Spec AC8 (ownership), AC10 (confirm card for both kinds, identities never a Slack id), AC13 (re-attach), AC14 (process_exited), AC21 (cancel escalation) are covered by tests; `stop()` never terminates a child (G7)

---

## Test Specification

See the `test_service.py` blueprint above.

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
7. **Move this file** to `sdd/tasks/completed/TASK-3204-devloop-dispatch-service-and-transport-protocol.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
