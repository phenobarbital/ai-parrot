"""The ONLY Roost module that names the Squawk satellite (FEAT-747 M11, resolved Q1).

Every satellite import is inside a function body; without the satellite Roost degrades, never fails.
"""

from __future__ import annotations

import functools
import importlib
import importlib.util
import logging
from typing import TYPE_CHECKING, Any, Final, Optional, Sequence

from parrot.core.events.lifecycle import TraceContext

from .codec import EnvelopeCodec, JsonEnvelopeCodec
from .directory import CapabilityMatch
from .messages import LocalEnvelope, RoostMessage

if TYPE_CHECKING:
    from parrot.tools.manager import ToolManager

logger = logging.getLogger(__name__)

SQUAWK_MODULE: Final[str] = "parrot.squawk"  # confirmed by the FEAT-746 spec (M0)
_WARNED = False


class SquawkUnavailable(RuntimeError):
    """A satellite feature was required but ``parrot.squawk`` is not installed."""


@functools.lru_cache(maxsize=1)
def squawk_available() -> bool:
    """Return whether the satellite namespace resolves, cached per process."""
    try:
        return importlib.util.find_spec(SQUAWK_MODULE) is not None
    except (ModuleNotFoundError, ValueError):
        return False


class SquawkCodecAdapter:
    """EnvelopeCodec over the satellite codec and bus payload serializer."""

    content_type = "application/x-squawk"

    def __init__(self) -> None:
        """Load the optional codec components only after the satellite probe succeeds.

        Raises:
            SquawkUnavailable: The satellite or one of its codec components cannot be imported.
        """
        if not squawk_available():
            raise SquawkUnavailable(f"{SQUAWK_MODULE} is not installed")
        try:
            self._codec = importlib.import_module(f"{SQUAWK_MODULE}.schema.codec")
            bus_module = importlib.import_module(f"{SQUAWK_MODULE}.transport.bus")
            self._serializer = bus_module.BusPayloadSerializer()
        except (ImportError, AttributeError) as exc:
            raise SquawkUnavailable("Squawk codec components are unavailable") from exc

    def encode(self, msg: RoostMessage) -> bytes:
        """Encode a Roost message through the satellite payload and binary codecs."""
        payload = self._serializer.to_payload(msg)
        return self._codec.encode(payload)

    def decode(self, data: bytes) -> RoostMessage:
        """Decode satellite bytes into a Roost message."""
        payload = self._codec.decode(data)
        return self._serializer.from_payload(payload)


def load_codec() -> EnvelopeCodec:
    """Return the satellite codec when available, otherwise the JSON fallback."""
    if squawk_available():
        try:
            return SquawkCodecAdapter()
        except (ImportError, SquawkUnavailable):
            logger.warning("Squawk codec unavailable; falling back to JSON envelope codec")
    return JsonEnvelopeCodec()


def new_envelope(
    *,
    correlation_id: str,
    caller: str,
    trace: Optional[TraceContext] = None,
    budget_ms: Optional[int] = None,
    token_budget: Optional[int] = None,
    idempotency_key: Optional[str] = None,
) -> Any:
    """Return a satellite CallMessage when available, otherwise a LocalEnvelope."""
    local = LocalEnvelope(
        correlation_id=correlation_id,
        caller=caller,
        trace=trace,
        budget_ms=budget_ms,
        token_budget=token_budget,
        idempotency_key=idempotency_key,
    )
    if squawk_available():
        try:
            messages_module = importlib.import_module(f"{SQUAWK_MODULE}.schema.messages")
            return messages_module.CallMessage(
                envelope_id=local.envelope_id,
                cap_id="",
                contract_hash="",
                args=b"",
                out_hints={},
                budget={"ms": budget_ms, "tokens": token_budget, "rows": None},
                trace_id=trace.trace_id if trace is not None else "",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key or local.envelope_id,
                reply_to=None,
                caller=caller,
            )
        except (ImportError, AttributeError):
            logger.warning("Squawk envelope unavailable; falling back to local envelope")
    return local


def _warn_mount_unavailable() -> None:
    """Log the degraded mount warning once per process."""
    global _WARNED
    if not _WARNED:
        logger.warning("Squawk satellite not installed — capability mount skipped (FEAT-747 Q1)")
        _WARNED = True


async def mount_capabilities(tool_manager: "ToolManager", matches: Sequence[CapabilityMatch]) -> list[str]:
    """Mount each matched satellite capability, degrading to an empty list when unavailable."""
    if not squawk_available():
        _warn_mount_unavailable()
        return []

    try:
        toolkit_module = importlib.import_module(f"{SQUAWK_MODULE}.client.toolkit")
        toolkit_class = toolkit_module.SquawkRemoteToolkit
    except (ImportError, AttributeError):
        _warn_mount_unavailable()
        return []

    mounted: list[str] = []
    try:
        for match in matches:
            toolkit = toolkit_class(remote=match.agent_name, tool_manager=tool_manager, landing=None)
            mounted_name = await toolkit.catalog_mount(match.cap_id)
            mounted.append(mounted_name)
    except (ImportError, AttributeError):
        _warn_mount_unavailable()
        return []
    return mounted


def resolve_authority(msg: RoostMessage) -> Any:
    """Prefer verified token authority, falling back to the serialized permission context."""
    if not msg.auth_token or not squawk_available():
        return msg.permission_context

    try:
        biscuit_module = importlib.import_module(f"{SQUAWK_MODULE}.security.biscuit")
        verifier = biscuit_module.BiscuitVerifier()
        scope = verifier.parse(msg.auth_token.encode("utf-8"))
    except Exception:  # noqa: BLE001 - optional verifier failures must preserve the fallback authority
        return msg.permission_context
    return getattr(scope, "permission_context", scope)
