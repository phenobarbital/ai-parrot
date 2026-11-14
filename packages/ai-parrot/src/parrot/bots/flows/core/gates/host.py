"""Generic gate host (FEAT-890 M1)."""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Awaitable, Callable, Literal, Mapping

from parrot.human.models import HumanInteraction, InteractionType

from .kinds import is_registered
from .models import GateError, GateErrorCode, GateEvent, GateRecord, GateSpec, GateStore, PreReviewVerdict

if TYPE_CHECKING:
    from parrot.human import HumanInteractionManager


AUTO_APPROVER = "system:ttl-auto-approve"
Listener = Callable[[GateEvent], Awaitable[None]]


class GateHost:
    """Open, resolve, expire and recover gates over a GateStore."""

    def __init__(
        self,
        store: GateStore,
        *,
        notifier: "HumanInteractionManager | None" = None,
        pre_reviewer: Callable[[GateRecord], Awaitable[PreReviewVerdict]] | None = None,
    ) -> None:
        """Initialize the host with persistence and optional delivery hooks.

        Args:
            store: Durable storage for gate records.
            notifier: Optional manager for non-blocking human delivery.
            pre_reviewer: Optional advisory reviewer invoked for requested reviews.
        """
        self.store = store
        self.notifier = notifier
        self.pre_reviewer = pre_reviewer
        self._listeners: list[Listener] = []
        self.logger = logging.getLogger(__name__)

    def subscribe(self, listener: Listener) -> None:
        """Register an async listener for GateEvent.

        Args:
            listener: Listener called after each persisted lifecycle event.
        """
        self._listeners.append(listener)

    async def open(self, spec: GateSpec, *, owner: str, payload_ref: str = "") -> GateRecord:
        """Persist a pending gate, run pre-review, and notify humans.

        Args:
            spec: Definition of the requested gate.
            owner: Flow run or node identifier that owns the gate.
            payload_ref: Optional reference to supporting evidence.

        Returns:
            The newly persisted gate record.

        Raises:
            GateError: If the requested gate kind was not registered.
        """
        if not is_registered(spec.kind):
            raise GateError(GateErrorCode.UNKNOWN_KIND, spec.kind)

        now = time.time()
        record = GateRecord(
            gate_id=uuid.uuid4().hex,
            kind=spec.kind,
            owner=owner,
            spec=spec,
            payload_ref=payload_ref,
            opened_at=now,
            expires_at=(now + spec.ttl_seconds) if spec.ttl_seconds else None,
        )
        if spec.pre_review and self.pre_reviewer is not None:
            try:
                verdict = await self.pre_reviewer(record)
            except Exception as exc:
                self.logger.exception("pre-review failed for gate %s", record.gate_id)
                verdict = PreReviewVerdict(
                    expert=spec.pre_review,
                    recommendation="unsure",
                    summary="",
                    error=str(exc),
                )
            record = record.model_copy(update={"pre_review": verdict})

        await self.store.put(record)
        await self._emit(GateEvent(type="opened", record=record))
        await self._notify(record)
        return record

    async def resolve(
        self,
        gate_id: str,
        resolution: Literal["approved", "rejected"],
        *,
        resolved_by: str,
        comment: str = "",
        answers: Mapping[str, str] | None = None,
    ) -> GateRecord:
        """Resolve a pending gate.

        Args:
            gate_id: Identifier of the gate to resolve.
            resolution: Human approval or rejection.
            resolved_by: Identity of the resolving actor.
            comment: Optional explanatory comment.
            answers: Optional answers to the gate's questions.

        Returns:
            The updated gate record.

        Raises:
            GateError: If the gate is missing or no longer pending.
        """
        record = await self.store.get(gate_id)
        if record is None:
            raise GateError(GateErrorCode.NOT_FOUND, gate_id)
        if record.status != "pending":
            raise GateError(GateErrorCode.NOT_PENDING, gate_id)

        resolved = record.model_copy(
            update={
                "status": resolution,
                "resolved_by": resolved_by,
                "resolved_at": time.time(),
                "comment": comment,
                "answers": dict(answers or {}),
            }
        )
        await self.store.put(resolved)
        await self._emit(GateEvent(type="resolved", record=resolved))
        return resolved

    async def recover(self, *, now: float | None = None) -> list[GateRecord]:
        """Apply expiry policies to elapsed pending gates.

        Args:
            now: Optional clock value used to make recovery deterministic.

        Returns:
            Records transitioned by this recovery pass.
        """
        current_time = time.time() if now is None else now
        recovered: list[GateRecord] = []
        for record in await self.store.pending():
            if record.expires_at is None or current_time < record.expires_at:
                continue
            if record.spec.on_expiry == "approve":
                updated = record.model_copy(
                    update={
                        "status": "approved",
                        "resolved_by": AUTO_APPROVER,
                        "resolved_at": current_time,
                        "comment": "TTL expired; fail-open policy.",
                    }
                )
                event_type: Literal["resolved", "expired"] = "resolved"
            else:
                updated = record.model_copy(update={"status": "expired"})
                event_type = "expired"
            await self.store.put(updated)
            await self._emit(GateEvent(type=event_type, record=updated))
            recovered.append(updated)
        return recovered

    async def _notify(self, record: GateRecord) -> None:
        """Deliver a non-blocking human interaction for an opened gate.

        Args:
            record: Persisted record to present to a human.
        """
        if self.notifier is None:
            return
        interaction = HumanInteraction(
            question=record.spec.title,
            context=f"Gate {record.gate_id}: {record.spec.instructions}",
            interaction_type=InteractionType.FREE_TEXT,
            timeout=float(record.spec.ttl_seconds or 7200),
            source_node=record.owner,
        )
        try:
            await self.notifier.request_human_input_async(interaction)
        except Exception:
            self.logger.exception("human notification failed for gate %s", record.gate_id)

    async def _emit(self, event: GateEvent) -> None:
        """Best-effort emit a gate lifecycle event to all listeners.

        Args:
            event: Persisted lifecycle event to publish.
        """
        for listener in self._listeners:
            try:
                await listener(event)
            except Exception:
                self.logger.exception("gate listener failed for %s", event.record.gate_id)
