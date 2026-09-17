"""TASK-3326: Omni async Interactions clip adapter contract tests.

Mocks the owner's `get_client()`, its `aio.interactions.create`/`aio.aclose`
surface, and the injected `ProviderMediaDownloader`, while the REAL
`OmniClipAdapter.generate()` normalization/materialization/measurement logic
runs end to end.
"""

from __future__ import annotations

import asyncio
import base64
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.clients.google.reel.clip import GeneratedReelClip
from parrot.clients.google.reel.download import ProviderMediaDownloader
from parrot.clients.google.reel.errors import ReelError, ReelErrorCode, ReelValidationError
from parrot.clients.google.reel.omni import OmniClipAdapter
from parrot.clients.google.reel.profiles import VideoProfileRegistry

FAR_DEADLINE = lambda: time.monotonic() + 30.0  # noqa: E731


@pytest.fixture
def profile():
    return VideoProfileRegistry.default().resolve("gemini-omni-1.1-flash", "gemini_developer")


def _interaction(*, status="completed", errors=None, output_video=None, id="interactions/abc123"):
    return SimpleNamespace(status=status, errors=errors, output_video=output_video, id=id)


def _video_content(*, data=None, uri=None, mime_type="video/mp4"):
    return SimpleNamespace(data=data, uri=uri, mime_type=mime_type)


def _fake_owner(client):
    owner = MagicMock()
    owner.get_client = AsyncMock(return_value=client)
    return owner


def _fake_client(*, create):
    client = MagicMock()
    client.aio = MagicMock()
    client.aio.interactions = MagicMock()
    client.aio.interactions.create = create
    client.aio.aclose = AsyncMock()
    return client


@pytest.fixture
def downloader():
    d = MagicMock(spec=ProviderMediaDownloader)
    d.fetch = AsyncMock()
    return d


@pytest.fixture(autouse=True)
def _fake_moviepy():
    fake_clip = MagicMock()
    fake_clip.duration = 5.08
    fake_clip.audio = MagicMock()  # Omni: native_audio="always" -> present by default in tests
    fake_clip.close = MagicMock()
    with patch("moviepy.VideoFileClip", return_value=fake_clip):
        yield


class TestCreateKwargs:
    async def test_no_veo_fields_and_no_duration_in_response_format(self, profile, downloader, tmp_path):
        video = _video_content(data=base64.b64encode(b"FAKEVIDEO").decode("ascii"))
        create = AsyncMock(return_value=_interaction(output_video=video))
        client = _fake_client(create=create)
        owner = _fake_owner(client)
        adapter = OmniClipAdapter(owner, downloader)

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

        create.assert_awaited_once()
        kwargs = create.call_args.kwargs
        assert kwargs["agent"] == "gemini-omni-1.1-flash"
        assert kwargs["input"] == "a cat"
        assert kwargs["background"] is False
        assert kwargs["store"] is False
        assert kwargs["stream"] is False
        assert "temperature" not in kwargs
        assert "negative_prompt" not in kwargs
        assert "duration" not in kwargs["response_format"]
        assert kwargs["response_format"]["aspect_ratio"] == "16:9"

    async def test_client_closed_on_success(self, profile, downloader, tmp_path):
        video = _video_content(data=base64.b64encode(b"FAKEVIDEO").decode("ascii"))
        create = AsyncMock(return_value=_interaction(output_video=video))
        client = _fake_client(create=create)
        owner = _fake_owner(client)
        adapter = OmniClipAdapter(owner, downloader)

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

        client.aio.aclose.assert_awaited_once()


class TestInlineAndUriDelivery:
    async def test_inline_data_success_measures_duration_and_audio(self, profile, downloader, tmp_path):
        payload = b"FAKEVIDEOBYTESHERE"
        video = _video_content(data=base64.b64encode(payload).decode("ascii"))
        create = AsyncMock(return_value=_interaction(output_video=video))
        client = _fake_client(create=create)
        owner = _fake_owner(client)
        adapter = OmniClipAdapter(owner, downloader)

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
        assert clip.backend == "omni"
        assert clip.submitted_duration_seconds is None
        assert clip.measured_duration_seconds == 5.08
        assert clip.has_audio is True
        assert clip.local_path.read_bytes() == payload
        downloader.fetch.assert_not_called()

    async def test_uri_delivery_uses_downloader(self, profile, downloader, tmp_path):
        uri = "https://generativelanguage.googleapis.com/files/abc"
        video = _video_content(uri=uri)
        create = AsyncMock(return_value=_interaction(output_video=video))
        client = _fake_client(create=create)
        owner = _fake_owner(client)

        expected_path = tmp_path / "downloaded.mp4"
        expected_path.write_bytes(b"DOWNLOADEDBYTES")
        downloader.fetch = AsyncMock(return_value=expected_path)

        adapter = OmniClipAdapter(owner, downloader)

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

        downloader.fetch.assert_awaited_once()
        fetch_kwargs = downloader.fetch.call_args
        assert fetch_kwargs.args[0] == uri
        assert clip.local_path == expected_path

    async def test_mime_type_selects_correct_extension(self, profile, downloader, tmp_path):
        video = _video_content(data=base64.b64encode(b"X").decode("ascii"), mime_type="video/webm")
        create = AsyncMock(return_value=_interaction(output_video=video))
        client = _fake_client(create=create)
        owner = _fake_owner(client)
        adapter = OmniClipAdapter(owner, downloader)

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

        assert clip.local_path.suffix == ".webm"


class TestMalformedAndEmptyOutput:
    async def test_malformed_base64_raises_media_invalid(self, profile, downloader, tmp_path):
        video = _video_content(data="not-valid-base64!!!")
        create = AsyncMock(return_value=_interaction(output_video=video))
        client = _fake_client(create=create)
        owner = _fake_owner(client)
        adapter = OmniClipAdapter(owner, downloader)

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

    async def test_empty_decoded_bytes_raises_media_invalid(self, profile, downloader, tmp_path):
        video = _video_content(data=base64.b64encode(b"").decode("ascii"))
        create = AsyncMock(return_value=_interaction(output_video=video))
        client = _fake_client(create=create)
        owner = _fake_owner(client)
        adapter = OmniClipAdapter(owner, downloader)

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

    async def test_no_output_video_raises(self, profile, downloader, tmp_path):
        create = AsyncMock(return_value=_interaction(output_video=None))
        client = _fake_client(create=create)
        owner = _fake_owner(client)
        adapter = OmniClipAdapter(owner, downloader)

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

    async def test_video_content_with_neither_data_nor_uri_raises(self, profile, downloader, tmp_path):
        video = _video_content()
        create = AsyncMock(return_value=_interaction(output_video=video))
        client = _fake_client(create=create)
        owner = _fake_owner(client)
        adapter = OmniClipAdapter(owner, downloader)

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

    async def test_blocked_terminal_status_preserves_interaction_id(self, profile, downloader, tmp_path):
        error = SimpleNamespace(code="content_policy", message="blocked by policy")
        create = AsyncMock(return_value=_interaction(status="failed", errors=[error], id="interactions/blocked-1"))
        client = _fake_client(create=create)
        owner = _fake_owner(client)
        adapter = OmniClipAdapter(owner, downloader)

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

        assert exc_info.value.operation_id == "interactions/blocked-1"

    async def test_unexpected_in_progress_status_raises(self, profile, downloader, tmp_path):
        create = AsyncMock(return_value=_interaction(status="queued"))
        client = _fake_client(create=create)
        owner = _fake_owner(client)
        adapter = OmniClipAdapter(owner, downloader)

        with pytest.raises(ReelError):
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

    async def test_too_short_measured_duration_raises_insufficient_duration(self, profile, downloader, tmp_path):
        video = _video_content(data=base64.b64encode(b"X").decode("ascii"))
        create = AsyncMock(return_value=_interaction(output_video=video))
        client = _fake_client(create=create)
        owner = _fake_owner(client)
        adapter = OmniClipAdapter(owner, downloader)

        short_clip = MagicMock()
        short_clip.duration = 1.0  # far short of a 5s target
        short_clip.audio = None
        short_clip.close = MagicMock()
        with patch("moviepy.VideoFileClip", return_value=short_clip):
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

        assert exc_info.value.code is ReelErrorCode.INSUFFICIENT_DURATION

    async def test_download_failure_normalized(self, profile, downloader, tmp_path):
        from parrot.clients.google.reel.errors import DownloadFailure

        video = _video_content(uri="https://generativelanguage.googleapis.com/files/x")
        create = AsyncMock(return_value=_interaction(output_video=video))
        client = _fake_client(create=create)
        owner = _fake_owner(client)
        downloader.fetch = AsyncMock(side_effect=DownloadFailure("boom"))
        adapter = OmniClipAdapter(owner, downloader)

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

        assert exc_info.value.code is ReelErrorCode.DOWNLOAD_FAILED


class TestStartingFrameAndDeadline:
    async def test_starting_frame_rejected_before_any_client_call(self, profile, downloader, tmp_path):
        create = AsyncMock()
        client = _fake_client(create=create)
        owner = _fake_owner(client)
        adapter = OmniClipAdapter(owner, downloader)

        with pytest.raises(ReelValidationError) as exc_info:
            await adapter.generate(
                profile=profile,
                prompt="a cat",
                output_directory=tmp_path,
                aspect_ratio="16:9",
                resolution="720p",
                target_duration_seconds=5.0,
                starting_frame=tmp_path / "frame.jpg",
                deadline=FAR_DEADLINE(),
            )

        assert exc_info.value.code is ReelErrorCode.UNSUPPORTED_OPTION
        owner.get_client.assert_not_called()
        create.assert_not_called()

    async def test_already_expired_deadline_raises_without_submission(self, profile, downloader, tmp_path):
        create = AsyncMock()
        client = _fake_client(create=create)
        owner = _fake_owner(client)
        adapter = OmniClipAdapter(owner, downloader)

        with pytest.raises(ReelError) as exc_info:
            await adapter.generate(
                profile=profile,
                prompt="a cat",
                output_directory=tmp_path,
                aspect_ratio="16:9",
                resolution="720p",
                target_duration_seconds=5.0,
                starting_frame=None,
                deadline=time.monotonic() - 1.0,
            )

        assert exc_info.value.code is ReelErrorCode.TIMEOUT
        create.assert_not_called()


class TestCancellation:
    async def test_cancellation_during_create_propagates_and_closes_client(self, profile, downloader, tmp_path):
        create = AsyncMock(side_effect=asyncio.CancelledError())
        client = _fake_client(create=create)
        owner = _fake_owner(client)
        adapter = OmniClipAdapter(owner, downloader)

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

        client.aio.aclose.assert_awaited_once()
