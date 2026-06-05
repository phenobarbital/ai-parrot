"""Unit tests for GoogleGenAIClient Batch API and Flex Inference."""
import asyncio
import json
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel

from datamodel.parsers.json import json_decoder, json_encoder
from parrot.models.responses import AIMessage
from parrot.models.basic import CompletionUsage
from parrot.models.google import GoogleModel


class TestData(BaseModel):
    name: str
    age: int


def _make_client():
    """Create GoogleGenAIClient without network setup."""
    from parrot.clients.google.client import GoogleGenAIClient
    client = GoogleGenAIClient.__new__(GoogleGenAIClient)
    client.model = "gemini-2.5-flash"
    client._lightweight_model = "gemini-3-flash-lite"
    client._fallback_model = None
    client.enable_tools = False
    client.temperature = 0.7
    client.max_tokens = 100
    client.logger = MagicMock()
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    client._tool_manager.tools = {}
    from datamodel.parsers.json import JSONContent
    client._json = JSONContent()
    return client


@pytest.fixture
def mock_google_client():
    """GoogleGenAIClient with mocked SDK."""
    client = _make_client()
    
    # Create mock SDK client
    sdk_client = MagicMock()
    sdk_client.aio = MagicMock()
    sdk_client.aio.batches = MagicMock()
    sdk_client.aio.files = MagicMock()
    sdk_client.aio.models = MagicMock()
    
    # Redefine client property to return our mocked SDK client
    type(client).client = property(lambda self: sdk_client)
    
    client._ensure_client = AsyncMock(return_value=sdk_client)
    
    return client


class TestGoogleBatch:
    """Tests for GoogleGenAIClient batch API and flex inference."""

    async def test_build_batch_request_payload(self, mock_google_client):
        """Verify _build_batch_request_payload correctly formats requests."""
        req = {
            "prompt": "Hello Gemini",
            "temperature": 0.5,
            "max_tokens": 150,
            "system_prompt": "You are a helpful assistant",
            "structured_output": TestData
        }
        
        payload = await mock_google_client._build_batch_request_payload(req)
        
        assert payload["contents"] == [{"parts": [{"text": "Hello Gemini"}]}]
        assert payload["system_instruction"] == {"parts": [{"text": "You are a helpful assistant"}]}
        assert payload["generation_config"]["temperature"] == 0.5
        assert payload["generation_config"]["max_output_tokens"] == 150
        assert payload["generation_config"]["response_mime_type"] == "application/json"
        assert "response_schema" in payload["generation_config"]

    async def test_ask_batch_flex(self, mock_google_client):
        """Verify ask_batch with use_flex=True delegates to ask() concurrently."""
        mock_google_client.ask = AsyncMock()
        mock_google_client.ask.side_effect = [
            AIMessage(input="test 1", output="response 1", model="gemini-2.5-flash", provider="google", usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)),
            AIMessage(input="test 2", output="response 2", model="gemini-2.5-flash", provider="google", usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0))
        ]
        
        requests = [
            {"prompt": "test 1"},
            {"prompt": "test 2"}
        ]
        
        results = await mock_google_client.ask_batch(requests, use_flex=True)
        
        assert len(results) == 2
        assert results[0].output == "response 1"
        assert results[1].output == "response 2"
        
        # Verify ask was called with service_tier="flex"
        mock_google_client.ask.assert_any_call(prompt="test 1", service_tier="flex")
        mock_google_client.ask.assert_any_call(prompt="test 2", service_tier="flex")

    async def test_ask_batch_async_wait_for_completion(self, mock_google_client):
        """Verify async ask_batch flows completely from file upload to job polling and results parsing."""
        sdk_client = await mock_google_client._ensure_client()
        
        # Setup mocks
        mock_file = SimpleNamespace(name="files/input-file")
        sdk_client.aio.files.upload = AsyncMock(return_value=mock_file)
        
        mock_job = SimpleNamespace(
            name="batches/job-123",
            state="JOB_STATE_PENDING",
            dest=SimpleNamespace(file_name="files/output-file"),
            error=None
        )
        sdk_client.aio.batches.create = AsyncMock(return_value=mock_job)
        
        # We'll simulate polling: pending -> succeeded
        mock_job_succeeded = SimpleNamespace(
            name="batches/job-123",
            state="JOB_STATE_SUCCEEDED",
            dest=SimpleNamespace(file_name="files/output-file"),
            error=None
        )
        sdk_client.aio.batches.get = AsyncMock(return_value=mock_job_succeeded)
        
        # Mock download results
        # We need GenerateContentResponse structures serialized as JSON lines
        output_data = (
            '{"key": "req_0", "response": {"candidates": [{"content": {"parts": [{"text": "response 1"}], "role": "model"}, "finishReason": "STOP", "index": 0}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 5, "totalTokenCount": 10}}}\n'
            '{"key": "req_1", "response": {"candidates": [{"content": {"parts": [{"text": "response 2"}], "role": "model"}, "finishReason": "STOP", "index": 0}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 5, "totalTokenCount": 10}}}\n'
        )
        sdk_client.aio.files.download = AsyncMock(return_value=output_data.encode("utf-8"))
        sdk_client.aio.files.delete = AsyncMock()

        requests = [
            {"prompt": "test 1"},
            {"prompt": "test 2"}
        ]
        
        results = await mock_google_client.ask_batch(requests, use_flex=False, poll_interval=1)
        
        assert len(results) == 2
        assert results[0].output == "response 1"
        assert results[1].output == "response 2"
        
        # Check files uploads & batch creation calls
        sdk_client.aio.files.upload.assert_called_once()
        sdk_client.aio.batches.create.assert_called_once()
        sdk_client.aio.batches.get.assert_called()
        sdk_client.aio.files.download.assert_called_once_with(file="files/output-file")
        
        # Check files deletes (input and output)
        sdk_client.aio.files.delete.assert_any_call(name="files/input-file")
        sdk_client.aio.files.delete.assert_any_call(name="files/output-file")

    async def test_ask_batch_async_no_wait(self, mock_google_client):
        """Verify ask_batch returns job immediately when wait_for_completion=False."""
        sdk_client = await mock_google_client._ensure_client()
        
        mock_file = SimpleNamespace(name="files/input-file")
        sdk_client.aio.files.upload = AsyncMock(return_value=mock_file)
        
        mock_job = SimpleNamespace(
            name="batches/job-123",
            state="JOB_STATE_PENDING"
        )
        sdk_client.aio.batches.create = AsyncMock(return_value=mock_job)
        
        requests = [{"prompt": "test 1"}]
        job = await mock_google_client.ask_batch(requests, wait_for_completion=False)
        
        assert job.name == "batches/job-123"
        assert job.state == "JOB_STATE_PENDING"
        
        sdk_client.aio.files.upload.assert_called_once()
        sdk_client.aio.batches.create.assert_called_once()
        sdk_client.aio.batches.get.assert_not_called()

    async def test_get_batch_job(self, mock_google_client):
        """Verify get_batch_job retrieves the requested job."""
        sdk_client = await mock_google_client._ensure_client()
        mock_job = SimpleNamespace(name="batches/job-123")
        sdk_client.aio.batches.get = AsyncMock(return_value=mock_job)
        
        job = await mock_google_client.get_batch_job("batches/job-123")
        assert job.name == "batches/job-123"
        sdk_client.aio.batches.get.assert_called_once_with(name="batches/job-123")

    async def test_cancel_batch_job(self, mock_google_client):
        """Verify cancel_batch_job cancels the requested job."""
        sdk_client = await mock_google_client._ensure_client()
        mock_job = SimpleNamespace(name="batches/job-123", state="JOB_STATE_CANCELLED")
        sdk_client.aio.batches.cancel = AsyncMock(return_value=mock_job)
        
        job = await mock_google_client.cancel_batch_job("batches/job-123")
        assert job.state == "JOB_STATE_CANCELLED"
        sdk_client.aio.batches.cancel.assert_called_once_with(name="batches/job-123")

    async def test_list_batch_jobs(self, mock_google_client):
        """Verify list_batch_jobs yields all batch jobs."""
        sdk_client = await mock_google_client._ensure_client()
        
        async def mock_list():
            yield SimpleNamespace(name="batches/job-1")
            yield SimpleNamespace(name="batches/job-2")
            
        sdk_client.aio.batches.list = mock_list
        
        jobs = await mock_google_client.list_batch_jobs()
        assert len(jobs) == 2
        assert jobs[0].name == "batches/job-1"
        assert jobs[1].name == "batches/job-2"

    async def test_generate_image_batch(self, mock_google_client):
        """Verify generate_image_batch executes generate_image concurrently."""
        mock_google_client.generate_image = AsyncMock()
        mock_google_client.generate_image.side_effect = [
            AIMessage(input="prompt 1", output=None, response="ok", model="gemini-3.1-flash-image", provider="google", usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)),
            AIMessage(input="prompt 2", output=None, response="ok", model="gemini-3.1-flash-image", provider="google", usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0))
        ]
        
        requests = [{"prompt": "prompt 1"}, {"prompt": "prompt 2"}]
        results = await mock_google_client.generate_image_batch(requests, use_flex=True)
        
        assert len(results) == 2
        mock_google_client.generate_image.assert_any_call(prompt="prompt 1", service_tier="flex")
        mock_google_client.generate_image.assert_any_call(prompt="prompt 2", service_tier="flex")

    async def test_generate_video_batch(self, mock_google_client):
        """Verify generate_video_batch executes video_generation concurrently."""
        mock_google_client.video_generation = AsyncMock()
        mock_google_client.video_generation.side_effect = [
            AIMessage(input="prompt 1", output=None, response="ok", model="veo-3.1-generate-preview", provider="google", usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)),
            AIMessage(input="prompt 2", output=None, response="ok", model="veo-3.1-generate-preview", provider="google", usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0))
        ]
        
        requests = [{"prompt": "prompt 1"}, {"prompt": "prompt 2"}]
        results = await mock_google_client.generate_video_batch(requests)
        
        assert len(results) == 2
        mock_google_client.video_generation.assert_any_call(prompt="prompt 1")
        mock_google_client.video_generation.assert_any_call(prompt="prompt 2")

    async def test_persist_batch_results(self, mock_google_client, tmp_path):
        """Verify persist_batch_results writes JSON files, copies images/videos, and formats files correctly."""
        # Create dummy image and video files
        dummy_img = tmp_path / "dummy_image.png"
        dummy_img.write_text("dummy image data")
        dummy_vid = tmp_path / "dummy_video.mp4"
        dummy_vid.write_text("dummy video data")

        results = [
            AIMessage(
                input="prompt text",
                output="output text",
                response="response text",
                model="gemini-2.5-flash",
                provider="google",
                usage=CompletionUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
                images=[dummy_img],
                files=[dummy_vid],
                structured_output={"key": "value"}
            )
        ]

        # Call persist_batch_results
        google_client = _make_client()
        google_client.persist_batch_results = mock_google_client.persist_batch_results
        google_client.logger = mock_google_client.logger
        
        dest_dir = await google_client.persist_batch_results(
            results,
            batch_id="test_batch_123",
            save_dir=tmp_path / "custom_batch_results"
        )

        assert dest_dir.exists()
        assert dest_dir.joinpath("result_0_message.json").exists()
        assert dest_dir.joinpath("result_0_structured.json").exists()
        assert dest_dir.joinpath("result_0_response.txt").exists()
        
        # Check files were copied with timestamps in their names
        copied_images = list(dest_dir.joinpath("images").glob("dummy_image_*.png"))
        copied_videos = list(dest_dir.joinpath("files").glob("dummy_video_*.mp4"))
        assert len(copied_images) == 1
        assert len(copied_videos) == 1

        # Read JSON file and verify copied path updates
        with open(dest_dir.joinpath("result_0_message.json"), "r") as f:
            data = json_decoder(f.read())
            assert copied_images[0].name in data["images"][0]
            assert copied_videos[0].name in data["files"][0]
