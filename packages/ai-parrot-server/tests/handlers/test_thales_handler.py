"""Unit tests for `parrot.handlers.thales` (FEAT-425 TASK-2232).

Mirrors `test_mcp_helper_handler.py`'s style: mock the handler's `self`
(request/json_response/error) directly rather than spinning up a full
aiohttp app with real auth middleware. No network, no real ThalesRunner.
"""

from __future__ import annotations

import asyncio
import json as jsonlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from parrot.handlers.thales import (
    RunRegistry,
    ThalesArtifactsHandler,
    ThalesRunHandler,
    ThalesStatusHandler,
    get_run_registry,
    setup_thales_routes,
)


def _make_mock_request(method: str = "GET", match_info: dict | None = None, body: dict | None = None) -> MagicMock:
    req = MagicMock()
    req.method = method
    req.match_info = match_info or {}
    req.json = AsyncMock(return_value=body or {})
    return req


def _make_handler(request: MagicMock) -> MagicMock:
    handler = MagicMock()
    handler.request = request
    handler.json_response = lambda data, status=200: web.json_response(data, status=status)
    handler.error = lambda msg, status=400, **kw: web.json_response({"error": str(msg)}, status=status)
    return handler


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test gets a clean module-level registry."""
    registry = get_run_registry()
    registry._runs.clear()
    yield
    registry._runs.clear()


class TestSetupThalesRoutes:
    def test_registers_routes(self):
        app = web.Application()
        setup_thales_routes(app)
        routes = [r.resource.canonical for r in app.router.routes() if hasattr(r, "resource")]
        joined = " ".join(routes)
        assert "/api/v1/thales" in joined
        assert "/api/v1/thales/{run_id}" in joined
        assert "/api/v1/thales/{run_id}/artifacts" in joined


class TestThalesRunHandlerPost:
    @pytest.mark.asyncio
    async def test_missing_thesis_returns_400(self):
        request = _make_mock_request(body={})
        handler = _make_handler(request)
        response = await ThalesRunHandler.post(handler)
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_rejects_small_num_decks(self):
        request = _make_mock_request(body={"thesis": "t", "num_decks": 5})
        handler = _make_handler(request)
        response = await ThalesRunHandler.post(handler)
        assert response.status == 400
        body = jsonlib.loads(response.body)
        assert "10" in body["error"]

    @pytest.mark.asyncio
    async def test_handler_post_poll(self):
        """POST -> run_id; poll GET transitions pending -> running -> completed."""
        request = _make_mock_request(body={"thesis": "t"})
        handler = _make_handler(request)

        fake_result = MagicMock()
        fake_result.model_dump.return_value = {"thesis": "t"}

        with patch("parrot.handlers.thales.ThalesRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner.add_progress_listener = MagicMock()

            async def fake_run():
                # Simulate progress before completing.
                listener = mock_runner.add_progress_listener.call_args[0][0]
                listener("flow_started", "start", {})
                return fake_result

            mock_runner.run = fake_run
            mock_runner_cls.return_value = mock_runner

            response = await ThalesRunHandler.post(handler)
            assert response.status == 202
            payload = jsonlib.loads(response.body)
            run_id = payload["run_id"]

            # Let the background task run to completion.
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        status_request = _make_mock_request(match_info={"run_id": run_id})
        status_handler = _make_handler(status_request)
        status_response = await ThalesStatusHandler.get(status_handler)
        assert status_response.status == 200
        status_body = jsonlib.loads(status_response.body)
        assert status_body["status"] == "completed"
        assert status_body["result"] == {"thesis": "t"}


class TestThalesStatusHandlerGet:
    @pytest.mark.asyncio
    async def test_unknown_run_id_404(self):
        request = _make_mock_request(match_info={"run_id": "ghost"})
        handler = _make_handler(request)
        response = await ThalesStatusHandler.get(handler)
        assert response.status == 404

    @pytest.mark.asyncio
    async def test_failed_run_returns_200_with_error(self):
        registry = get_run_registry()
        fake_task = MagicMock()
        registry.attach("run-failed", runner=MagicMock(), task=fake_task)
        registry.fail("run-failed", RuntimeError("boom"))

        request = _make_mock_request(match_info={"run_id": "run-failed"})
        handler = _make_handler(request)
        response = await ThalesStatusHandler.get(handler)
        assert response.status == 200
        body = jsonlib.loads(response.body)
        assert body["status"] == "failed"
        assert "boom" in body["error"]


class TestThalesArtifactsHandlerGet:
    @pytest.mark.asyncio
    async def test_unknown_run_id_404(self):
        request = _make_mock_request(match_info={"run_id": "ghost"})
        handler = _make_handler(request)
        response = await ThalesArtifactsHandler.get(handler)
        assert response.status == 404

    @pytest.mark.asyncio
    async def test_artifacts_before_completion_empty(self):
        registry = get_run_registry()
        registry.attach("run-pending", runner=MagicMock(), task=MagicMock())

        request = _make_mock_request(match_info={"run_id": "run-pending"})
        handler = _make_handler(request)
        response = await ThalesArtifactsHandler.get(handler)
        assert response.status == 200
        body = jsonlib.loads(response.body)
        assert body["artifacts"] == []

    @pytest.mark.asyncio
    async def test_artifacts_after_completion(self):
        from parrot.flows.thales.models import ArtifactRef, Bibliography, ThalesResult

        result = ThalesResult(
            thesis="t",
            decks=[],
            slides=[ArtifactRef(kind="slide_html", artifact_id="s1", url="https://x/s1")],
            bibliography=Bibliography(),
            executive_summary="summary",
            final_document=ArtifactRef(kind="final_html", artifact_id="d1", url="https://x/d1"),
            final_pdf=None,
        )
        registry = get_run_registry()
        registry.attach("run-done", runner=MagicMock(), task=MagicMock())
        registry.complete("run-done", result)

        request = _make_mock_request(match_info={"run_id": "run-done"})
        handler = _make_handler(request)
        response = await ThalesArtifactsHandler.get(handler)
        assert response.status == 200
        body = jsonlib.loads(response.body)
        kinds = {a["kind"] for a in body["artifacts"]}
        assert kinds == {"slide_html", "final_html"}


class TestRunRegistry:
    def test_record_event_marks_running(self):
        registry = RunRegistry()
        registry.attach("r1", runner=MagicMock(), task=MagicMock())
        registry.record_event("r1", "flow_started", "start", {})
        assert registry.get("r1").status == "running"

    def test_unknown_run_id_events_are_noop(self):
        registry = RunRegistry()
        registry.record_event("ghost", "flow_started", "start", {})  # must not raise
        assert registry.get("ghost") is None
