"""The only human-readable view of Squawk traffic (D2): ledger entries and stored bus envelopes."""

from __future__ import annotations

import hashlib
from typing import Any

from parrot.interagent import (
    BusPayloadSerializer,
    CallMessage,
    ProgressMessage,
    ResultMessage,
    ServedLedgerEntry,
    CancelMessage,
)

_SER = BusPayloadSerializer()


def _bytes_repr(b: bytes | None) -> str:
    return "-" if b is None else f"<{len(b)} bytes sha256:{hashlib.sha256(b).hexdigest()[:12]}…>"


def render_entry(e: ServedLedgerEntry) -> str:
    """One line per field group; never payloads."""
    return (
        f"[{e.created_at.isoformat()}] {e.status if isinstance(e.status, str) else e.status.value} {e.cap_id} "
        f"caller={e.caller.agent_id}@{e.caller.network} backing={e.backing} args={e.args_digest[:19]} "
        f"result={e.result_kind}:{(e.result_digest or '-')[:19]} cost={e.cost.duration_ms}ms/{e.cost.tokens_in}+{e.cost.tokens_out}tok "
        f"policy={','.join(e.policy_applied) or '-'} classes={','.join(e.data_classes) or '-'} trace={e.trace_id} sig={e.signature[:12]}…"
    )


def render_envelope(payload: dict[str, Any]) -> str:
    """Decode a bus payload (BusPayloadSerializer) and pretty-print it; bytes fields become digests."""
    msg = _SER.from_payload(payload)
    if isinstance(msg, CallMessage):
        return f"CALL {msg.cap_id} hash={msg.contract_hash[:19]} args={_bytes_repr(msg.args)} budget={msg.budget.model_dump()} corr={msg.correlation_id} idem={msg.idempotency_key} trace={msg.trace_id}"
    if isinstance(msg, ResultMessage):
        status = msg.status if isinstance(msg.status, str) else msg.status.value
        handle_str = "-"
        if msg.handle:
            # Bounded summary only: the descriptor's summary may carry preview rows (payload data).
            handle_str = f"{msg.handle.key[:19]}…({msg.handle.media_type.value},{msg.handle.byte_size}B)"
        return (
            f"RESULT status={status} transfer={msg.transfer} "
            f"handle={handle_str} inline={_bytes_repr(msg.inline)} "
            f"cost={msg.cost.duration_ms}ms/{msg.cost.tokens_in}+{msg.cost.tokens_out}tok "
            f"detail={msg.detail or '-'} trace={msg.trace_id}"
        )
    if isinstance(msg, ProgressMessage):
        return f"PROGRESS op={msg.op_id} phase={msg.phase} frame#{msg.frame_index} {_bytes_repr(msg.frame)} last={msg.is_last}"
    if isinstance(msg, CancelMessage):
        return f"CANCEL op={msg.op_id} trace={msg.trace_id}"
    return "UNKNOWN"
