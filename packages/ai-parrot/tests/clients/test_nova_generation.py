"""Unit tests for NovaGeneration (FEAT-315, TASK-1808).

Mocks the aioboto3-facing seams (``_ensure_client`` → fake
``invoke_model``/``start_async_invoke``/``get_async_invoke`` — no real AWS
credentials or network access required.
"""
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.clients.nova.generation import NovaGeneration
from parrot.exceptions import InvokeError


class _FakeStreamingBody:
    """Minimal stand-in for botocore's StreamingBody (async ``.read()``)."""

    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode()

    async def read(self):
        return self._payload


class Host(NovaGeneration):
    """Minimal composition host with the attributes the mixin reads."""

    _aws_id = None
    _aws_access_key = None
    _aws_secret_key = None
    _aws_session_token = None
    _region = "us-east-1"
    _profile = None

    def __init__(self, client):
        import logging
        self._client = client
        self.logger = logging.getLogger(__name__)

    def _translate_model(self, model):
        return model or "amazon.nova-canvas-v1:0"

    async def _ensure_client(self):
        return self._client


@pytest.mark.asyncio
class TestGenerateImage:
    async def test_generate_image_payload_and_decode(self, tmp_path):
        png_b64 = base64.b64encode(b"\x89PNG...").decode()
        fake_client = AsyncMock()
        fake_client.invoke_model.return_value = {
            "body": _FakeStreamingBody({"images": [png_b64]})
        }
        host = Host(fake_client)

        msg = await host.generate_image("a cat", output_directory=tmp_path)

        payload = json.loads(fake_client.invoke_model.call_args.kwargs["body"])
        assert payload["taskType"] == "TEXT_IMAGE"
        assert payload["textToImageParams"]["text"] == "a cat"
        assert len(msg.images) == 1
        assert msg.images[0].exists()
        assert msg.images[0].read_bytes() == b"\x89PNG..."

    async def test_generate_image_negative_prompt_and_seed(self, tmp_path):
        png_b64 = base64.b64encode(b"\x89PNG...").decode()
        fake_client = AsyncMock()
        fake_client.invoke_model.return_value = {
            "body": _FakeStreamingBody({"images": [png_b64]})
        }
        host = Host(fake_client)

        await host.generate_image("a cat", negative_prompt="no dogs", seed=42)

        payload = json.loads(fake_client.invoke_model.call_args.kwargs["body"])
        assert payload["textToImageParams"]["negativeText"] == "no dogs"
        assert payload["imageGenerationConfig"]["seed"] == 42

    async def test_generate_image_as_base64(self):
        png_b64 = base64.b64encode(b"\x89PNG...").decode()
        fake_client = AsyncMock()
        fake_client.invoke_model.return_value = {
            "body": _FakeStreamingBody({"images": [png_b64]})
        }
        host = Host(fake_client)

        msg = await host.generate_image("a cat", as_base64=True)
        assert msg.output == [png_b64]


@pytest.mark.asyncio
class TestVideoGeneration:
    async def test_video_generation_requires_s3_config(self):
        host = Host(AsyncMock())
        with patch(
            "parrot.clients.nova.generation.AWS_CREDENTIALS", {"default": {}}
        ):
            with pytest.raises(ValueError, match="s3_output_uri|bucket_name"):
                await host.video_generation("a dancing robot")

    async def test_resolve_s3_output_uri_named_profile_falls_back_to_default_bucket(self):
        """Code-review regression test (FEAT-315): a named aws_id profile
        that lacks bucket_name must fall back to the 'default' profile's
        bucket_name (mirrors BedrockConverseBase's credential-resolution
        fallback-to-'default' convention) instead of raising immediately."""
        host = Host(AsyncMock())
        host._aws_id = "monitoring"
        with patch(
            "parrot.clients.nova.generation.AWS_CREDENTIALS",
            {"monitoring": {}, "default": {"bucket_name": "default-bucket"}},
        ):
            uri = host._resolve_s3_output_uri(None)
        assert uri == "s3://default-bucket/nova-reel-output/"

    async def test_resolve_s3_output_uri_named_profile_bucket_wins_over_default(self):
        host = Host(AsyncMock())
        host._aws_id = "monitoring"
        with patch(
            "parrot.clients.nova.generation.AWS_CREDENTIALS",
            {
                "monitoring": {"bucket_name": "monitoring-bucket"},
                "default": {"bucket_name": "default-bucket"},
            },
        ):
            uri = host._resolve_s3_output_uri(None)
        assert uri == "s3://monitoring-bucket/nova-reel-output/"

    async def test_video_generation_polls_until_complete(self, tmp_path):
        fake_client = AsyncMock()
        fake_client.start_async_invoke.return_value = {
            "invocationArn": "arn:aws:bedrock:us-east-1:123:async-invoke/job-1"
        }
        in_progress = {"status": "InProgress"}
        completed = {
            "status": "Completed",
            "outputDataConfig": {
                "s3OutputDataConfig": {"s3Uri": "s3://my-bucket/nova-reel-output/"}
            },
        }
        fake_client.get_async_invoke.side_effect = [in_progress, completed]

        fake_body = MagicMock()
        fake_body.read = AsyncMock(return_value=b"FAKEMP4BYTES")
        fake_s3_client = AsyncMock()
        fake_s3_client.get_object.return_value = {"Body": fake_body}

        fake_s3_cm = AsyncMock()
        fake_s3_cm.__aenter__.return_value = fake_s3_client
        fake_s3_cm.__aexit__.return_value = None

        fake_session = MagicMock()
        fake_session.client.return_value = fake_s3_cm

        host = Host(fake_client)

        with patch("aioboto3.Session", return_value=fake_session), \
                patch("asyncio.sleep", new=AsyncMock()), \
                patch(
                    "parrot.clients.nova.generation.AWS_CREDENTIALS",
                    {"default": {"bucket_name": "my-bucket"}},
                ):
            msg = await host.video_generation(
                "a dancing robot", output_directory=tmp_path, poll_interval=0.01,
            )

        assert fake_client.get_async_invoke.call_count == 2
        assert Path(msg.output).exists()
        assert Path(msg.output).read_bytes() == b"FAKEMP4BYTES"

    async def test_video_generation_failed_job_raises(self):
        fake_client = AsyncMock()
        fake_client.start_async_invoke.return_value = {
            "invocationArn": "arn:aws:bedrock:us-east-1:123:async-invoke/job-2"
        }
        fake_client.get_async_invoke.return_value = {
            "status": "Failed", "failureMessage": "boom",
        }
        host = Host(fake_client)

        with pytest.raises(InvokeError, match="boom"):
            await host.video_generation("a dancing robot", s3_output_uri="s3://bucket/prefix/")

    async def test_video_generation_times_out(self):
        fake_client = AsyncMock()
        fake_client.start_async_invoke.return_value = {
            "invocationArn": "arn:aws:bedrock:us-east-1:123:async-invoke/job-3"
        }
        fake_client.get_async_invoke.return_value = {"status": "InProgress"}
        host = Host(fake_client)

        with patch("asyncio.sleep", new=AsyncMock()):
            with pytest.raises(InvokeError, match="did not complete"):
                await host.video_generation(
                    "a dancing robot", s3_output_uri="s3://bucket/prefix/",
                    poll_interval=1.0, timeout=1.0,
                )
