"""TASK-3324: Veo clip adapter submit/poll/download and wire tests.

Mocks the owner's `get_client()` and its `aio.models.generate_videos` /
`aio.operations.get` / `aio.files.download` surface (transport), while the
REAL `VeoClipAdapter.generate()` logic — config serialization through the
actual `google.genai.types.GenerateVideosConfig`, poll/retry/deadline
handling, error classification — runs end to end.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import errors as genai_errors

from parrot.clients.google.reel.clip import GeneratedReelClip
from parrot.clients.google.reel.errors import ReelError, ReelErrorCode
from parrot.clients.google.reel.profiles import VideoProfileRegistry
from parrot.clients.google.reel.veo import VeoClipAdapter

FAR_DEADLINE = lambda: time.monotonic() + 30.0  # noqa: E731


@pytest.fixture
def profile():
    return VideoProfileRegistry.default().resolve("veo-3.1-generate-preview", "gemini_developer")


def _op(*, done=True, error=None, generated_videos=None, name="operations/op-123"):
    response = SimpleNamespace(
        generated_videos=generated_videos, rai_media_filtered_count=None, rai_media_filtered_reasons=None
    )
    return SimpleNamespace(done=done, error=error, response=response, result=None, name=name)


def _video_ref():
    return SimpleNamespace(video=SimpleNamespace())


def _fake_owner(client):
    owner = MagicMock()
    owner.get_client = AsyncMock(return_value=client)
    return owner


def _fake_client(*, generate_videos, operations_get=None, files_download=None):
    client = MagicMock()
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_videos = generate_videos
    client.aio.operations = MagicMock()
    client.aio.operations.get = operations_get or AsyncMock()
    client.aio.files = MagicMock()
    client.aio.files.download = files_download or AsyncMock(return_value=b"FAKEVIDEOBYTES")
    client.aio.aclose = AsyncMock()
    return client


@pytest.fixture(autouse=True)
def _fake_moviepy():
    """Every test measures a fake clip (duration=6.04s, no audio track) unless overridden."""
    fake_clip = MagicMock()
    fake_clip.duration = 6.04
    fake_clip.audio = None
    fake_clip.close = MagicMock()
    with patch("moviepy.VideoFileClip", return_value=fake_clip) as mocked:
        yield mocked


class TestWireConfigSerialization:
    async def test_text_to_video_uses_lowercase_allow_all_and_resolved_duration(self, profile, tmp_path):
        gen = AsyncMock(return_value=_op(generated_videos=[_video_ref()]))
        client = _fake_client(generate_videos=gen)
        owner = _fake_owner(client)
        adapter = VeoClipAdapter(owner)

        clip = await adapter.generate(
            profile=profile,
            prompt="a cat",
            output_directory=tmp_path,
            aspect_ratio="16:9",
            resolution="720p",
            target_duration_seconds=5.0,
            starting_frame=None,
            deadline=FAR_DEADLINE(),
        )

        gen.assert_awaited_once()
        client.aio.aclose.assert_awaited_once()
        call_kwargs = gen.call_args.kwargs
        config = call_kwargs["config"]
        assert config.person_generation == "allow_all"
        assert config.duration_seconds == 6  # smallest covering duration for a 5s target
        assert "image" not in call_kwargs
        assert clip.submitted_duration_seconds == 6.0
        assert isinstance(clip, GeneratedReelClip)

    async def test_starting_frame_uses_allow_adult_and_attaches_image(self, profile, tmp_path):
        frame = tmp_path / "frame.jpg"
        from PIL import Image

        Image.new("RGB", (4, 4)).save(frame, format="JPEG")

        gen = AsyncMock(return_value=_op(generated_videos=[_video_ref()]))
        client = _fake_client(generate_videos=gen)
        owner = _fake_owner(client)
        adapter = VeoClipAdapter(owner)

        await adapter.generate(
            profile=profile,
            prompt="a cat",
            output_directory=tmp_path,
            aspect_ratio="16:9",
            resolution="720p",
            target_duration_seconds=5.0,
            starting_frame=frame,
            deadline=FAR_DEADLINE(),
        )

        call_kwargs = gen.call_args.kwargs
        assert call_kwargs["config"].person_generation == "allow_adult"
        assert "image" in call_kwargs

    async def test_no_generate_audio_key_set(self, profile, tmp_path):
        gen = AsyncMock(return_value=_op(generated_videos=[_video_ref()]))
        client = _fake_client(generate_videos=gen)
        owner = _fake_owner(client)
        adapter = VeoClipAdapter(owner)

        await adapter.generate(
            profile=profile,
            prompt="a cat",
            output_directory=tmp_path,
            aspect_ratio="16:9",
            resolution="720p",
            target_duration_seconds=5.0,
            starting_frame=None,
            deadline=FAR_DEADLINE(),
        )

        assert gen.call_args.kwargs["config"].generate_audio is None


class TestSafetyAndTimeoutSingleSubmit:
    async def test_immediate_safety_error_single_submit_no_retry(self, profile, tmp_path):
        exc = genai_errors.ClientError(
            400, {"error": {"status": "INVALID_ARGUMENT", "details": [{"reason": "SAFETY"}]}}
        )
        gen = AsyncMock(side_effect=exc)
        client = _fake_client(generate_videos=gen)
        owner = _fake_owner(client)
        adapter = VeoClipAdapter(owner)

        with pytest.raises(ReelError) as exc_info:
            await adapter.generate(
                profile=profile,
                prompt="a cat",
                output_directory=tmp_path,
                aspect_ratio="16:9",
                resolution="720p",
                target_duration_seconds=5.0,
                starting_frame=None,
                deadline=FAR_DEADLINE(),
            )

        assert exc_info.value.code is ReelErrorCode.SAFETY_BLOCKED
        assert exc_info.value.retryable is False
        gen.assert_awaited_once()
        client.aio.aclose.assert_awaited_once()

    async def test_operation_error_normalized_and_keeps_operation_id(self, profile, tmp_path):
        gen = AsyncMock(return_value=_op(error=SimpleNamespace(code=400, message="bad config"), name="operations/xyz"))
        client = _fake_client(generate_videos=gen)
        owner = _fake_owner(client)
        adapter = VeoClipAdapter(owner)

        with pytest.raises(ReelError) as exc_info:
            await adapter.generate(
                profile=profile,
                prompt="a cat",
                output_directory=tmp_path,
                aspect_ratio="16:9",
                resolution="720p",
                target_duration_seconds=5.0,
                starting_frame=None,
                deadline=FAR_DEADLINE(),
            )

        assert exc_info.value.operation_id == "operations/xyz"
        gen.assert_awaited_once()

    async def test_ambiguous_timeout_preserves_operation_id_no_resubmit(self, profile, tmp_path):
        gen = AsyncMock(return_value=_op(done=False, name="operations/timeout-op"))
        client = _fake_client(generate_videos=gen)
        owner = _fake_owner(client)
        adapter = VeoClipAdapter(owner, poll_interval_seconds=0.01)

        with pytest.raises(ReelError) as exc_info:
            await adapter.generate(
                profile=profile,
                prompt="a cat",
                output_directory=tmp_path,
                aspect_ratio="16:9",
                resolution="720p",
                target_duration_seconds=5.0,
                starting_frame=None,
                deadline=time.monotonic() - 1.0,  # already expired
            )

        assert exc_info.value.code is ReelErrorCode.TIMEOUT
        assert exc_info.value.operation_id == "operations/timeout-op"
        gen.assert_awaited_once()


class TestEmptyOutputAndFilteredContent:
    async def test_filtered_output_with_rai_reason_is_safety_blocked(self, profile, tmp_path):
        response = SimpleNamespace(
            generated_videos=None, rai_media_filtered_count=1, rai_media_filtered_reasons=["blocked"]
        )
        op = SimpleNamespace(done=True, error=None, response=response, result=None, name="operations/filtered")
        gen = AsyncMock(return_value=op)
        client = _fake_client(generate_videos=gen)
        owner = _fake_owner(client)
        adapter = VeoClipAdapter(owner)

        with pytest.raises(ReelError) as exc_info:
            await adapter.generate(
                profile=profile,
                prompt="a cat",
                output_directory=tmp_path,
                aspect_ratio="16:9",
                resolution="720p",
                target_duration_seconds=5.0,
                starting_frame=None,
                deadline=FAR_DEADLINE(),
            )

        assert exc_info.value.code is ReelErrorCode.SAFETY_BLOCKED

    async def test_empty_output_without_rai_signal_is_provider_failure(self, profile, tmp_path):
        gen = AsyncMock(return_value=_op(generated_videos=None))
        client = _fake_client(generate_videos=gen)
        owner = _fake_owner(client)
        adapter = VeoClipAdapter(owner)

        with pytest.raises(ReelError) as exc_info:
            await adapter.generate(
                profile=profile,
                prompt="a cat",
                output_directory=tmp_path,
                aspect_ratio="16:9",
                resolution="720p",
                target_duration_seconds=5.0,
                starting_frame=None,
                deadline=FAR_DEADLINE(),
            )

        assert exc_info.value.code is ReelErrorCode.PROVIDER_FAILURE


class TestBoundedReadRetries:
    async def test_transient_poll_error_retried_then_succeeds(self, profile, tmp_path):
        gen = AsyncMock(return_value=_op(done=False, name="operations/retry-poll"))
        calls = {"n": 0}

        async def _flaky_get(operation):
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("transient")
            return _op(done=True, generated_videos=[_video_ref()])

        client = _fake_client(generate_videos=gen, operations_get=_flaky_get)
        owner = _fake_owner(client)
        adapter = VeoClipAdapter(owner, poll_interval_seconds=0.01, max_read_retries=3)

        clip = await adapter.generate(
            profile=profile,
            prompt="a cat",
            output_directory=tmp_path,
            aspect_ratio="16:9",
            resolution="720p",
            target_duration_seconds=5.0,
            starting_frame=None,
            deadline=FAR_DEADLINE(),
        )

        assert isinstance(clip, GeneratedReelClip)
        gen.assert_awaited_once()
        assert calls["n"] == 3

    async def test_download_failure_after_retries_exhausted_raises(self, profile, tmp_path):
        gen = AsyncMock(return_value=_op(generated_videos=[_video_ref()]))
        download = AsyncMock(side_effect=ConnectionError("download broke"))
        client = _fake_client(generate_videos=gen, files_download=download)
        owner = _fake_owner(client)
        adapter = VeoClipAdapter(owner, max_read_retries=2)

        with pytest.raises(ReelError) as exc_info:
            await adapter.generate(
                profile=profile,
                prompt="a cat",
                output_directory=tmp_path,
                aspect_ratio="16:9",
                resolution="720p",
                target_duration_seconds=5.0,
                starting_frame=None,
                deadline=FAR_DEADLINE(),
            )

        assert exc_info.value.code is ReelErrorCode.PROVIDER_FAILURE
        assert download.await_count == 3  # initial + 2 retries
        gen.assert_awaited_once()


class TestCancellation:
    async def test_cancellation_during_poll_propagates_without_retry(self, profile, tmp_path):
        gen = AsyncMock(return_value=_op(done=False, name="operations/cancel-me"))
        cancel_calls = {"n": 0}

        async def _cancelling_get(operation):
            cancel_calls["n"] += 1
            raise asyncio.CancelledError()

        client = _fake_client(generate_videos=gen, operations_get=_cancelling_get)
        owner = _fake_owner(client)
        adapter = VeoClipAdapter(owner, poll_interval_seconds=0.01, max_read_retries=3)

        with pytest.raises(asyncio.CancelledError):
            await adapter.generate(
                profile=profile,
                prompt="a cat",
                output_directory=tmp_path,
                aspect_ratio="16:9",
                resolution="720p",
                target_duration_seconds=5.0,
                starting_frame=None,
                deadline=FAR_DEADLINE(),
            )

        assert cancel_calls["n"] == 1  # never retried
        client.aio.aclose.assert_awaited_once()  # closed even on cancellation


class TestMediaMeasurement:
    async def test_measures_real_duration_and_audio_flag(self, profile, tmp_path):
        gen = AsyncMock(return_value=_op(generated_videos=[_video_ref()]))
        client = _fake_client(generate_videos=gen)
        owner = _fake_owner(client)
        adapter = VeoClipAdapter(owner)

        fake_clip = MagicMock()
        fake_clip.duration = 6.04
        fake_clip.audio = MagicMock()  # truthy -> has_audio True
        fake_clip.close = MagicMock()
        with patch("moviepy.VideoFileClip", return_value=fake_clip):
            clip = await adapter.generate(
                profile=profile,
                prompt="a cat",
                output_directory=tmp_path,
                aspect_ratio="16:9",
                resolution="720p",
                target_duration_seconds=5.0,
                starting_frame=None,
                deadline=FAR_DEADLINE(),
            )

        assert clip.measured_duration_seconds == 6.04
        assert clip.has_audio is True

    async def test_unreadable_generated_video_raises_media_invalid(self, profile, tmp_path):
        gen = AsyncMock(return_value=_op(generated_videos=[_video_ref()]))
        client = _fake_client(generate_videos=gen)
        owner = _fake_owner(client)
        adapter = VeoClipAdapter(owner)

        with patch("moviepy.VideoFileClip", side_effect=RuntimeError("corrupt file")):
            with pytest.raises(ReelError) as exc_info:
                await adapter.generate(
                    profile=profile,
                    prompt="a cat",
                    output_directory=tmp_path,
                    aspect_ratio="16:9",
                    resolution="720p",
                    target_duration_seconds=5.0,
                    starting_frame=None,
                    deadline=FAR_DEADLINE(),
                )

        assert exc_info.value.code is ReelErrorCode.MEDIA_INVALID

    async def test_unreadable_starting_frame_raises_media_invalid(self, profile, tmp_path):
        bad_frame = tmp_path / "bad.jpg"
        bad_frame.write_bytes(b"not an image")

        gen = AsyncMock(return_value=_op(generated_videos=[_video_ref()]))
        client = _fake_client(generate_videos=gen)
        owner = _fake_owner(client)
        adapter = VeoClipAdapter(owner)

        with pytest.raises(ReelError) as exc_info:
            await adapter.generate(
                profile=profile,
                prompt="a cat",
                output_directory=tmp_path,
                aspect_ratio="16:9",
                resolution="720p",
                target_duration_seconds=5.0,
                starting_frame=bad_frame,
                deadline=FAR_DEADLINE(),
            )

        assert exc_info.value.code is ReelErrorCode.MEDIA_INVALID
        gen.assert_not_awaited()
