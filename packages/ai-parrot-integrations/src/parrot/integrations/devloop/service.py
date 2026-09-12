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
from parrot.integrations.devloop.briefs import (
    brief_summary_fields,
    brief_to_file,
    build_bug_brief,
    build_feature_brief,
)
from parrot.integrations.devloop.models import (
    BridgeResult,
    DevLoopCommand,
    DevLoopError,
    DevLoopIntegrationConfig,
    GateView,
    NotRunOwnerError,
    PendingConfirmation,
    Requester,
    RequestType,
    RunEvent,
    RunNotFoundError,
    RunRecord,
    SpawnError,
)
from parrot.integrations.devloop.process import HeadlessRunProcess
from parrot.integrations.devloop.registry import RunRegistry
from parrot.integrations.devloop.tail import RunStateTail
from parrot.integrations.devloop.transport import DevLoopTransport

IdentityResolver = Callable[[Requester], Awaitable[Tuple[str, str]]]
_PENDING_TTL = 900.0
_TERMINAL = {"completed", "failed", "cancelled"}
_BRIEF_MODEL: Dict[str, type] = {"bug": WorkBrief, "feature": DevRequestBrief}
_AF_UNIX_MAX_PATH = 100


class DevLoopDispatchService:
    """Owns the run lifecycle: confirm → spawn → tail → gates → terminal; enforces initiator ownership."""

    def __init__(
        self,
        *,
        config: DevLoopIntegrationConfig,
        transport: DevLoopTransport,
        redis: Any,
        identity_resolver: Optional[IdentityResolver] = None,
        jira_toolkit: Any = None,
    ) -> None:
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
        self._tasks: set = set()
        self.logger = logging.getLogger(__name__)

    # -- lifecycle -----------------------------------------------------------------

    async def start(self) -> None:
        """Re-attach every live record.

        Probes each record's command endpoint; reachable ⇒ resume its tail
        from ``last_seen_seq``; unreachable ⇒ mark it failed and post a
        terminal ``process_exited`` message (spec §7 "Re-attach on start", AC13).
        """
        for record in await self.registry.live():
            channel = LoopbackRestChannel(record.command_endpoint, token=record.command_token)
            self._channels[record.run_id] = channel
            reachable = await channel.probe()
            if reachable:
                self._track(self._tail(record, last_seen=record.last_seen_seq), name=f"devloop-tail-{record.run_id}")
                continue
            record.phase = "failed"
            record.finished_at = time.time()
            await self.registry.save(record)
            event = RunEvent(run_id=record.run_id, kind="process_exited", exit_code=None)
            await self._safe_call(self.transport.post_terminal, record, event)
            await self.registry.mark_terminal(record.run_id)

    async def stop(self) -> None:
        """Cancel tail/supervisor tasks only. Children keep running (G7)."""
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # -- intake --------------------------------------------------------------------

    async def dispatch(self, command: DevLoopCommand, requester: Requester, channel_id: str) -> str:
        """Build the brief for both kinds and park it behind a confirm card (Q1).

        Nothing is spawned here — :meth:`confirm` launches the run.

        Args:
            command: The parsed ``/devloop`` command (``action == "dispatch"``).
            requester: The channel-neutral identity of the caller.
            channel_id: The channel the command was issued in.

        Returns:
            The minted ``pending_id``.

        Raises:
            pydantic.ValidationError: The built brief fails validation.
            DevLoopError: ``config.max_concurrent_runs`` is reached.
        """
        self._expire_pending()
        self._check_capacity()
        if command.type == "bug":
            reporter, escalation = await self._identities(requester)
            brief: BaseModel = build_bug_brief(
                command, requester, self.config, reporter=reporter, escalation_assignee=escalation
            )
        else:
            brief = build_feature_brief(command, self.config)

        now = time.time()
        pending = PendingConfirmation(
            pending_id=uuid.uuid4().hex[:12],
            kind=command.type or "feature",
            brief=brief.model_dump(mode="json"),
            fields=brief_summary_fields(brief),
            requester=requester,
            channel_id=channel_id,
            created_at=now,
            expires_at=now + _PENDING_TTL,
        )
        self._pending[pending.pending_id] = pending
        pending.message_ts = (
            await self._safe_call(
                self.transport.post_confirm, pending.pending_id, pending.kind, pending.fields, requester, channel_id
            )
            or ""
        )
        return pending.pending_id

    # -- cross-lane read accessors (used by the Slack handlers, TASK-3206/3207) ----

    def record(self, run_id: str) -> Optional[RunRecord]:
        """In-memory lookup only (no Redis) — safe inside a Slack 3s ack / trigger_id window."""
        return self.registry.peek(run_id)

    def pending(self, pending_id: str) -> Optional[PendingConfirmation]:
        """Look up a not-yet-confirmed dispatch by its pending id."""
        return self._pending.get(pending_id)

    def record_by_thread(self, channel_id: str, thread_ts: str) -> Optional[RunRecord]:
        """Match ``RunRecord.channel_id`` + ``thread_ts`` (thread-reply interceptor)."""
        return next(
            (r for r in self.registry.all_records() if r.channel_id == channel_id and r.thread_ts == thread_ts),
            None,
        )

    async def confirm(
        self, pending_id: str, requester: Requester, overrides: Optional[Dict[str, Any]] = None
    ) -> RunRecord:
        """Launch a previously-parked dispatch.

        Args:
            pending_id: The pending confirmation's id.
            requester: The caller — must be the original requester.
            overrides: Optional Edit-modal field overrides, re-validated
                against the brief model.

        Returns:
            The launched :class:`RunRecord`.

        Raises:
            RunNotFoundError: No such pending confirmation (or it expired).
            NotRunOwnerError: ``requester`` did not originate the dispatch.
        """
        pending = self._get_pending_or_raise(pending_id)
        if pending.requester.actor != requester.actor:
            raise NotRunOwnerError(pending.requester.user_id)
        self._pending.pop(pending_id, None)

        brief_data = {**pending.brief, **(overrides or {})}
        brief = _BRIEF_MODEL[pending.kind](**brief_data)
        fields = brief_summary_fields(brief)
        title = fields.get("title") or fields.get("summary") or pending.kind

        record = await self._launch(brief, pending.kind, title, requester, pending.channel_id)
        await self._safe_call(self.transport.update_confirm, pending_id, "confirmed", record)
        return record

    async def discard(self, pending_id: str, requester: Requester) -> None:
        """Drop a pending confirmation without launching it.

        Args:
            pending_id: The pending confirmation's id.
            requester: The caller — must be the original requester.

        Raises:
            RunNotFoundError: No such pending confirmation (or it expired).
            NotRunOwnerError: ``requester`` did not originate the dispatch.
        """
        pending = self._get_pending_or_raise(pending_id)
        if pending.requester.actor != requester.actor:
            raise NotRunOwnerError(pending.requester.user_id)
        self._pending.pop(pending_id, None)
        await self._safe_call(self.transport.update_confirm, pending_id, "discarded", None)

    # -- commands ------------------------------------------------------------------

    async def answer_gate(
        self, run_id: str, gate_id: str, requester: Requester, answers: Dict[str, str]
    ) -> BridgeResult:
        """Approve an ``open_questions`` gate with structured answers."""
        record = await self._require_owned(run_id, requester)
        return await self._channel(record).resolve_gate(
            run_id, gate_id, resolution="approved", resolved_by=requester.actor, answers=answers
        )

    async def resolve_gate(
        self, run_id: str, gate_id: str, requester: Requester, resolution: str, comment: str = ""
    ) -> BridgeResult:
        """Approve or reject any other gate kind, with an optional comment."""
        record = await self._require_owned(run_id, requester)
        return await self._channel(record).resolve_gate(
            run_id, gate_id, resolution=resolution, resolved_by=requester.actor, comment=comment
        )

    async def cancel(self, run_id: str, requester: Requester) -> BridgeResult:
        """Cancel a run; escalate to ``terminate()`` if it does not exit in time (S7).

        Args:
            run_id: The run to cancel.
            requester: The caller — must be the run's initiator.

        Returns:
            The bridge result of the cancel POST.
        """
        record = await self._require_owned(run_id, requester)
        result = await self._channel(record).cancel(run_id, requested_by=requester.actor)
        if result.ok and run_id in self._processes:
            self._track(self._escalate_cancel(run_id), name=f"devloop-cancel-escalate-{run_id}")
        return result

    async def status(self, requester: Requester) -> List[RunRecord]:
        """List every run the caller initiated."""
        return await self.registry.list_for(requester.actor)

    def pending_gate(self, run_id: str) -> Optional[GateView]:
        """The run's current pending gate, if any."""
        return self._gates.get(run_id)

    # -- internals -----------------------------------------------------------------

    async def _identities(self, requester: Requester) -> Tuple[str, str]:
        """Resolve ``(reporter, escalation_assignee)`` — resolver first (Q3).

        Falls back to :func:`default_identities` when no resolver is
        configured, it raises, or it returns an empty identity — never a
        raw Slack id.
        """
        if self._identity_resolver is not None:
            try:
                reporter, escalation = await self._identity_resolver(requester)
                if reporter and escalation:
                    return reporter, escalation
            except Exception:  # noqa: BLE001 - resolver is best-effort
                self.logger.exception("identity_resolver failed for %s; falling back", requester.actor)
        return await default_identities(self._jira_toolkit)

    async def _require_owned(self, run_id: str, requester: Requester) -> RunRecord:
        record = await self.registry.get(run_id)
        if record is None:
            raise RunNotFoundError(run_id)
        if record.requester.actor != requester.actor:
            raise NotRunOwnerError(record.requester.user_id)  # .owner_user_id → Slack renders "<@owner>"
        return record

    def _channel(self, record: RunRecord) -> RunCommandChannel:
        return self._channels.setdefault(
            record.run_id, LoopbackRestChannel(record.command_endpoint, token=record.command_token)
        )

    def _track(self, coro: Awaitable[Any], name: str = "") -> "asyncio.Task":
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _safe_call(self, func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        """Call a transport method; log and swallow any exception (spec §7)."""
        try:
            return await func(*args, **kwargs)
        except Exception:  # noqa: BLE001 - a transport failure must never affect the run
            self.logger.exception("devloop transport call %s failed", getattr(func, "__name__", func))
            return None

    async def _launch(
        self, brief: BaseModel, kind: RequestType, title: str, requester: Requester, channel_id: str
    ) -> RunRecord:
        """Mint ids, spawn the headless child, await its handshake, and start tailing it (spec M8)."""
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        token = secrets.token_urlsafe(32)

        socket_dir = self.config.socket_dir or os.path.join(tempfile.gettempdir(), "parrot-devloop")
        os.makedirs(socket_dir, mode=0o700, exist_ok=True)
        brief_path = brief_to_file(brief, socket_dir, run_id)

        socket_path: Optional[str] = None
        port: Optional[int] = None
        if self.config.use_tcp:
            port = 0
        else:
            socket_path = os.path.join(socket_dir, f"{run_id}.sock")
            if len(socket_path.encode("utf-8")) > _AF_UNIX_MAX_PATH:
                self.logger.warning("devloop socket path %s exceeds the AF_UNIX length limit (~108 bytes)", socket_path)

        record = RunRecord(
            run_id=run_id,
            kind=kind,
            title=title,
            requester=requester,
            channel_id=channel_id,
            command_token=token,
            phase="starting",
            brief_path=brief_path,
            started_at=time.time(),
        )

        process: Optional[HeadlessRunProcess] = None
        try:
            process = await HeadlessRunProcess.spawn(
                config=self.config,
                run_id=run_id,
                brief_path=brief_path,
                socket_path=socket_path,
                port=port,
                token=token,
            )
            handshake = await process.wait_ready(self.config.handshake_timeout_seconds)
        except SpawnError as exc:
            record.phase = "failed"
            record.error = str(exc)
            await self.registry.save(record)
            await self._safe_call(self.transport.post_spawn_failed, record, str(exc))
            if process is not None:
                process.cleanup()
            raise

        record.command_endpoint = handshake.command_endpoint
        record.pid = handshake.pid
        record.phase = "running"
        self._processes[run_id] = process

        record.thread_ts = await self._safe_call(self.transport.post_run_dispatched, record) or ""
        await self.registry.save(record)

        self._track(self._tail(record), name=f"devloop-tail-{run_id}")
        self._track(self._supervise(record), name=f"devloop-supervise-{run_id}")

        await self._safe_call(self.transport.post_run_started, record)
        return record

    async def _tail(self, record: RunRecord, *, last_seen: Optional[int] = None) -> None:
        tail = RunStateTail(self._redis, record.run_id)
        async for event in tail.events(last_seen=last_seen):
            await self._handle_event(record, event)

    async def _handle_event(self, record: RunRecord, event: RunEvent) -> None:
        """Fold one ``RunEvent`` into the record and render it; transport errors never raise."""
        record.last_seen_seq = max(record.last_seen_seq, event.seq)

        if event.kind == "gate_opened" and event.gate is not None:
            record.pending_gate_id = event.gate.gate_id
            record.phase = "blocked"
            self._gates[record.run_id] = event.gate
            await self.registry.save(record)
            await self._safe_call(self.transport.post_gate, record, event.gate)
            return

        if event.kind in ("gate_resolved", "gate_expired") and event.gate is not None:
            record.pending_gate_id = ""
            record.phase = "running"
            self._gates.pop(record.run_id, None)
            await self.registry.save(record)
            await self._safe_call(self.transport.update_gate, record, event.gate)
            return

        if event.kind == "node_changed":
            record.current_node = event.node_id
            await self.registry.save(record)
            if self.config.status_card:
                await self._safe_call(self.transport.update_status, record, event.state or {})
            return

        if event.kind == "jira_linked":
            record.jira_issue_key = (event.state or {}).get("jira_issue_key", "") or record.jira_issue_key
            await self.registry.save(record)
            return

        if event.kind in ("run_closed", "run_cancelled", "process_exited"):
            state = event.state or {}
            if event.kind == "run_closed":
                record.phase = "completed" if state.get("outcome") == "succeeded" else "failed"
                record.pr_url = state.get("pr_url", "") or record.pr_url
                record.jira_issue_key = state.get("jira_issue_key", "") or record.jira_issue_key
            elif event.kind == "run_cancelled":
                record.phase = "cancelled"
            else:  # process_exited
                record.phase = "completed" if event.exit_code == 0 else "failed"
                record.exit_code = event.exit_code
                record.error = event.stderr_tail or record.error
            record.finished_at = time.time()
            await self.registry.save(record)
            await self.registry.mark_terminal(record.run_id)
            await self._safe_call(self.transport.post_terminal, record, event)
            return

        # snapshot and any other forward-compat kind: persist last_seen_seq only.
        await self.registry.save(record)

    async def _supervise(self, record: RunRecord) -> None:
        """Bounded supervisor (S8): child exit → drain window → ``process_exited`` if the tail delivered nothing."""
        process = self._processes.get(record.run_id)
        if process is None:
            return
        code = await process.wait()
        await asyncio.sleep(self.config.tail_drain_seconds)

        current = await self.registry.get(record.run_id) or record
        if current.phase not in _TERMINAL:
            event = RunEvent(
                run_id=record.run_id, kind="process_exited", exit_code=code, stderr_tail=process.stderr_tail()
            )
            await self._handle_event(current, event)

        for task in list(self._tasks):
            if task.get_name() == f"devloop-tail-{record.run_id}":
                task.cancel()

        await self.registry.mark_terminal(record.run_id)
        process.cleanup()
        self._processes.pop(record.run_id, None)

    async def _escalate_cancel(self, run_id: str) -> None:
        """S7: if the child has not reached a terminal phase within ``cancel_grace_seconds``, terminate it."""
        await asyncio.sleep(self.config.cancel_grace_seconds)
        record = await self.registry.get(run_id)
        process = self._processes.get(run_id)
        if record is not None and record.phase not in _TERMINAL and process is not None:
            await process.terminate()

    def _expire_pending(self) -> None:
        now = time.time()
        for pid in [p for p, pc in self._pending.items() if now > pc.expires_at]:
            self._pending.pop(pid, None)

    def _get_pending_or_raise(self, pending_id: str) -> PendingConfirmation:
        """Look up a pending confirmation, treating an expired one as not-found."""
        pending = self._pending.get(pending_id)
        if pending is None:
            raise RunNotFoundError(pending_id)
        if time.time() > pending.expires_at:
            self._pending.pop(pending_id, None)
            raise RunNotFoundError(pending_id)
        return pending

    def _check_capacity(self) -> None:
        """Enforce the optional soft cap on concurrent runs (``None`` = unlimited, decision)."""
        if self.config.max_concurrent_runs is None:
            return
        live_count = sum(1 for r in self.registry.all_records() if r.phase not in _TERMINAL)
        if live_count >= self.config.max_concurrent_runs:
            raise DevLoopError(f"max_concurrent_runs ({self.config.max_concurrent_runs}) reached")
