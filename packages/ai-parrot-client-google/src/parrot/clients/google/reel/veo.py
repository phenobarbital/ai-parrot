"""Bounded Veo clip adapter (FEAT-564, spec module M3).

Wraps ``aio.models.generate_videos`` + ``aio.operations.get`` +
``aio.files.download`` for exactly one reel scene: submits once, polls and
downloads under the caller's original absolute deadline, applies at most
``max_read_retries`` bounded retries to transient poll/download reads only
(never to the generation submission itself), and never resubmits after a
safety block or an ambiguous timeout — the operation id is always preserved
on the raised error for reconciliation.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional, Tuple, TypeVar

from PIL import Image

from .clip import GeneratedReelClip
from .errors import (
    DownloadFailure,
    FilteredOutputError,
    MediaValidationFailure,
    OperationFailure,
    ReelError,
    ReelErrorCode,
    classify_provider_error,
)
from .profiles import VideoModelProfile, select_generation_duration

# Lazy SDK guard: see ``client.py`` for the rationale.
try:
    from google.genai import types
except ImportError:  # pragma: no cover - exercised when extra is missing
    types = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from ..client import GoogleGenAIClient

MOVIEPY_AVAILABLE = importlib.util.find_spec("moviepy") is not None

_T = TypeVar("_T")

# Codes that must never enter the bounded read-retry path (AC07: "Auth and
# validation errors never enter a retry path") even though
# `classify_provider_error`'s own default for an UNCLASSIFIED exception is
# conservatively `retryable=False` too — that default exists to make an
# unrecognized *provider* error safe-by-default, not to blanket-disable the
# existing transient-network retry loop (e.g. a bare `ConnectionError`
# during download SHOULD still be retried). Checking these specific codes
# is deliberately narrower than trusting `ReelError.retryable` wholesale.
_NEVER_RETRY_CODES = frozenset(
    {ReelErrorCode.AUTH_OR_ACCESS, ReelErrorCode.SAFETY_BLOCKED, ReelErrorCode.INVALID_CONFIGURATION}
)


class VeoClipAdapter:
    """Generates one Veo clip for a reel scene.

    Args:
        owner: The :class:`GoogleGenAIClient` that owns provider client
            lifecycle (``get_client``/``close``).
        poll_interval_seconds: Delay between long-running-operation status
            polls.
        max_read_retries: Maximum bounded retries for transient poll/download
            reads — never applied to the initial generation submission.
    """

    def __init__(
        self,
        owner: "GoogleGenAIClient",
        *,
        poll_interval_seconds: float = 10.0,
        max_read_retries: int = 3,
    ) -> None:
        self._owner = owner
        self._poll_interval_seconds = poll_interval_seconds
        self._max_read_retries = max_read_retries

    async def generate(
        self,
        *,
        profile: VideoModelProfile,
        prompt: str,
        output_directory: Path,
        aspect_ratio: str,
        resolution: str,
        target_duration_seconds: float,
        starting_frame: Optional[Path],
        deadline: float,
    ) -> GeneratedReelClip:
        """Generates one Veo clip for a scene.

        Args:
            profile: The resolved, enabled Veo profile to generate with.
            prompt: The scene's video prompt.
            output_directory: Directory the downloaded clip is written into.
            aspect_ratio: Requested aspect ratio (already normalized).
            resolution: Requested resolution.
            target_duration_seconds: The scene's edit target duration.
            starting_frame: Optional starting-frame image path.
            deadline: Absolute ``time.monotonic()``-comparable deadline
                shared across submit/poll/download.

        Returns:
            The generated, measured, locally-saved clip.

        Raises:
            ReelError: Submission, safety-block, filtered-output, ambiguous
                timeout, download or media-validation failure — always with
                the provider operation id attached once one was issued.
            asyncio.CancelledError: Propagated unchanged.
        """
        if types is None:
            raise ReelError(
                ReelErrorCode.PROVIDER_FAILURE, "google-genai is not installed.", stage="veo_submit", retryable=False
            )

        if starting_frame is not None:
            try:
                self._validate_starting_frame(starting_frame)
            except MediaValidationFailure as exc:
                raise classify_provider_error(exc, stage="veo_starting_frame_validate") from exc

        is_image_to_video = starting_frame is not None
        duration = select_generation_duration(profile, target_duration_seconds, resolution, is_image_to_video)

        config_kwargs: dict = {
            "aspect_ratio": aspect_ratio,
            "person_generation": self._resolve_person_generation(profile, is_image_to_video),
        }
        if duration is not None:
            config_kwargs["duration_seconds"] = duration
        if resolution:
            config_kwargs["resolution"] = resolution
        config = types.GenerateVideosConfig(**config_kwargs)

        gen_kwargs: dict = {"model": profile.model_id, "prompt": prompt, "config": config}
        if starting_frame is not None:
            gen_kwargs["image"] = self._load_starting_frame(starting_frame)

        # "Directly created clients require explicit ownership" (verified:
        # client.py's get_client docstring) — this adapter owns and closes
        # the async surface (client.aio.aclose(), NOT the sync close()) on
        # every exit, success or failure.
        client = await self._owner.get_client(model=profile.model_id)
        try:
            try:
                operation = await client.aio.models.generate_videos(**gen_kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise classify_provider_error(exc, stage="veo_submit") from exc

            operation_id = getattr(operation, "name", None)

            operation = await self._poll(client, operation, deadline=deadline, operation_id=operation_id)

            if getattr(operation, "error", None):
                raise classify_provider_error(
                    OperationFailure(
                        str(operation.error), code=getattr(operation.error, "code", None), operation_id=operation_id
                    ),
                    stage="veo_poll",
                    scene_index=None,
                )

            response = operation.response or operation.result
            generated_videos = getattr(response, "generated_videos", None) if response else None
            if not generated_videos:
                rai_count = getattr(response, "rai_media_filtered_count", None)
                rai_reasons = getattr(response, "rai_media_filtered_reasons", None)
                reason = "SAFETY" if (rai_count or rai_reasons) else None
                raise classify_provider_error(
                    FilteredOutputError(
                        f"No videos returned (rai_count={rai_count}, rai_reasons={rai_reasons}).",
                        reason=reason,
                        operation_id=operation_id,
                    ),
                    stage="veo_result",
                )

            video_bytes = await self._download_with_retries(
                client, generated_videos[0].video, deadline=deadline, operation_id=operation_id
            )
        finally:
            await client.aio.aclose()

        local_path = output_directory / f"veo_{uuid.uuid4().hex[:8]}.mp4"
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, self._write_clip, output_directory, local_path, video_bytes
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A raw OSError (disk full, permission denied, ...) must become
            # a ReelError so the caller's partial_failure_policy="skip" path
            # can catch it — an unclassified exception here bypasses skip
            # entirely and fails the whole job (code-review finding,
            # TASK-3331).
            raise classify_provider_error(exc, stage="veo_write", scene_index=None) from exc

        try:
            measured_duration, has_audio = await self._measure(local_path)
        except MediaValidationFailure as exc:
            raise classify_provider_error(exc, stage="veo_media_validate", scene_index=None) from exc

        return GeneratedReelClip(
            local_path=local_path,
            model=profile.model_id,
            backend="veo",
            submitted_duration_seconds=float(duration) if duration is not None else None,
            measured_duration_seconds=measured_duration,
            has_audio=has_audio,
            provider_operation_id=operation_id,
        )

    async def _poll(self, client, operation, *, deadline: float, operation_id: Optional[str]):
        """Polls an operation to completion, bounded by ``deadline`` and read retries."""
        while not operation.done:
            if time.monotonic() > deadline:
                raise classify_provider_error(
                    OperationFailure(
                        "Ambiguous timeout waiting for the operation to complete; not resubmitted.",
                        code="DEADLINE_EXCEEDED",
                        operation_id=operation_id,
                    ),
                    stage="veo_poll",
                )
            remaining = max(0.0, deadline - time.monotonic())
            await asyncio.sleep(min(self._poll_interval_seconds, remaining) if remaining > 0 else 0)

            async def _read(op=operation) -> object:
                return await client.aio.operations.get(op)

            operation = await self._read_with_retries(_read, stage="veo_poll", operation_id=operation_id)
        return operation

    async def _download_with_retries(self, client, video_ref, *, deadline: float, operation_id: Optional[str]) -> bytes:
        async def _read() -> bytes:
            if time.monotonic() > deadline:
                raise DownloadFailure(f"Download deadline exceeded for operation {operation_id}.")
            return await client.aio.files.download(file=video_ref)

        return await self._read_with_retries(_read, stage="veo_download", operation_id=operation_id)

    async def _read_with_retries(
        self, read: Callable[[], Awaitable[_T]], *, stage: str, operation_id: Optional[str]
    ) -> _T:
        """Runs ``read`` with at most ``max_read_retries`` bounded retries on transient failure.

        Every failure is classified BEFORE deciding whether to retry (not
        only on the final attempt, as before) — an auth/safety/validation
        failure surfacing mid-poll or mid-download is raised immediately,
        never retried like a transient `ConnectionError` (AC07). See
        `_NEVER_RETRY_CODES` for why this checks specific codes rather than
        the classified error's generic `.retryable` flag.
        """
        last_exc: Optional[BaseException] = None
        for attempt in range(self._max_read_retries + 1):
            try:
                return await read()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - normalized below via classify_provider_error
                classified = classify_provider_error(exc, stage=stage)
                classified.operation_id = classified.operation_id or operation_id
                if classified.code in _NEVER_RETRY_CODES:
                    raise classified from exc
                last_exc = exc
                if attempt >= self._max_read_retries:
                    break
                await asyncio.sleep(min(1.0 * (attempt + 1), 5.0))
        assert last_exc is not None  # loop always sets it before breaking on final attempt
        error = classify_provider_error(last_exc, stage=stage)
        error.operation_id = error.operation_id or operation_id
        raise error from last_exc

    @staticmethod
    def _write_clip(output_directory: Path, local_path: Path, video_bytes: bytes) -> None:
        """Creates the output directory and writes the downloaded clip (blocking I/O, run in an executor)."""
        output_directory.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(video_bytes)

    async def _measure(self, path: Path) -> Tuple[float, bool]:
        """Measures the downloaded clip's real duration and audio presence.

        Never trusts the request/config alone — this is the "validate
        generated video readability" step (Scope bullet 3).
        """
        if not MOVIEPY_AVAILABLE:
            raise MediaValidationFailure("moviepy is not available to measure/validate the generated clip.")
        from moviepy import VideoFileClip  # lazy: mirrors generation.py's own guard

        def _do() -> Tuple[float, bool]:
            try:
                clip = VideoFileClip(str(path))
            except Exception as exc:
                raise MediaValidationFailure(f"Generated video is not readable: {path}") from exc
            try:
                return clip.duration, clip.audio is not None
            finally:
                clip.close()

        return await asyncio.get_running_loop().run_in_executor(None, _do)

    @staticmethod
    def _resolve_person_generation(profile: VideoModelProfile, is_image_to_video: bool) -> str:
        """Picks the lowercase person_generation wire value for the modality.

        Image-to-video (a starting frame is supplied) requires
        ``"allow_adult"``; text-to-video requires ``"allow_all"`` — falls
        back to the profile's first legal value if neither is supported by
        this profile, rather than silently sending an unsupported one.
        """
        required = "allow_adult" if is_image_to_video else "allow_all"
        if profile.person_generation_values and required not in profile.person_generation_values:
            return profile.person_generation_values[0]
        return required

    @staticmethod
    def _validate_starting_frame(path: Path) -> None:
        """Validates a starting-frame image is present and readable.

        Raises:
            MediaValidationFailure: Missing file or unreadable/corrupt image.
        """
        if not path.exists():
            raise MediaValidationFailure(f"Starting frame not found: {path}")
        try:
            with Image.open(path) as img:
                img.verify()
        except Exception as exc:
            raise MediaValidationFailure(f"Starting frame is not a readable image: {path}") from exc

    @staticmethod
    def _load_starting_frame(path: Path):
        """Loads a starting-frame image into an SDK ``types.Image`` (JPEG bytes)."""
        with Image.open(path) as img:
            converted = img.convert("RGB") if img.mode in ("RGBA", "P") else img
            buf = io.BytesIO()
            converted.save(buf, format="JPEG")
            return types.Image(image_bytes=buf.getvalue(), mime_type="image/jpeg")
