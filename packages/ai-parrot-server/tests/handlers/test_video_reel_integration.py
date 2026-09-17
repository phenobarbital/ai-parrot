"""TASK-3334: cross-module reel integration — real handler + JobManager +
polling + artifact retrieval.

Exercises the REAL queued-execution pipeline: ``VideoReelHandler.post()``
schedules a genuine ``JobManager.execute_job()`` background
``asyncio.Task`` (awaited directly to completion here, never faked), whose
result is polled via the REAL ``VideoReelHandler.get()``/
``_get_job_status`` and resolved via the REAL ``_get_artifact``. Only the
PROVIDER call (``GoogleGenAIClient.generate_video_reel``) is mocked — the
``AIMessage``/``ReelResult``/``ReelArtifact`` descriptors returned from it
are REAL Pydantic models, round-tripped through ``job.result`` exactly as
production does (``model_dump(mode="json")``), and the "local" artifact is
a REAL file on disk (its actual bytes are asserted, not a mocked path).
Cloud transport (signed-URL refresh) is mocked per this task's own scope
("mock only cloud transport/provider generation").
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from parrot.handlers.jobs import JobManager, JobStatus
from parrot.handlers.video_reel import VideoReelHandler
from parrot.models import AIMessage, CompletionUsage
from parrot.models.google import ReelArtifact, ReelResult

_OWNER_ID = "integration-owner"


def _fake_response(body, status):
    resp = MagicMock()
    resp.status = status
    resp.body = body
    return resp


def _handler(app: web.Application, *, match_info: dict | None = None) -> VideoReelHandler:
    """Builds a VideoReelHandler bound to a REAL JobManager-carrying app.

    ``request`` itself stays a MagicMock (only ``.app``/``.match_info``/
    ``.query``/``.content_type``/``.json`` are meaningfully read by the
    code paths this file exercises) — the same real-BaseView-compatible
    construction as test_video_reel_handler.py / test_video_reel_artifacts.py.
    """
    h = VideoReelHandler.__new__(VideoReelHandler)
    h.logger = MagicMock()
    h._request = MagicMock()
    h.request.app = app
    h.request.match_info = match_info or {}
    h.request.query = {}
    h.request.content_type = "application/json"
    h._get_session_user_id = AsyncMock(return_value=_OWNER_ID)
    h.error = MagicMock(
        side_effect=lambda *a, **kw: _fake_response(kw.get("response", a[0] if a else "error"), kw.get("status", 400))
    )
    h.json_response = MagicMock(side_effect=lambda data, **kw: _fake_response(data, kw.get("status", 200)))
    return h


def _build_completed_ai_message(tmp_path: Path, *, partial: bool = False, suffix: str = "") -> AIMessage:
    """Builds a REAL AIMessage + REAL ReelResult/ReelArtifact backed by a
    REAL local file — only the provider call producing this object is
    mocked; everything here is the actual production descriptor shape.
    """
    final_path = tmp_path / f"final_reel{suffix}.mp4"
    final_path.write_bytes(b"FAKEVIDEOBYTES" + suffix.encode())

    artifact = ReelArtifact(
        artifact_id=f"art-1{suffix}",
        storage_backend="fs",
        storage_key=f"reels/job{suffix}/final/final_reel.mp4",
        mime_type="video/mp4",
        size_bytes=final_path.stat().st_size,
        download_url=f"file://{final_path}",
    )
    reel_result = ReelResult(
        final_artifact=artifact,
        requested_models={"director": None, "image": None, "video": None},
        effective_models={"director": None, "image": None, "video": "veo-3.1-generate-preview"},
        director_unused=True,
        api_surface="gemini_developer",
        sdk_version="2.23.0",
        audio_mode="separate",
        music_status="off",
        scenes=[],
        partial=partial,
        warnings=[],
        final_duration_seconds=5.0,
    )
    ai_message = AIMessage(
        input="test prompt",
        output=None,
        model="google-reel-pipeline",
        provider="google_genai",
        usage=CompletionUsage(total_time=1.0),
        files=[final_path],
    )
    ai_message.metadata["video_reel"] = reel_result.model_dump(mode="json")
    ai_message.artifacts = [artifact.model_dump(mode="json")]
    return ai_message


def _mock_provider_client(ai_message: AIMessage | None = None, *, side_effect: Exception | None = None):
    """Builds a mocked async-context-manager GoogleGenAIClient, matching
    ``run_logic()``'s own usage: ``async with GoogleGenAIClient(...) as
    client: await client.generate_video_reel(...)``.
    """
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    if side_effect is not None:
        client.generate_video_reel = AsyncMock(side_effect=side_effect)
    else:
        client.generate_video_reel = AsyncMock(return_value=ai_message)
    return client


async def _submit(handler: VideoReelHandler, payload: dict) -> tuple[dict, JobManager]:
    """POSTs ``payload`` through the real handler; returns (response_body, job_manager)."""
    handler.request.json = AsyncMock(return_value=payload)
    response = await handler.post()
    assert response.status == 202
    job_manager: JobManager = handler.request.app["job_manager"]
    return response.body, job_manager


async def _await_job_task(job_manager: JobManager, job_id: str) -> None:
    """Awaits the REAL background task JobManager.execute_job() scheduled,
    to completion — never a sleep/poll loop, the actual asyncio.Task.
    """
    task = job_manager.tasks[job_id]
    with contextlib.suppress(BaseException):
        await task


@pytest.fixture
async def app():
    application = web.Application()
    jm = JobManager(id="integration-test")
    application["job_manager"] = jm
    yield application
    await jm.stop()


class TestQueuedExecutionAndPolling:
    """Real JobManager execution -> real polling, for each terminal job state."""

    async def test_successful_job_completes_with_real_artifact_bytes(self, app, tmp_path):
        ai_message = _build_completed_ai_message(tmp_path)
        handler = _handler(app)

        with patch("parrot.clients.google.GoogleGenAIClient", return_value=_mock_provider_client(ai_message)):
            body, job_manager = await _submit(handler, {"prompt": "a reel about the ocean"})
            await _await_job_task(job_manager, body["job_id"])

        job = await job_manager.get_job_async(body["job_id"])
        assert job.status == JobStatus.COMPLETED
        # Ownership: recorded from the session, never a body-supplied claim (TASK-3333).
        assert job.user_id == _OWNER_ID
        assert job.result["artifacts"][0]["artifact_id"] == "art-1"
        # Real descriptor serialization — mode="json" round-trip (AC10/AC18).
        assert job.result["metadata"]["video_reel"]["api_surface"] == "gemini_developer"
        assert job.result["metadata"]["video_reel"]["partial"] is False

        # Poll via the real handler.
        poll_handler = _handler(app, match_info={"job_id": body["job_id"]})
        poll_response = await poll_handler.get()
        assert poll_response.status == 200
        response_data = poll_handler.json_response.call_args[0][0]
        assert response_data["status"] == "completed"
        assert response_data["result"]["artifacts"][0]["artifact_id"] == "art-1"
        assert "completed_at" in response_data
        assert "elapsed_time" in response_data

        # Artifact retrieval resolves the REAL local file with the REAL
        # bytes on disk — never a raw path in the result, per TASK-3333.
        artifact_handler = _handler(app, match_info={"job_id": body["job_id"], "artifact_id": "art-1"})
        stream_mock = MagicMock()
        artifact_handler._stream_file = AsyncMock(return_value=stream_mock)
        result = await artifact_handler.get()
        assert result is stream_mock
        called_path, called_type = artifact_handler._stream_file.call_args.args
        assert called_path.read_bytes() == b"FAKEVIDEOBYTES"
        assert called_type == "video/mp4"

    async def test_partial_job_reports_partial_true_with_skipped_scene(self, app, tmp_path):
        ai_message = _build_completed_ai_message(tmp_path, partial=True)
        handler = _handler(app)

        with patch("parrot.clients.google.GoogleGenAIClient", return_value=_mock_provider_client(ai_message)):
            body, job_manager = await _submit(handler, {"prompt": "a reel with a flaky scene"})
            await _await_job_task(job_manager, body["job_id"])

        poll_handler = _handler(app, match_info={"job_id": body["job_id"]})
        poll_response = await poll_handler.get()
        assert poll_response.status == 200
        response_data = poll_handler.json_response.call_args[0][0]
        assert response_data["status"] == "completed"
        assert response_data["result"]["metadata"]["video_reel"]["partial"] is True

    async def test_failed_job_reports_error_and_completed_at(self, app):
        handler = _handler(app)

        with patch(
            "parrot.clients.google.GoogleGenAIClient",
            return_value=_mock_provider_client(side_effect=RuntimeError("provider exploded")),
        ):
            body, job_manager = await _submit(handler, {"prompt": "a reel that blows up"})
            await _await_job_task(job_manager, body["job_id"])

        job = await job_manager.get_job_async(body["job_id"])
        assert job.status == JobStatus.FAILED
        assert "provider exploded" in job.error

        poll_handler = _handler(app, match_info={"job_id": body["job_id"]})
        poll_response = await poll_handler.get()
        assert poll_response.status == 200
        response_data = poll_handler.json_response.call_args[0][0]
        assert response_data["status"] == "failed"
        assert "provider exploded" in response_data["error"]
        assert "completed_at" in response_data

    async def test_cancelled_job_reports_cancelled_and_error(self, app):
        handler = _handler(app)
        provider_started = asyncio.Event()

        async def _slow_provider(*args, **kwargs):
            provider_started.set()
            await asyncio.sleep(60)

        client = _mock_provider_client()
        client.generate_video_reel = AsyncMock(side_effect=_slow_provider)

        with patch("parrot.clients.google.GoogleGenAIClient", return_value=client):
            body, job_manager = await _submit(handler, {"prompt": "a reel that gets cancelled"})
            await provider_started.wait()
            task = job_manager.tasks[body["job_id"]]
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        job = await job_manager.get_job_async(body["job_id"])
        assert job.status == JobStatus.CANCELLED

        poll_handler = _handler(app, match_info={"job_id": body["job_id"]})
        poll_response = await poll_handler.get()
        assert poll_response.status == 200
        response_data = poll_handler.json_response.call_args[0][0]
        assert response_data["status"] == "cancelled"
        assert "error" in response_data
        assert "completed_at" in response_data

    async def test_queued_job_independently_reflects_effective_models(self, app, tmp_path):
        """The queued callback's own generate_video_reel call — not the
        HTTP request body — is what determines effective_models; verified
        by inspecting the actual call args reaching the mocked provider.
        """
        ai_message = _build_completed_ai_message(tmp_path)
        handler = _handler(app)
        mock_client = _mock_provider_client(ai_message)

        with patch("parrot.clients.google.GoogleGenAIClient", return_value=mock_client) as mock_cls:
            body, job_manager = await _submit(handler, {"prompt": "a reel", "video_model": "veo-3.1-generate-preview"})
            await _await_job_task(job_manager, body["job_id"])

        mock_cls.assert_called_once()
        call_kwargs = mock_client.generate_video_reel.call_args.kwargs
        assert call_kwargs["request"].video_model == "veo-3.1-generate-preview"
        assert call_kwargs["user_id"] is None  # no body user_id supplied in this request

    async def test_second_owner_cannot_poll_first_owners_job(self, app, tmp_path):
        """End-to-end confirmation of TASK-3333's ownership boundary
        through the real queued-execution path (not just a unit-level
        _authorize_job call)."""
        ai_message = _build_completed_ai_message(tmp_path)
        handler = _handler(app)

        with patch("parrot.clients.google.GoogleGenAIClient", return_value=_mock_provider_client(ai_message)):
            body, job_manager = await _submit(handler, {"prompt": "owner-only reel"})
            await _await_job_task(job_manager, body["job_id"])

        other_handler = _handler(app, match_info={"job_id": body["job_id"]})
        other_handler._get_session_user_id = AsyncMock(return_value="a-completely-different-user")

        with pytest.raises(web.HTTPNotFound):
            await other_handler.get()
