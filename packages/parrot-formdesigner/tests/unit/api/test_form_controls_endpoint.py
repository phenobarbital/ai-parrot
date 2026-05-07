"""Unit tests for the ``GET /api/v1/form-controls`` endpoint."""

from __future__ import annotations

import pytest
from aiohttp import web

from parrot_formdesigner.api.controls import handle_form_controls
from parrot_formdesigner.controls.registry import _REGISTRY
from parrot_formdesigner.core.types import FieldType


@pytest.fixture(autouse=True)
def _seed_builtin():
    """Re-seed the registry with the builtin set."""
    import importlib
    import sys

    _REGISTRY.clear()
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    yield
    _REGISTRY.clear()


async def test_form_controls_payload_shape(aiohttp_client):
    app = web.Application()
    app.router.add_get("/api/v1/form-controls", handle_form_controls)
    client = await aiohttp_client(app)
    resp = await client.get("/api/v1/form-controls")
    assert resp.status == 200
    body = await resp.json()
    assert "controls" in body
    assert isinstance(body["controls"], list)
    assert len(body["controls"]) == len(FieldType)
    expected_keys = {
        "type", "label", "description", "category", "icon",
        "snippet", "render_hint", "supports_constraints", "is_container",
    }
    for entry in body["controls"]:
        assert set(entry.keys()) == expected_keys
