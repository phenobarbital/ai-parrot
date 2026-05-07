"""Test that string-keyed extension types are registrable and discoverable."""

from __future__ import annotations

import importlib
import sys

import pytest
from aiohttp import web

from parrot_formdesigner.api.controls import handle_form_controls
from parrot_formdesigner.controls import get_controls, register_field_control
from parrot_formdesigner.controls.registry import _REGISTRY


@pytest.fixture(autouse=True)
def _seed_builtin():
    _REGISTRY.clear()
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    yield
    _REGISTRY.clear()


def test_extension_with_string_type_in_registry():
    """``register_field_control('rich_text', ...)`` adds a new entry."""
    pre_count = len(get_controls())
    register_field_control(
        "rich_text",
        label="Rich Text",
        description="Rich text editor",
        category="advanced",
        icon="rich-text",
        snippet={"type": "string", "format": "rich-text"},
        render_hint="rich",
        supports_constraints=True,
    )
    controls = get_controls()
    assert len(controls) == pre_count + 1
    types = {c.type for c in controls}
    assert "rich_text" in types


async def test_extension_visible_in_http_endpoint(aiohttp_client):
    register_field_control(
        "rich_text",
        label="Rich Text",
        description="Rich text editor",
        category="advanced",
        icon="rich-text",
        snippet={"type": "string", "format": "rich-text"},
        render_hint="rich",
        supports_constraints=True,
    )

    app = web.Application()
    app.router.add_get("/api/v1/form-controls", handle_form_controls)
    client = await aiohttp_client(app)
    resp = await client.get("/api/v1/form-controls")
    assert resp.status == 200
    body = await resp.json()
    types = {c["type"] for c in body["controls"]}
    assert "rich_text" in types
    rich_entry = next(c for c in body["controls"] if c["type"] == "rich_text")
    assert rich_entry["label"] == "Rich Text"
    assert rich_entry["category"] == "advanced"
