"""Authenticated worker-to-worker speaker relay (FEAT-537 — Module 4).

Spec §2: "For a socket connected to another worker, an internal aiohttp
WebSocket relay authenticates the worker and carries participant/owner/floor
epochs in bounded messages.  Public clients cannot select an owner address …
No raw microphone audio in Redis pub/sub.  Live objects stay on the producer
process."

The shape of the problem: a participant's browser can land on **any** HTTP
worker, but the VoiceBot, the avatar session and the LiveKit publishers live
only on the worker that won ``claim_owner``.  When the granted speaker's socket
is not on that worker, their microphone PCM has to cross one hop — and that hop
is the most security-sensitive surface in the feature, because anything that
reaches it is about to be spoken by the agent to the whole audience.

Hence, deliberately:

* **The owner's address is never client-supplied.**  It comes from
  :class:`WorkerAddressRegistry`, written by workers themselves, and any value
  that is not a ``ws(s)://`` URL is refused outright.
* **Every frame re-states the full fencing tuple** (owner epoch, lease, floor
  epoch, turn, sequence) and is re-validated *on the owner* immediately before
  ``push_audio``.  Passing ingress validation is not a permit.
* **A stale owner epoch closes the connection** rather than being tolerated.
* Bounded message size, bounded queue, idle timeout, and a constant-time shared
  service token compared with :func:`hmac.compare_digest`.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hmac
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

import aiohttp
from aiohttp import WSMsgType, web

from parrot.integrations.liveavatar.broadcast.errors import BroadcastError
from parrot.integrations.liveavatar.broadcast.models import BroadcastReason

_logger = logging.getLogger(__name__)

#: Route the owner worker exposes.  Internal: never mounted on a public app.
RELAY_ROUTE: str = "/internal/voice-broadcast/relay"

#: Header carrying the per-deployment shared service token.
WORKER_TOKEN_HEADER: str = "X-Parrot-Broadcast-Worker-Token"

#: Environment variable holding that token.
WORKER_TOKEN_ENV: str = "PARROT_BROADCAST_WORKER_TOKEN"

#: Hard cap on one relayed message.  ~128 KiB is far above a 1 s 16 kHz PCM16
#: frame (32 000 bytes raw, ~42 700 base64), so a larger message is a bug or an
#: attack, not a big microphone chunk.
MAX_RELAY_MESSAGE_BYTES: int = 128 * 1024

#: Idle timeout for a relay connection.
RELAY_IDLE_TIMEOUT_S: float = 15.0

#: Bounded outbound queue on the ingress side.
RELAY_QUEUE_MAX_FRAMES: int = 64

#: WebSocket close code for "message too big" (RFC 6455).
WS_CLOSE_TOO_BIG: int = 1009

#: WebSocket close code used when the sender has been fenced.
WS_CLOSE_POLICY_VIOLATION: int = 1008

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


class WorkerTransportError(BroadcastError):
    """The relay refused or lost the connection."""


def resolve_worker_token(explicit: Optional[str] = None) -> Optional[str]:
    """Return the shared worker token from the argument or the environment.

    Args:
        explicit: A token supplied by the caller, if any.

    Returns:
        The token, or ``None`` when none is configured.
    """
    return explicit or os.environ.get(WORKER_TOKEN_ENV) or None


def _is_loopback(url: str) -> bool:
    """Whether ``url`` points at the local machine.

    Args:
        url: A ``ws(s)://`` URL.

    Returns:
        ``True`` for loopback hosts.
    """
    host = (urlparse(url).hostname or "").lower()
    return host in _LOOPBACK_HOSTS


class WorkerAddressRegistry:
    """Maps worker ids to their internal relay URLs.

    Backed by a Redis hash so every worker can resolve the current producer's
    address, and refreshed with a TTL so a dead worker's address disappears.

    The only write path is a worker registering **itself**; the only read path
    returns what was registered.  A client can name a *worker id* (indirectly,
    by which broadcast it joined) but never a URL.

    Args:
        redis_client: An ``redis.asyncio.Redis`` with ``decode_responses=True``,
            or ``None`` for a purely in-process registry (single-worker
            deployments and tests).
        key_prefix: Namespace for the workers hash.
        ttl_s: Registration lifetime.
    """

    def __init__(
        self,
        redis_client: Any = None,
        *,
        key_prefix: str = "parrot:voice-broadcast",
        ttl_s: int = 30,
    ) -> None:
        self._redis = redis_client
        self._key = f"{key_prefix}:workers"
        self._ttl_s = ttl_s
        self._local: Dict[str, str] = {}
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def validate_url(url: str) -> str:
        """Reject anything that is not a WebSocket URL.

        Args:
            url: Candidate address.

        Returns:
            The validated URL.

        Raises:
            WorkerTransportError: If the scheme is not ``ws``/``wss`` or the
                host is missing.  This is the choke point that stops an
                attacker-influenced value ever becoming an outbound connection.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("ws", "wss") or not parsed.hostname:
            raise WorkerTransportError(message=f"refusing non-WebSocket worker address: {url!r}")
        return url

    async def register(self, worker_id: str, url: str) -> None:
        """Advertise this worker's relay address.

        Args:
            worker_id: The worker registering itself.
            url: Its internal relay URL.

        Raises:
            WorkerTransportError: If ``url`` is not a WebSocket URL.
        """
        self.validate_url(url)
        self._local[worker_id] = url
        if self._redis is not None:
            await self._redis.hset(self._key, worker_id, url)
            await self._redis.expire(self._key, self._ttl_s * 4)

    async def unregister(self, worker_id: str) -> None:
        """Remove a worker's address."""
        self._local.pop(worker_id, None)
        if self._redis is not None:
            with contextlib.suppress(Exception):
                await self._redis.hdel(self._key, worker_id)

    async def resolve(self, worker_id: str) -> Optional[str]:
        """Look up a worker's relay URL.

        Args:
            worker_id: The worker to reach.

        Returns:
            Its validated URL, or ``None`` when it is not registered.
        """
        url = self._local.get(worker_id)
        if url is None and self._redis is not None:
            url = await self._redis.hget(self._key, worker_id)
        if url is None:
            return None
        return self.validate_url(url)


@dataclass
class RelayFrame:
    """One validated relay message.

    Attributes:
        kind: ``start_turn`` / ``audio`` / ``end_turn`` / ``release``.
        owner_epoch: Ownership generation the sender believes is current.
        lease_id: Speaker lease the audio is attributed to.
        floor_epoch: Floor generation the input was captured under.
        turn_id: Producing turn, when known.
        seq: Monotonic sequence within the turn.
        pcm: Decoded PCM, for ``audio`` frames.
    """

    kind: str
    owner_epoch: int
    lease_id: str
    floor_epoch: int
    turn_id: Optional[str] = None
    seq: int = 0
    pcm: bytes = b""

    @classmethod
    def parse(cls, raw: str) -> "RelayFrame":
        """Parse and validate one wire message.

        Args:
            raw: The JSON text received.

        Returns:
            The parsed frame.

        Raises:
            WorkerTransportError: On malformed JSON, a missing required field
                or undecodable audio.
        """
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise WorkerTransportError(message="relay frame is not JSON") from exc
        if not isinstance(payload, dict):
            raise WorkerTransportError(message="relay frame must be an object")

        kind = str(payload.get("kind", "audio"))
        try:
            owner_epoch = int(payload["owner_epoch"])
            lease_id = str(payload["lease_id"])
            floor_epoch = int(payload["floor_epoch"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkerTransportError(message="relay frame is missing its fencing tuple") from exc

        pcm = b""
        if kind == "audio":
            encoded = payload.get("pcm_b64", "")
            if not isinstance(encoded, str) or not encoded:
                raise WorkerTransportError(message="audio relay frame carries no pcm")
            try:
                pcm = base64.b64decode(encoded)
            except (ValueError, binascii.Error) as exc:
                raise WorkerTransportError(message="pcm_b64 is not valid base64") from exc

        return cls(
            kind=kind,
            owner_epoch=owner_epoch,
            lease_id=lease_id,
            floor_epoch=floor_epoch,
            turn_id=payload.get("turn_id"),
            seq=int(payload.get("seq", 0) or 0),
            pcm=pcm,
        )

    def to_wire(self) -> str:
        """Serialise this frame for the wire."""
        payload: Dict[str, Any] = {
            "kind": self.kind,
            "owner_epoch": self.owner_epoch,
            "lease_id": self.lease_id,
            "floor_epoch": self.floor_epoch,
            "seq": self.seq,
        }
        if self.turn_id is not None:
            payload["turn_id"] = self.turn_id
        if self.kind == "audio":
            payload["pcm_b64"] = base64.b64encode(self.pcm).decode("ascii")
        return json.dumps(payload)


class WorkerRelayServer:
    """Owner-side endpoint that accepts relayed speaker input.

    Mounted **only** on the worker that owns a producer, and only on an
    internal application — never on the public one.

    Args:
        service: The local :class:`BroadcastService`, used to resolve the
            producer, its owner epoch and the live voice session.
        token: Shared service token.  Falls back to
            :data:`WORKER_TOKEN_ENV`.
        require_tls: Refuse non-loopback peers that are not on TLS.
    """

    def __init__(
        self,
        service: Any,
        *,
        token: Optional[str] = None,
        require_tls: bool = True,
    ) -> None:
        self._service = service
        self._token = resolve_worker_token(token)
        self._require_tls = require_tls
        self.logger = logging.getLogger(__name__)

    def setup_routes(self, app: web.Application, prefix: str = "") -> None:
        """Mount the relay route on an **internal** aiohttp application.

        Args:
            app: The internal application.
            prefix: Optional URL prefix.

        Raises:
            WorkerTransportError: If no shared token is configured.  Refusing
                to start is the right failure: an unauthenticated relay would
                let anything that can reach the port speak as the agent.
        """
        if not self._token:
            raise WorkerTransportError(
                message=(f"{WORKER_TOKEN_ENV} must be set before mounting the broadcast " "worker relay")
            )
        app.router.add_get(f"{prefix}{RELAY_ROUTE}", self.handle_relay)
        self.logger.info("Broadcast worker relay mounted at %s%s", prefix, RELAY_ROUTE)

    def _authorized(self, request: web.Request) -> bool:
        """Constant-time comparison of the shared service token."""
        supplied = request.headers.get(WORKER_TOKEN_HEADER, "")
        if not supplied or not self._token:
            return False
        return hmac.compare_digest(supplied, self._token)

    def _transport_allowed(self, request: web.Request) -> bool:
        """Whether the peer may speak plaintext.

        Loopback is exempt; anything else must be TLS when ``require_tls``.
        """
        if not self._require_tls:
            return True
        if request.secure:
            return True
        peer = request.remote or ""
        return peer in _LOOPBACK_HOSTS

    async def handle_relay(self, request: web.Request) -> web.WebSocketResponse:
        """Accept one ingress worker's relayed speaker input.

        Args:
            request: The internal request.

        Returns:
            The prepared WebSocket response.

        Raises:
            web.HTTPUnauthorized: On a missing/incorrect service token.
            web.HTTPForbidden: On a plaintext non-loopback peer.
        """
        if not self._authorized(request):
            raise web.HTTPUnauthorized(reason="invalid worker token")
        if not self._transport_allowed(request):
            raise web.HTTPForbidden(reason="TLS required for non-loopback relay")

        tenant_id = request.query.get("tenant_id", "")
        broadcast_id = request.query.get("broadcast_id", "")

        ws = web.WebSocketResponse(max_msg_size=MAX_RELAY_MESSAGE_BYTES, heartbeat=RELAY_IDLE_TIMEOUT_S)
        await ws.prepare(request)

        accepted = 0
        rejected = 0
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=RELAY_IDLE_TIMEOUT_S)
                except asyncio.TimeoutError:
                    await ws.close(code=WS_CLOSE_POLICY_VIOLATION, message=b"idle")
                    break
                if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                    break
                if msg.type == WSMsgType.ERROR:
                    self.logger.warning("relay: socket error %s", ws.exception())
                    break
                if msg.type != WSMsgType.TEXT:
                    rejected += 1
                    continue
                if len(msg.data) > MAX_RELAY_MESSAGE_BYTES:
                    await ws.close(code=WS_CLOSE_TOO_BIG, message=b"frame too large")
                    break

                try:
                    frame = RelayFrame.parse(msg.data)
                except WorkerTransportError as exc:
                    rejected += 1
                    await ws.send_json({"type": "error", "message": str(exc)})
                    continue

                handled = await self._apply(ws, tenant_id, broadcast_id, frame)
                if handled is None:
                    break
                accepted += int(handled)
                rejected += int(not handled)
        finally:
            self.logger.info(
                "relay for %s closed (accepted=%d rejected=%d)",
                broadcast_id,
                accepted,
                rejected,
            )
        return ws

    async def _apply(
        self,
        ws: web.WebSocketResponse,
        tenant_id: str,
        broadcast_id: str,
        frame: RelayFrame,
    ) -> Optional[bool]:
        """Re-validate one frame on the owner and apply it.

        Returns:
            ``True`` when applied, ``False`` when rejected, ``None`` when the
            connection was closed (fenced sender).
        """
        from parrot.integrations.liveavatar.broadcast.floor import (
            validate_audio_authority,
        )

        producer_epoch = self._service.owner_epoch(tenant_id, broadcast_id)
        session = self._service.voice_session(tenant_id, broadcast_id)
        if producer_epoch is None or session is None:
            await ws.close(code=WS_CLOSE_POLICY_VIOLATION, message=b"not the producer")
            return None
        if frame.owner_epoch != producer_epoch:
            # The sender is talking to a producer that no longer exists.
            await ws.close(code=WS_CLOSE_POLICY_VIOLATION, message=b"stale_owner_epoch")
            return None

        if frame.kind == "switch_speaker":
            return await self._apply_barrier(ws, tenant_id, broadcast_id, frame)

        descriptor = await self._service.get_descriptor(tenant_id, broadcast_id)
        lease = await self._service.get_lease(tenant_id, broadcast_id, frame.lease_id)
        try:
            # Second, authoritative check: ingress already validated, but a
            # revoke may have landed in between and the producer is the last
            # place that can stop it.
            validate_audio_authority(
                descriptor,
                lease,
                floor_epoch=frame.floor_epoch,
                socket_id=lease.speaker_socket_id if lease else "relay",
            )
        except BroadcastError as exc:
            await ws.send_json(
                {
                    "type": "error",
                    "code": exc.reason.value if exc.reason else "forbidden",
                    "message": str(exc),
                }
            )
            return False

        if frame.kind == "start_turn":
            # Install THIS speaker's context before the turn runs. Without it
            # the session keeps whatever context a previous (possibly local)
            # speaker left behind, and the relayed turn would execute under
            # that user's identity and tool permissions — spec §2 forbids
            # reusing another participant's privileges, and failing closed is
            # the only safe default.
            begin = getattr(session, "begin_speaker_turn", None)
            if begin is None:
                await ws.send_json(
                    {
                        "type": "error",
                        "code": BroadcastReason.FLOOR_NOT_GRANTED.value,
                        "message": "producer cannot establish a speaker context",
                    }
                )
                return False
            begin(frame.lease_id, lease.principal, frame.floor_epoch)
            await session.start_turn()
        elif frame.kind == "end_turn":
            await session.end_turn()
        elif frame.kind == "release":
            session.end_speaker_turn()
        else:
            await session.push_audio(frame.pcm)
        return True

    async def _apply_barrier(
        self, ws: web.WebSocketResponse, tenant_id: str, broadcast_id: str, frame: "RelayFrame"
    ) -> bool:
        """Run the producer half of a handoff requested by another worker.

        A grant issued on a worker that does not own the producer used to skip
        the barrier entirely: the registry went ``switching`` and was committed
        without the producer ever fencing its output, so the outgoing speaker's
        in-flight audio could still surface under the incoming one. Relaying
        the barrier makes a cross-worker handoff obey the same ordering as a
        local one.

        Args:
            ws: The peer worker's socket.
            tenant_id: Tenant scope.
            broadcast_id: Broadcast concerned.
            frame: The ``switch_speaker`` frame; ``lease_id`` is the target.

        Returns:
            ``True`` when the producer acknowledged.
        """
        session = self._service.media_session(tenant_id, broadcast_id)
        if session is None:
            await ws.send_json(
                {
                    "type": "error",
                    "code": BroadcastReason.OWNER_LOST.value,
                    "message": "no local producer to fence",
                }
            )
            return False
        try:
            await session.switch_speaker(frame.lease_id, frame.floor_epoch)
        except Exception as exc:  # noqa: BLE001 — report, never force through
            self.logger.warning(
                "broadcast %s: relayed handoff barrier failed at epoch %d: %s",
                broadcast_id,
                frame.floor_epoch,
                type(exc).__name__,
            )
            await ws.send_json(
                {
                    "type": "error",
                    "code": BroadcastReason.STALE_FLOOR_EPOCH.value,
                    "message": "producer did not acknowledge the handoff",
                }
            )
            return False
        await ws.send_json({"type": "ack", "floor_epoch": frame.floor_epoch})
        return True


async def relay_switch_speaker(
    url: str,
    *,
    tenant_id: str,
    broadcast_id: str,
    owner_epoch: int,
    target_lease_id: str,
    floor_epoch: int,
    token: Optional[str] = None,
    session_factory: Optional[Any] = None,
    timeout_s: float = 3.0,
) -> None:
    """Ask a remote producer to fence its output for a handoff.

    Args:
        url: The owner's relay URL, resolved from
            :class:`WorkerAddressRegistry` — never from a client.
        tenant_id: Tenant scope.
        broadcast_id: Broadcast concerned.
        owner_epoch: Ownership generation, restated so a fenced owner refuses.
        target_lease_id: The incoming speaker.
        floor_epoch: The epoch being switched to.
        token: Shared service token.
        session_factory: Override for ``aiohttp.ClientSession`` (tests).
        timeout_s: Deadline for the whole exchange.

    Raises:
        WorkerTransportError: If the producer does not acknowledge in time.
            The caller aborts the floor, leaving it idle and retryable, rather
            than committing a handoff the producer never applied.
    """
    WorkerAddressRegistry.validate_url(url)
    resolved = resolve_worker_token(token)
    factory = session_factory or aiohttp.ClientSession
    frame = RelayFrame(
        kind="switch_speaker",
        owner_epoch=owner_epoch,
        lease_id=target_lease_id,
        floor_epoch=floor_epoch,
    )
    target = f"{url.rstrip('/')}{RELAY_ROUTE}" f"?tenant_id={tenant_id}&broadcast_id={broadcast_id}"
    headers = {WORKER_TOKEN_HEADER: resolved} if resolved else {}
    try:
        async with factory() as session:
            async with session.ws_connect(target, headers=headers, timeout=timeout_s) as ws:
                await ws.send_str(frame.to_wire())
                msg = await asyncio.wait_for(ws.receive(), timeout=timeout_s)
                payload = json.loads(msg.data) if isinstance(msg.data, str) else {}
                if payload.get("type") != "ack":
                    raise WorkerTransportError(message=f"producer refused the handoff: {payload.get('code')}")
    except WorkerTransportError:
        raise
    except Exception as exc:  # noqa: BLE001 — any failure aborts the handoff
        raise WorkerTransportError(
            message=f"could not reach the producer to fence the handoff: {type(exc).__name__}"
        ) from exc


class SpeakerInput:
    """What the WebSocket route uses to feed the producer, wherever it lives."""

    async def start_turn(self) -> None:
        """Begin an input turn."""
        raise NotImplementedError

    async def push_audio(self, pcm: bytes) -> None:
        """Forward one microphone PCM block."""
        raise NotImplementedError

    async def end_turn(self) -> None:
        """End the input turn."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release the input.  Idempotent, never raises."""
        raise NotImplementedError


class LocalSpeakerInput(SpeakerInput):
    """Producer is on this worker: talk to the voice session directly.

    Args:
        session: The local :class:`BroadcastVoiceSession`.
        lease_id: The speaking lease.
        principal: The speaker's scoped principal.
        floor_epoch: Floor epoch this input was authorised under.
    """

    def __init__(self, session: Any, lease_id: str, principal: Any, floor_epoch: int) -> None:
        self._session = session
        self._lease_id = lease_id
        self._principal = principal
        self._floor_epoch = floor_epoch
        self._begun = False
        self._generation: Optional[int] = None

    async def start_turn(self) -> None:
        if not self._begun:
            self._generation = self._session.begin_speaker_turn(self._lease_id, self._principal, self._floor_epoch)
            self._begun = True
        await self._session.start_turn()

    async def push_audio(self, pcm: bytes) -> None:
        await self._session.push_audio(pcm)

    async def end_turn(self) -> None:
        await self._session.end_turn()

    async def aclose(self) -> None:
        """Release this input, but only if it still owns the speaker context.

        A departing socket must not clear a context that has since been handed
        to somebody else: after an A→B handoff, closing A's socket would
        otherwise leave B unable to speak.  The generation captured at
        ``start_turn`` identifies the turn this input started.
        """
        if not self._begun:
            return
        current = getattr(self._session, "turn_generation", None)
        if current is not None and current != self._generation:
            return  # The floor moved on; the context belongs to someone else.
        with contextlib.suppress(Exception):
            self._session.end_speaker_turn()


class RemoteSpeakerInput(SpeakerInput):
    """Producer is on another worker: relay over the authenticated transport.

    The queue is bounded on purpose.  If the hop cannot keep up, dropping the
    newest frames and logging is correct — buffering microphone audio
    indefinitely would make the agent answer a question the speaker asked
    seconds ago.

    Args:
        url: The owner's relay URL, resolved from
            :class:`WorkerAddressRegistry` — never from a client.
        tenant_id: Tenant scope.
        broadcast_id: Broadcast concerned.
        owner_epoch: Ownership generation, restated on every frame.
        lease_id: The speaking lease.
        floor_epoch: Floor epoch this input was authorised under.
        token: Shared service token.
        session_factory: Override for ``aiohttp.ClientSession`` (tests).
    """

    def __init__(
        self,
        url: str,
        *,
        tenant_id: str,
        broadcast_id: str,
        owner_epoch: int,
        lease_id: str,
        floor_epoch: int,
        token: Optional[str] = None,
        session_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        WorkerAddressRegistry.validate_url(url)
        if not _is_loopback(url) and not url.startswith("wss://"):
            raise WorkerTransportError(message="non-loopback worker relay must use wss://")
        self._url = url
        self._tenant_id = tenant_id
        self._broadcast_id = broadcast_id
        self._owner_epoch = owner_epoch
        self._lease_id = lease_id
        self._floor_epoch = floor_epoch
        self._token = resolve_worker_token(token)
        self._session_factory = session_factory or aiohttp.ClientSession
        self._client: Any = None
        self._ws: Any = None
        self._closed = False
        self.dropped_frames = 0
        self.logger = logging.getLogger(__name__)

    async def _connect(self) -> None:
        """Open the relay connection lazily.

        Raises:
            WorkerTransportError: If no shared token is configured.
        """
        if self._ws is not None:
            return
        if not self._token:
            raise WorkerTransportError(message=f"{WORKER_TOKEN_ENV} is required to relay speaker input")
        self._client = self._session_factory()
        self._ws = await self._client.ws_connect(
            f"{self._url}{RELAY_ROUTE}" f"?tenant_id={self._tenant_id}&broadcast_id={self._broadcast_id}",
            headers={WORKER_TOKEN_HEADER: self._token},
            max_msg_size=MAX_RELAY_MESSAGE_BYTES,
        )

    async def _send(self, frame: RelayFrame) -> None:
        """Send one frame, translating a fenced close into an error.

        Raises:
            WorkerTransportError: When the owner fenced this sender.
        """
        if self._closed:
            raise WorkerTransportError(message="relay is closed")
        await self._connect()
        if self._ws.closed:
            raise WorkerTransportError(
                BroadcastReason.OWNER_LOST,
                message="relay closed by the owner (stale owner epoch)",
            )
        await self._ws.send_str(frame.to_wire())

    def _frame(self, kind: str, pcm: bytes = b"", seq: int = 0) -> RelayFrame:
        """Build a frame carrying the full fencing tuple."""
        return RelayFrame(
            kind=kind,
            owner_epoch=self._owner_epoch,
            lease_id=self._lease_id,
            floor_epoch=self._floor_epoch,
            seq=seq,
            pcm=pcm,
        )

    async def start_turn(self) -> None:
        await self._send(self._frame("start_turn"))

    async def push_audio(self, pcm: bytes) -> None:
        if len(pcm) > MAX_RELAY_MESSAGE_BYTES // 2:
            self.dropped_frames += 1
            self.logger.warning("relay: dropping oversized %d-byte block", len(pcm))
            return
        await self._send(self._frame("audio", pcm=pcm))

    async def end_turn(self) -> None:
        await self._send(self._frame("end_turn"))

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.close()
            self._client = None


__all__ = [
    "MAX_RELAY_MESSAGE_BYTES",
    "RELAY_IDLE_TIMEOUT_S",
    "RELAY_QUEUE_MAX_FRAMES",
    "RELAY_ROUTE",
    "WORKER_TOKEN_ENV",
    "WORKER_TOKEN_HEADER",
    "WS_CLOSE_POLICY_VIOLATION",
    "WS_CLOSE_TOO_BIG",
    "LocalSpeakerInput",
    "RelayFrame",
    "RemoteSpeakerInput",
    "SpeakerInput",
    "WorkerAddressRegistry",
    "WorkerRelayServer",
    "WorkerTransportError",
    "resolve_worker_token",
]
