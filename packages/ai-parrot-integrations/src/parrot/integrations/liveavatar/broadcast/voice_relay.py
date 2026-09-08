"""Broadcast-owned voice session and response relay (FEAT-537 — Module 4).

Implements spec §2 end-to-end step 7: the producer session and its response
task belong to the **broadcast**, not to the first participant's WebSocket.  A
viewer closing their browser must not take the conversation with them.

Three differences from the single-user :class:`_HandlerVoiceSession`:

* **PCM never goes down a participant socket.**  Generated audio is pushed once
  into :class:`BroadcastSession`, which routes it to the avatar or the direct
  publisher in the shared room.  Every browser hears it from LiveKit, so
  echoing base64 PCM per socket would produce a second, unsynchronised audible
  source — exactly the "one audible source" rule spec §2 forbids breaking.
* **No connection-local avatar tee.**  The legacy tee speaks to a per-connection
  ``avatar_session``; a broadcast has exactly one avatar for the whole audience.
* **Turns are attributed to the current speaker.**  ``user_id`` for each turn is
  the *speaker's* principal, never the creator's or the moderator's, while the
  conversation key stays the broadcast's stable ``voice_session_id``.  The
  memory namespace is not an authorization principal (spec §2).

Text, transcription, tool and lifecycle frames are still produced by the very
same :func:`~parrot.voice.handler.build_voice_frames` the single-user path
uses, so the two cannot drift in what a browser receives.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from parrot.integrations.liveavatar.broadcast.errors import BroadcastError
from parrot.integrations.liveavatar.broadcast.models import (
    BroadcastAudioFrame,
    BroadcastReason,
    ParticipantPrincipal,
)
from parrot.voice.session import VoiceSession

#: Frame keys carrying inline PCM.  Stripped from every broadcast wire frame:
#: the audio is already going to the shared room.
_AUDIO_FRAME_KEYS: tuple[str, ...] = ("audio_base64", "audio_format")

FanOut = Callable[[Dict[str, Any]], Awaitable[None]]


async def _noop_fanout(_frame: Dict[str, Any]) -> None:
    """Default sink used before the control-socket layer attaches (TASK-2960)."""
    return None


class BroadcastVoiceSession(VoiceSession):
    """The one voice session a broadcast owns, shared by every speaker.

    Constructed once by the producing worker.  Speakers come and go through
    :meth:`begin_speaker_turn` / :meth:`end_speaker_turn`; the conversation,
    the bot and the avatar do not change with them.

    Args:
        *args: Forwarded to :class:`~parrot.voice.session.VoiceSession`.
        broadcast: The :class:`BroadcastSession` that owns the media sinks.
        **kwargs: Forwarded to :class:`~parrot.voice.session.VoiceSession`.
    """

    def __init__(self, *args: Any, broadcast: Any, **kwargs: Any) -> None:
        kwargs.setdefault("send_fn", _noop_fanout)
        super().__init__(*args, **kwargs)
        self._broadcast = broadcast
        # Read back off the base class so a positionally-passed send_fn works.
        self._fanout: FanOut = self.send_fn

        # Current speaker context.  ``None`` means nobody may speak.
        self._speaker_lease_id: Optional[str] = None
        self._speaker_principal: Optional[ParticipantPrincipal] = None
        self._speaker_floor_epoch: Optional[int] = None
        #: Bumped on every speaker change so a response produced by the
        #: previous speaker's turn can be recognised and suppressed.
        self._turn_generation: int = 0

        self._frame_sequence: int = 0
        self._current_turn_id: Optional[str] = None
        self._dedup_state: Any = None

        #: Observability, asserted by tests.
        self.suppressed_stale_responses: int = 0
        self.pushed_audio_frames: int = 0

        self.logger = logging.getLogger(__name__)

    # ── Fan-out wiring ─────────────────────────────────────────────────

    def set_fanout(self, fanout: FanOut) -> None:
        """Attach the control-socket fan-out (TASK-2960 supplies it).

        Args:
            fanout: Coroutine sending one frame to **every** participant.
        """
        self._fanout = fanout

    async def _send(self, payload: Dict[str, Any]) -> None:
        """Send one frame to every participant.

        Overridden rather than relying on ``send_fn`` so a fan-out attached
        after construction takes effect.
        """
        await self._fanout(payload)

    # ── Speaker context ────────────────────────────────────────────────

    @property
    def speaker_lease_id(self) -> Optional[str]:
        """Lease currently permitted to speak, if any."""
        return self._speaker_lease_id

    @property
    def turn_generation(self) -> int:
        """Monotonic counter bumped on every speaker change."""
        return self._turn_generation

    def begin_speaker_turn(
        self,
        lease_id: str,
        principal: ParticipantPrincipal,
        floor_epoch: int,
    ) -> int:
        """Install the speaker whose microphone audio the next turn will carry.

        The turn runs as **that participant**: their ``user_id`` is what the
        bot resolves tool permissions and context from.  Reusing the creator's
        or moderator's identity for someone else's turn would silently hand
        them another user's privileges (spec §2).

        Args:
            lease_id: The granted lease.
            principal: The speaker's scoped principal.
            floor_epoch: Floor epoch this grant belongs to.

        Returns:
            The new turn generation.
        """
        self._speaker_lease_id = lease_id
        self._speaker_principal = principal
        self._speaker_floor_epoch = floor_epoch
        self._turn_generation += 1
        self._frame_sequence = 0
        # Bind the provider call to THIS speaker.  Guarded so a test double or
        # a non-ask_stream client does not break the handoff.
        setter = getattr(self.client, "set_user_id", None)
        if callable(setter):
            setter(principal.user_id)
        self.logger.info(
            "broadcast voice session: speaker=%s user=%s floor_epoch=%d generation=%d",
            lease_id,
            principal.user_id,
            floor_epoch,
            self._turn_generation,
        )
        return self._turn_generation

    def end_speaker_turn(self) -> None:
        """Clear the speaker context so no further input is attributable."""
        self._speaker_lease_id = None
        self._speaker_principal = None
        self._speaker_floor_epoch = None
        self._turn_generation += 1
        self._frame_sequence = 0
        setter = getattr(self.client, "set_user_id", None)
        if callable(setter):
            setter(None)

    def _require_speaker(self) -> ParticipantPrincipal:
        """Return the current speaker principal, failing closed when absent.

        Returns:
            The speaker's principal.

        Raises:
            BroadcastError: With ``floor_not_granted`` when no speaker context
                has been established.  Raised *before* any provider call, so an
                unattributable turn never reaches the bot at all.
        """
        if self._speaker_principal is None or self._speaker_lease_id is None:
            raise BroadcastError(
                BroadcastReason.FLOOR_NOT_GRANTED,
                message="no speaker context established for this turn",
            )
        return self._speaker_principal

    async def start_turn(self) -> None:
        """Begin an input turn, refusing one that has no established speaker."""
        self._require_speaker()
        await super().start_turn()

    async def push_audio(self, pcm: bytes) -> None:
        """Accept microphone PCM, refusing input with no speaker context."""
        self._require_speaker()
        await super().push_audio(pcm)

    # ── Relay ──────────────────────────────────────────────────────────

    async def _relay(self, resp: Any, turn_no: int) -> None:
        """Fan out non-audio frames and route generated PCM to the broadcast.

        Args:
            resp: One provider response.
            turn_no: The current turn number.
        """
        from parrot.voice.handler import ToolCallDedupState, build_voice_frames

        generation = self._turn_generation
        if self._speaker_lease_id is None:
            # The floor moved (or was released) while this response was in
            # flight.  Suppressing it here is what stops a previous speaker's
            # late tool/display events surfacing under the new speaker.
            self.suppressed_stale_responses += 1
            return

        speaker_lease_id = self._speaker_lease_id
        speaker_user_id = (
            self._speaker_principal.user_id if self._speaker_principal else None
        )
        floor_epoch = self._speaker_floor_epoch or 0

        # Stamp attribution BEFORE frames are built, so transcripts and audit
        # records carry the authenticated speaker for this turn.
        if isinstance(getattr(resp, "metadata", None), dict):
            resp.metadata["broadcast"] = {
                "speaker_lease_id": speaker_lease_id,
                "speaker_user_id": speaker_user_id,
                "floor_epoch": floor_epoch,
            }

        if self._dedup_state is None:
            self._dedup_state = ToolCallDedupState()
        frames: List[Dict[str, Any]] = build_voice_frames(
            resp,
            turn_no,
            stt_only=self.stt_only,
            dedup_state=self._dedup_state,
        )

        for frame in frames:
            await self._send(_strip_audio(frame))

        # A speaker change between building frames and touching the media
        # sinks must not let this turn's audio through.
        if generation != self._turn_generation:
            self.suppressed_stale_responses += 1
            return

        if getattr(resp, "is_interrupted", False):
            await self._broadcast.interrupt(reason="provider_interruption")
            return

        audio = getattr(resp, "audio_data", None)
        if audio:
            await self._push_pcm(
                audio, speaker_lease_id=speaker_lease_id, floor_epoch=floor_epoch,
                turn_id=str(getattr(resp, "turn_id", "") or f"turn-{turn_no}"),
            )

        if getattr(resp, "is_complete", False):
            await self._broadcast.finish_turn(
                str(getattr(resp, "turn_id", "") or f"turn-{turn_no}")
            )

    async def _push_pcm(
        self,
        pcm: bytes,
        *,
        speaker_lease_id: str,
        floor_epoch: int,
        turn_id: str,
    ) -> None:
        """Hand one PCM block to the broadcast's output routing, exactly once.

        Epochs are read from the broadcast at send time rather than cached, so
        a cutover or ownership change that happened mid-turn fences this frame
        instead of it slipping through under a stale epoch.

        Args:
            pcm: Generated 24 kHz mono PCM16.
            speaker_lease_id: Lease whose turn produced it.
            floor_epoch: Floor epoch of that turn.
            turn_id: Producing turn.
        """
        if len(pcm) % 2:
            self.logger.warning(
                "broadcast voice session: dropping %d-byte misaligned PCM block",
                len(pcm),
            )
            return
        frame = BroadcastAudioFrame(
            owner_epoch=self._broadcast.owner_epoch,
            speaker_lease_id=speaker_lease_id,
            floor_epoch=floor_epoch,
            turn_id=turn_id,
            output_epoch=self._broadcast.output_epoch,
            sequence=self._frame_sequence,
            pcm=pcm,
            sample_count=len(pcm) // 2,
        )
        self._frame_sequence += 1
        self.pushed_audio_frames += 1
        await self._broadcast.push_audio(frame)


def _strip_audio(frame: Dict[str, Any]) -> Dict[str, Any]:
    """Remove inline PCM from a wire frame, keeping everything else intact.

    The frame *type* is preserved: browsers still receive ``response_chunk``
    with its text, they just do not receive a second copy of the audio they
    are already hearing from the room.

    Args:
        frame: A frame produced by ``build_voice_frames``.

    Returns:
        The frame without audio payload keys.
    """
    if not any(key in frame for key in _AUDIO_FRAME_KEYS):
        return frame
    stripped = {key: value for key, value in frame.items() if key not in _AUDIO_FRAME_KEYS}
    return stripped


__all__ = ["BroadcastVoiceSession", "FanOut"]
