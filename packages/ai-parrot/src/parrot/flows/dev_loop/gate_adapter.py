"""Bridge dev-loop ApprovalGate ⇄ generic GateRecord (FEAT-890 M3).

Persisted dev-loop runs carry :class:`ApprovalGate` objects inside the
Redis-streamed ``gate/opened`` actions. :class:`DevLoopGateAdapter` converts
them losslessly to and from the generic :class:`GateRecord` of
``parrot.bots.flows.core.gates`` so they survive the gate-host hard cut.

Field mapping (``ApprovalGate`` → ``GateRecord``):

* ``gate_id``, ``kind``, ``status``, ``payload_ref``, ``opened_at``,
  ``expires_at``, ``resolved_by``, ``resolved_at``, ``comment``, ``answers``
  map 1:1 onto the record's top-level fields.
* ``title``, ``instructions``, ``questions``, ``on_expiry`` live in the
  record's :class:`GateSpec`; ``spec.ttl_seconds`` is derived as
  ``round(expires_at - opened_at)`` when the gate has an expiry. The exact
  ``expires_at`` stays on the record, so the derived TTL never loses data.
* ``node_id`` has no slot in ``GateRecord`` (``payload_ref`` already holds
  the evidence URI and the model is closed). Decision: the adapter does
  NOT encode it; the caller owns it — it is passed back explicitly to
  :meth:`DevLoopGateAdapter.from_record`. Callers that need to recover it
  from the record alone use the owner convention ``f"{run_id}:{node_id}"``
  when calling :meth:`DevLoopGateAdapter.to_record`.
"""

from __future__ import annotations

from typing import get_args

from parrot.bots.flows.core.gates import (
    GateError,
    GateErrorCode,
    GateRecord,
    GateSpec,
    is_registered,
    register_gate_kind,
)

from .session_state import ApprovalGate, GateKind

__all__ = ["DevLoopGateAdapter", "register_devloop_gate_kinds"]

_DEVLOOP_KINDS: tuple[str, ...] = get_args(GateKind)


def register_devloop_gate_kinds() -> None:
    """Register every dev-loop GateKind as a generic string kind (idempotent)."""
    for kind in _DEVLOOP_KINDS:
        register_gate_kind(kind, description=f"dev-loop {kind}")


class DevLoopGateAdapter:
    """Lossless conversion for persisted dev-loop gates."""

    @staticmethod
    def to_record(gate: ApprovalGate, *, owner: str) -> GateRecord:
        """Convert a dev-loop gate into a generic gate record.

        Args:
            gate: The persisted dev-loop gate.
            owner: Record owner (by convention ``f"{run_id}:{node_id}"``).

        Returns:
            The equivalent :class:`GateRecord`; ``gate.node_id`` is not
            stored (see the module docstring).

        Raises:
            GateError: ``UNKNOWN_KIND`` when ``gate.kind`` is not a registered
                gate kind (call :func:`register_devloop_gate_kinds` first).
        """
        if not is_registered(gate.kind):
            raise GateError(
                GateErrorCode.UNKNOWN_KIND,
                f"gate {gate.gate_id!r} has unregistered kind {gate.kind!r}",
            )
        ttl_seconds = round(gate.expires_at - gate.opened_at) if gate.expires_at is not None else None
        spec = GateSpec(
            kind=gate.kind,
            title=gate.title,
            instructions=gate.instructions,
            questions=list(gate.questions),
            ttl_seconds=ttl_seconds,
            on_expiry=gate.on_expiry,
        )
        return GateRecord(
            gate_id=gate.gate_id,
            kind=gate.kind,
            owner=owner,
            status=gate.status,
            spec=spec,
            payload_ref=gate.payload_ref,
            opened_at=gate.opened_at,
            expires_at=gate.expires_at,
            resolved_by=gate.resolved_by,
            resolved_at=gate.resolved_at,
            comment=gate.comment,
            answers=dict(gate.answers),
        )

    @staticmethod
    def from_record(record: GateRecord, *, node_id: str) -> ApprovalGate:
        """Inverse of :meth:`to_record`.

        Args:
            record: A gate record produced by :meth:`to_record`.
            node_id: The dev-loop node that opened the gate.

        Returns:
            The :class:`ApprovalGate`; ``from_record(to_record(g), node_id=g.node_id) == g``.

        Raises:
            GateError: ``UNKNOWN_KIND`` when ``record.kind`` is not a dev-loop
                gate kind.
            pydantic.ValidationError: ``node_id`` is not a dev-loop node id.
        """
        if record.kind not in _DEVLOOP_KINDS:
            raise GateError(
                GateErrorCode.UNKNOWN_KIND,
                f"gate {record.gate_id!r} has non dev-loop kind {record.kind!r}",
            )
        return ApprovalGate(
            gate_id=record.gate_id,
            kind=record.kind,
            node_id=node_id,
            status=record.status,
            on_expiry=record.spec.on_expiry,
            title=record.spec.title,
            instructions=record.spec.instructions,
            payload_ref=record.payload_ref,
            opened_at=record.opened_at,
            expires_at=record.expires_at,
            resolved_by=record.resolved_by,
            resolved_at=record.resolved_at,
            comment=record.comment,
            questions=list(record.spec.questions),
            answers=dict(record.answers),
        )
