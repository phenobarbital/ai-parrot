"""Music policy, isolated Lyria session and verified PCM->WAV encoding (FEAT-564, spec module M5).

Applies ``VideoReelRequest.music_policy``/``audio_mode``, runs its OWN
connect/receive loop against an isolated, owned SDK client (never
``generate_music_stream``'s shared stream — this service needs each
chunk's ``mime_type`` to verify the PCM sample rate instead of guessing it),
bounds connection/receive time and bytes, joins the receiver task on
cancellation, and writes a verified-metadata WAV file.

Evidence gate (spec §8 Q6, "Lyria API version and PCM metadata are
unverified"): see this task's Completion Note for the full resolution —
summary: the sample RATE is read from each ``AudioChunk.mime_type`` at
runtime (a real wire field, verified via SDK source inspection) rather than
hardcoded from either of the two conflicting public sources (F011: repo docs
say 48kHz, Google's public guide's player example uses 44.1kHz). Channel
count (stereo) and sample width (16-bit) are NOT wire-verified — they are
documented conventions, flagged distinctly from the wire-verified rate.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
import uuid
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional, Tuple

from pydantic import BaseModel

from parrot.models.google import VideoReelRequest

from .errors import ReelError, ReelErrorCode

# Lazy SDK guard: see ``client.py`` for the rationale.
try:
    from google.genai import types
except ImportError:  # pragma: no cover - exercised when extra is missing
    types = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from ..client import GoogleGenAIClient

# Verified via source inspection of the installed google-genai package
# (google.genai.types.AudioChunk.mime_type — a real wire field, not
# invented) — Google's PCM mime convention is "audio/pcm;rate=<hz>".
_PCM_RATE_RE = re.compile(r"rate=(\d+)")

# NOT wire-verified (no mime_type sub-field carries these) — documented
# conventions: generate_music_stream's own docstring says Lyria audio is
# stereo, and 16-bit PCM is the universal convention across this SDK
# family (matches AbstractClient._save_audio_file's speech encoder).
_MUSIC_CHANNELS = 2
_MUSIC_SAMPLE_WIDTH = 2

_DEFAULT_MAX_BYTES = 20 * 1024 * 1024
_DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
_RECEIVE_POLL_TIMEOUT_SECONDS = 5.0


class MusicOutcome(BaseModel):
    """Structured outcome of one music-generation attempt.

    Args:
        status: ``"off"`` (policy off, no connection), ``"succeeded"``,
            ``"unavailable"`` (connection/handshake failure), ``"timeout"``,
            ``"failed"`` (any other error), or ``"skipped"``
            (``audio_mode`` is ``native``/``muted``).
        local_path: The written WAV file, only when ``status == "succeeded"``.
        warning: A human-readable warning for any non-``"succeeded"``,
            non-``"off"``, non-``"skipped"`` status.
    """

    status: Literal["off", "succeeded", "unavailable", "timeout", "failed", "skipped"]
    local_path: Optional[Path] = None
    warning: Optional[str] = None


class _LyriaUnavailable(Exception):
    """Internal signal: connection/handshake/protocol failure (maps to status='unavailable')."""


class _LyriaTimeout(Exception):
    """Internal signal: the connect or receive budget elapsed (maps to status='timeout')."""


class _TooManyBytes(Exception):
    """Internal signal: the stream exceeded the configured byte bound."""


class ReelMusicService:
    """Generates one background-music WAV for a reel, honoring ``music_policy``.

    Args:
        owner: The :class:`GoogleGenAIClient` that owns provider client
            lifecycle (``get_client``/``close``). This service builds and
            closes its OWN client, isolated from the director/video clients.
        api_version: The API version this service's client is built with —
            configurable and tested, never the shared hardcoded default.
        connect_timeout_seconds: Bound on the initial connect handshake.
        max_bytes: Bound on total received PCM bytes before aborting.
    """

    def __init__(
        self,
        owner: "GoogleGenAIClient",
        *,
        api_version: str,
        connect_timeout_seconds: float = _DEFAULT_CONNECT_TIMEOUT_SECONDS,
        max_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        self._owner = owner
        self._api_version = api_version
        self._connect_timeout_seconds = connect_timeout_seconds
        self._max_bytes = max_bytes

    async def generate(
        self,
        request: VideoReelRequest,
        *,
        duration_seconds: float,
        output_directory: Path,
        deadline: float,
    ) -> MusicOutcome:
        """Generates background music for a reel, per its audio_mode/music_policy.

        ``audio_mode in {"native", "muted"}`` skips Lyria entirely (no
        connection). Otherwise: ``music_policy == "off"`` makes no
        connection either. ``"optional"`` (default) returns a structured
        failure outcome with a warning on any error. ``"required"`` raises
        a :class:`ReelError` on any error instead.

        Args:
            request: The reel request (``music_policy``, ``audio_mode``,
                ``music_prompt``/``music_genre``/``music_mood``).
            duration_seconds: The final assembled reel duration to target.
            output_directory: Directory the WAV file is written into.
            deadline: Absolute ``time.monotonic()``-comparable deadline.

        Returns:
            A :class:`MusicOutcome`. Never ``None``.

        Raises:
            ReelError: Only when ``music_policy == "required"`` and
                generation failed.
            asyncio.CancelledError: Propagated unchanged.
        """
        if request.audio_mode in ("native", "muted"):
            return MusicOutcome(status="skipped")
        if request.music_policy == "off":
            return MusicOutcome(status="off")

        prompt = request.music_prompt or f"Background music for {request.prompt}"
        if request.music_genre:
            prompt += f", Genre: {request.music_genre}"
        if request.music_mood:
            prompt += f", Mood: {request.music_mood}"

        try:
            local_path = await self._run_session(
                prompt, duration_seconds=duration_seconds, output_directory=output_directory, deadline=deadline
            )
        except asyncio.CancelledError:
            raise
        except _LyriaTimeout as exc:
            outcome = MusicOutcome(status="timeout", warning=str(exc))
        except _LyriaUnavailable as exc:
            outcome = MusicOutcome(status="unavailable", warning=str(exc))
        except Exception as exc:  # noqa: BLE001 - normalized into a structured outcome or raised below
            outcome = MusicOutcome(status="failed", warning=str(exc))
        else:
            return MusicOutcome(status="succeeded", local_path=local_path)

        if request.music_policy == "required":
            raise ReelError(
                ReelErrorCode.PROVIDER_FAILURE,
                f"music_policy='required' but music generation failed: {outcome.warning}",
                stage="music_generate",
                retryable=False,
            )
        return outcome

    async def _run_session(
        self, prompt: str, *, duration_seconds: float, output_directory: Path, deadline: float
    ) -> Path:
        """Runs one isolated Lyria session end to end and writes the WAV file.

        Raises:
            _LyriaUnavailable: Connection/handshake/protocol/empty-stream failure.
            _LyriaTimeout: The connect or receive budget elapsed.
        """
        if types is None:
            raise _LyriaUnavailable("google-genai is not installed.")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _LyriaTimeout("Deadline already passed before the Lyria connection.")

        # Isolated, owned client — never shared with the director/video
        # clients (spec §2 item 6). "Directly created clients require
        # explicit ownership" (client.py's get_client docstring).
        client = await self._owner.get_client(http_options={"api_version": self._api_version})
        try:
            connect_cm = client.aio.live.music.connect(model="models/lyria-realtime-exp")
            try:
                session = await asyncio.wait_for(
                    connect_cm.__aenter__(), timeout=min(self._connect_timeout_seconds, remaining)
                )
            except asyncio.TimeoutError as exc:
                raise _LyriaTimeout(
                    f"Lyria connection handshake timed out after {self._connect_timeout_seconds}s."
                ) from exc
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise _LyriaUnavailable(f"Lyria connection failed: {exc}") from exc

            try:
                pcm_bytes, sample_rate = await self._receive_stream(
                    session, prompt=prompt, duration_seconds=duration_seconds, deadline=deadline
                )
            finally:
                with contextlib.suppress(Exception):
                    await connect_cm.__aexit__(None, None, None)
        finally:
            await client.aio.aclose()

        local_path = output_directory / f"music_{uuid.uuid4().hex[:8]}.wav"
        await asyncio.get_running_loop().run_in_executor(
            None,
            write_pcm_wav,
            pcm_bytes,
            local_path,
            sample_rate,
            _MUSIC_CHANNELS,
            _MUSIC_SAMPLE_WIDTH,
        )
        return local_path.with_suffix(".wav")

    async def _receive_stream(
        self, session, *, prompt: str, duration_seconds: float, deadline: float
    ) -> Tuple[bytes, int]:
        """Sends the prompt/config, plays, and collects PCM bytes + the verified sample rate.

        Raises:
            _LyriaUnavailable: Empty stream, byte-limit exceeded, an
                inconsistent declared rate across chunks, or no chunk ever
                declared a parseable rate (Q6: never guessed).
            _LyriaTimeout: The receive budget elapsed with no terminal signal.
        """
        queue: asyncio.Queue = asyncio.Queue()
        total_bytes = 0

        async def _receive() -> None:
            nonlocal total_bytes
            try:
                async for message in session.receive():
                    content = getattr(message, "server_content", None)
                    chunks = getattr(content, "audio_chunks", None) if content else None
                    if not chunks:
                        continue
                    for chunk in chunks:
                        if not chunk.data:
                            continue
                        total_bytes += len(chunk.data)
                        if total_bytes > self._max_bytes:
                            await queue.put(_TooManyBytes())
                            return
                        await queue.put(chunk)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - forwarded to the consumer via the queue
                await queue.put(exc)
            finally:
                await queue.put(None)

        receiver_task = asyncio.create_task(_receive())
        try:
            prompts = [types.WeightedPrompt(text=prompt, weight=1.0)]
            await session.set_weighted_prompts(prompts=prompts)
            await session.set_music_generation_config(config=types.LiveMusicGenerationConfig())
            await session.play()

            collected = bytearray()
            declared_rate: Optional[int] = None
            start = time.monotonic()
            budget = min(duration_seconds + 5.0, max(0.0, deadline - time.monotonic()))

            while True:
                elapsed = time.monotonic() - start
                if elapsed > budget:
                    break
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=min(_RECEIVE_POLL_TIMEOUT_SECONDS, budget - elapsed)
                    )
                except asyncio.TimeoutError:
                    continue
                if item is None:
                    break
                if isinstance(item, _TooManyBytes):
                    raise _LyriaUnavailable(f"Music stream exceeded the {self._max_bytes}-byte limit.")
                if isinstance(item, Exception):
                    raise _LyriaUnavailable(f"Lyria receive failed: {item}") from item

                rate = _parse_pcm_rate(getattr(item, "mime_type", None))
                if rate is not None:
                    if declared_rate is None:
                        declared_rate = rate
                    elif rate != declared_rate:
                        raise _LyriaUnavailable(
                            f"Lyria stream declared inconsistent PCM rates ({declared_rate} then {rate})."
                        )
                collected.extend(item.data)

            if not collected:
                raise _LyriaUnavailable("Lyria stream produced no audio.")
            if declared_rate is None:
                raise _LyriaUnavailable(
                    "No received chunk declared a parseable PCM sample rate via mime_type; "
                    "refusing to guess between conflicting public sources (spec §8 Q6)."
                )
            return bytes(collected), declared_rate
        finally:
            receiver_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await receiver_task


def _parse_pcm_rate(mime_type: Optional[str]) -> Optional[int]:
    """Extracts the sample rate from a ``"audio/pcm;rate=<hz>"``-shaped mime type.

    Args:
        mime_type: The chunk's declared MIME type, if any.

    Returns:
        The parsed rate in Hz, or ``None`` if absent/unparseable.
    """
    if not mime_type:
        return None
    match = _PCM_RATE_RE.search(mime_type)
    return int(match.group(1)) if match else None


def write_pcm_wav(pcm: bytes, dest: Path, sample_rate: int, channels: int, sample_width: int) -> Path:
    """Writes raw PCM bytes to ``dest`` as a WAV file with exactly the given metadata.

    Never used for speech (``AbstractClient._save_audio_file`` keeps that
    role) — this is music's own writer so speech's mono/24kHz assumptions
    never leak into reel background music.

    Args:
        pcm: Raw PCM audio bytes.
        dest: Destination path; a ``.wav`` suffix is enforced.
        sample_rate: Sample rate in Hz — must be verified, never guessed.
        channels: Number of audio channels.
        sample_width: Bytes per sample (e.g. ``2`` for 16-bit PCM).

    Returns:
        ``dest`` with a ``.wav`` suffix.

    Raises:
        ValueError: Non-positive ``sample_rate``/``channels``/``sample_width``.
    """
    if sample_rate <= 0 or channels <= 0 or sample_width <= 0:
        raise ValueError(f"Invalid WAV metadata: rate={sample_rate}, channels={channels}, width={sample_width}")
    dest = dest.with_suffix(".wav")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), mode="wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return dest
