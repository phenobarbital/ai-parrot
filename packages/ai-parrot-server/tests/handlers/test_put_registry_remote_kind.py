"""ChatbotHandler._put_registry registers remote (squawk/a2a) agents without a local factory."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from parrot.handlers.bots import ChatbotHandler
from parrot.registry import AgentKind, AgentRegistry


@pytest.mark.asyncio
async def test_put_registry_registers_remote_agent(tmp_path) -> None:
    """A squawk payload writes its YAML and lands in the registry as a remote entry."""
    registry = AgentRegistry(agents_dir=tmp_path)
    responses: list[tuple[dict, int]] = []
    fake = SimpleNamespace(
        _registry=registry,
        _manager=None,
        logger=logging.getLogger("test"),
        json_response=lambda body, status=200: responses.append((body, status)) or body,
        error=lambda response, status: responses.append((response, status)) or response,
    )
    payload = {"name": "hr", "kind": "squawk", "endpoint": "squawk://hr:7470", "contract_categories": ["hr.reports"]}

    await ChatbotHandler._put_registry(fake, payload)

    body, status = responses[-1]
    assert status == 201 and body["kind"] == "squawk"
    meta = registry.get_metadata("hr")
    assert meta.kind == AgentKind.SQUAWK and meta.endpoint == "squawk://hr:7470"


@pytest.mark.asyncio
async def test_put_registry_reports_failed_remote_registration(tmp_path) -> None:
    """If register_remote fails the handler returns 500, never a false 201."""
    registry = AgentRegistry(agents_dir=tmp_path)

    def boom(_config):
        raise RuntimeError("index unavailable")

    registry.register_remote = boom  # type: ignore[method-assign]
    responses: list[tuple[dict, int]] = []
    fake = SimpleNamespace(
        _registry=registry,
        _manager=None,
        logger=logging.getLogger("test"),
        json_response=lambda body, status=200: responses.append((body, status)) or body,
        error=lambda response, status: responses.append((response, status)) or response,
    )
    payload = {"name": "hr", "kind": "squawk", "endpoint": "squawk://hr:7470"}

    await ChatbotHandler._put_registry(fake, payload)

    assert responses[-1][1] == 500
