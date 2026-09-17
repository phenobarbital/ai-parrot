"""Omni async Interactions clip adapter (FEAT-564, spec module M4).

Calls the public ``sdk.aio.interactions.create(...)`` surface directly for
exactly one reel scene — never the synchronous, streaming
``client.interactions.create()`` pattern ``GoogleGenAIClient._deep_research_ask``
uses (``client.py:5153``), which this adapter must not copy (Implementation
Notes: "Do not copy synchronous deep research").

Evidence gate (spec §8 Q3, "Omni URI download authentication is unverified"):
the response SHAPE below (``Interaction.status``/``.errors``/``.output_video``
-> ``VideoContent.data``/``.uri``/``.mime_type``, ``InteractionStatus``'s legal
values) is verified via OFFLINE SDK source inspection of the installed
``google-genai`` package only — no live call was made, and the actual Omni
video URI host/authentication contract remains unverified. See this task's
Completion Note.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple

from .clip import GeneratedReelClip
from .download import ProviderMediaDownloader
from .errors import (
    DownloadFailure,
    FilteredOutputError,
    MediaValidationFailure,
    OperationFailure,
    ReelError,
    ReelErrorCode,
    ReelValidationError,
    classify_provider_error,
)
from .profiles import VideoModelProfile

if TYPE_CHECKING:
    from ..client import GoogleGenAIClient

MOVIEPY_AVAILABLE = importlib.util.find_spec("moviepy") is not None

# Verified (google-genai 2.23.0, source inspection of
# google.genai._gaos.types.interactions.interaction.InteractionStatus — evidence
# only, never a proposed import path per the Codebase Contract).
_TERMINAL_FAILURE_STATUSES = frozenset({"failed", "cancelled", "incomplete", "budget_exceeded"})
_IN_PROGRESS_STATUSES = frozenset({"in_progress", "requires_action", "queued"})

# Verified: google.genai._gaos.types.interactions.videocontent.VideoContentMimeType.
_EXTENSION_BY_MIME = {
    "video/mp4": ".mp4",
    "video/mpeg": ".mpeg",
    "video/mpg": ".mpg",
    "video/mov": ".mov",
    "video/avi": ".avi",
    "video/x-flv": ".flv",
    "video/webm": ".webm",
    "video/wmv": ".wmv",
    "video/3gpp": ".3gp",
}
_DEFAULT_EXTENSION = ".mp4"

# Omni's actual output frame rate is unverified (spec §8 Q3 territory); this
# is a documented assumption used ONLY for the one-frame insufficient-duration
# tolerance, matching Veo's typical output — see this task's Completion Note.
_ASSUMED_FPS_FOR_TOLERANCE = 24.0

_DEFAULT_MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024


class OmniClipAdapter:
    """Generates one clip through the Gemini Omni Interactions API for a reel scene.

    Args:
        owner: The :class:`GoogleGenAIClient` that owns provider client
            lifecycle (``get_client``/``close``).
        downloader: A :class:`ProviderMediaDownloader` used when the provider
            delivers output as a URI rather than inline data.
        max_download_bytes: Byte bound applied to a URI-delivered download.
    """

    def __init__(
        self,
        owner: "GoogleGenAIClient",
        downloader: ProviderMediaDownloader,
        *,
        max_download_bytes: int = _DEFAULT_MAX_DOWNLOAD_BYTES,
    ) -> None:
        self._owner = owner
        self._downloader = downloader
        self._max_download_bytes = max_download_bytes

    async def generate(
        self,
        *,
        profile: VideoModelProfile,
        prompt: str,
        output_directory: Path,
        aspect_ratio: str,
        resolution: str,  # noqa: ARG002 - not applicable to Omni (profile.resolutions == []); kept for signature parity with VeoClipAdapter
        target_duration_seconds: float,
        starting_frame: Optional[Path],
        deadline: float,
    ) -> GeneratedReelClip:
        """Generates one Omni clip for a scene.

        Args:
            profile: The resolved, enabled Omni profile to generate with.
            prompt: The scene's video prompt.
            output_directory: Directory the materialized clip is written into.
            aspect_ratio: Requested aspect ratio, forwarded as-is to
                ``response_format.aspect_ratio``.
            resolution: Not applicable to Omni; accepted only for signature
                parity with :class:`VeoClipAdapter`.
            target_duration_seconds: The scene's edit target duration, used
                only for the post-measurement insufficient-duration check —
                never sent to the provider (Omni has no verified duration
                enum; see spec §3 M4 "Does NOT invent a duration enum").
            starting_frame: Must be ``None`` — Omni has no verified
                starting-frame/image-to-video capability (profile
                ``supports_starting_frame=False``).
            deadline: Absolute ``time.monotonic()``-comparable deadline.

        Returns:
            The generated, measured, locally-saved clip.

        Raises:
            ReelError: Unsupported starting frame, submission failure,
                terminal interaction status, empty/invalid output, download
                or media-validation failure — creation failures are never
                retried (ambiguous outcome).
            asyncio.CancelledError: Propagated unchanged.
        """
        if starting_frame is not None:
            raise ReelValidationError(
                ReelErrorCode.UNSUPPORTED_OPTION,
                f"Model {profile.model_id!r} does not support a starting-frame image.",
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ReelError(
                ReelErrorCode.TIMEOUT,
                "Deadline already passed before Omni submission; not submitted.",
                stage="omni_submit",
                retryable=True,
            )

        # response_format.duration is intentionally omitted (spec §3 M4): no
        # Omni duration value has been verified, so none is sent — the
        # provider's own default applies and the OUTPUT is measured instead.
        response_format = {"type": "video", "aspect_ratio": aspect_ratio}

        # "Directly created clients require explicit ownership" (client.py's
        # get_client docstring) — owned and closed on every exit.
        client = await self._owner.get_client(model=profile.model_id)
        try:
            try:
                interaction = await client.aio.interactions.create(
                    agent=profile.model_id,
                    input=prompt,
                    background=False,
                    store=False,
                    stream=False,
                    response_format=response_format,
                    timeout=remaining,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Ambiguous creation failure: never retried (Scope: "do not
                # retry ambiguous creation failures").
                raise classify_provider_error(exc, stage="omni_submit") from exc

            interaction_id = getattr(interaction, "id", None)
            local_path = await self._normalize_and_materialize(
                interaction, output_directory, deadline=deadline, operation_id=interaction_id
            )
        finally:
            await client.aio.aclose()

        measured_duration, has_audio = await self._measure(local_path)
        self._check_sufficient_duration(target_duration_seconds, measured_duration, operation_id=interaction_id)

        return GeneratedReelClip(
            local_path=local_path,
            model=profile.model_id,
            backend="omni",
            submitted_duration_seconds=None,  # Omni: provider default, never submitted
            measured_duration_seconds=measured_duration,
            has_audio=has_audio,
            provider_operation_id=interaction_id,
        )

    async def _normalize_and_materialize(
        self, interaction, output_directory: Path, *, deadline: float, operation_id: Optional[str]
    ) -> Path:
        """Normalizes a completed interaction's status/output, then materializes the clip locally."""
        status = getattr(interaction, "status", None)
        status_value = getattr(status, "value", status)  # tolerate a str or an enum member

        if status_value in _TERMINAL_FAILURE_STATUSES:
            errors = getattr(interaction, "errors", None) or []
            message = "; ".join(getattr(e, "message", None) or str(e) for e in errors) or f"status={status_value}"
            raise classify_provider_error(
                OperationFailure(message, code=status_value, operation_id=operation_id), stage="omni_result"
            )
        if status_value in _IN_PROGRESS_STATUSES:
            # Should not occur with background=False/stream=False, but never assumed.
            raise classify_provider_error(
                OperationFailure(
                    f"Interaction returned status={status_value!r} despite background=False/stream=False.",
                    code=status_value,
                    operation_id=operation_id,
                ),
                stage="omni_result",
            )

        output_video = getattr(interaction, "output_video", None)
        if output_video is None:
            raise classify_provider_error(
                FilteredOutputError("No output_video in the Omni interaction response.", operation_id=operation_id),
                stage="omni_result",
            )

        data = getattr(output_video, "data", None)
        uri = getattr(output_video, "uri", None)
        mime_type = getattr(output_video, "mime_type", None)
        extension = _EXTENSION_BY_MIME.get(mime_type, _DEFAULT_EXTENSION)
        local_path = output_directory / f"omni_{uuid.uuid4().hex[:8]}{extension}"

        # `is not None` (not truthiness): an explicitly-empty `data=""` field
        # means the provider DID send inline delivery, just with zero bytes —
        # that must reach _decode_inline's own "decoded to zero bytes" check,
        # not be misread as "neither data nor uri present" (a provider
        # omission, which is a different failure mode).
        if data is not None:
            return await self._decode_inline(data, output_directory, local_path)
        if uri is not None:
            try:
                return await self._downloader.fetch(
                    uri, local_path, max_bytes=self._max_download_bytes, deadline=deadline
                )
            except DownloadFailure as exc:
                raise classify_provider_error(exc, stage="omni_download") from exc

        raise classify_provider_error(
            FilteredOutputError("Omni output_video has neither inline data nor a URI.", operation_id=operation_id),
            stage="omni_result",
        )

    async def _decode_inline(self, data: str, output_directory: Path, local_path: Path) -> Path:
        """Decodes base64 inline video data and writes it locally.

        Raises:
            ReelError: ``media_invalid`` for malformed base64 or an empty
                decoded payload.
        """
        try:
            raw_bytes = base64.b64decode(data, validate=True)
        except Exception as exc:
            raise classify_provider_error(
                MediaValidationFailure(f"Omni inline video data is not valid base64: {exc}"), stage="omni_decode"
            ) from exc
        if not raw_bytes:
            raise classify_provider_error(
                MediaValidationFailure("Omni inline video data decoded to zero bytes."), stage="omni_decode"
            )
        await asyncio.get_running_loop().run_in_executor(
            None, self._write_bytes, output_directory, local_path, raw_bytes
        )
        return local_path

    @staticmethod
    def _write_bytes(output_directory: Path, local_path: Path, data: bytes) -> None:
        """Creates the output directory and writes decoded bytes (blocking I/O, run in an executor)."""
        output_directory.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)

    async def _measure(self, path: Path) -> Tuple[float, bool]:
        """Measures the materialized clip's real duration and audio presence.

        Never trusts the request/profile alone (even though Omni's profile
        declares ``native_audio="always"``) — this is the "preserve native
        audio metadata" requirement, verified rather than assumed.
        """
        if not MOVIEPY_AVAILABLE:
            raise classify_provider_error(
                MediaValidationFailure("moviepy is not available to measure/validate the generated clip."),
                stage="omni_media_validate",
            )
        from moviepy import VideoFileClip  # lazy: mirrors reel/veo.py's own guard

        def _do() -> Tuple[float, bool]:
            try:
                clip = VideoFileClip(str(path))
            except Exception as exc:
                raise MediaValidationFailure(f"Generated video is not readable: {path}") from exc
            try:
                return clip.duration, clip.audio is not None
            finally:
                clip.close()

        try:
            return await asyncio.get_running_loop().run_in_executor(None, _do)
        except MediaValidationFailure as exc:
            raise classify_provider_error(exc, stage="omni_media_validate") from exc

    @staticmethod
    def _check_sufficient_duration(target: float, measured: float, *, operation_id: Optional[str]) -> None:
        """Fails ``insufficient_duration`` when measured output is short by more than one frame.

        Raises:
            ReelError: ``insufficient_duration`` — never loops, stretches or
                regenerates a short clip.
        """
        tolerance = 1.0 / _ASSUMED_FPS_FOR_TOLERANCE
        if measured < target - tolerance:
            raise ReelError(
                ReelErrorCode.INSUFFICIENT_DURATION,
                f"Measured Omni output duration {measured}s is shorter than target {target}s by more than "
                f"one frame ({tolerance}s tolerance).",
                stage="omni_media_validate",
                retryable=False,
                operation_id=operation_id,
            )
