"""Integration test: ``GET /api/v1/form-controls`` contract.

Boots an aiohttp app with the form-controls handler mounted, calls the
endpoint, validates the response against the JSON Schema fixture, and
asserts the builtin set covers every ``FieldType`` value.
"""

from __future__ import annotations

import importlib
import json
import pathlib
import sys

import jsonschema
import pytest
from aiohttp import web

from parrot_formdesigner.api.controls import handle_form_controls
from parrot_formdesigner.controls.registry import _REGISTRY
from parrot_formdesigner.core.types import FieldType


SCHEMA_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "fixtures"
    / "form_controls_response_schema.json"
)


@pytest.fixture(autouse=True)
def _seed_builtin():
    _REGISTRY.clear()
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    yield
    _REGISTRY.clear()


async def test_endpoint_returns_envelope(aiohttp_client):
    app = web.Application()
    app.router.add_get("/api/v1/form-controls", handle_form_controls)
    client = await aiohttp_client(app)
    resp = await client.get("/api/v1/form-controls")
    assert resp.status == 200
    body = await resp.json()
    assert "controls" in body
    assert isinstance(body["controls"], list)


async def test_endpoint_matches_schema(aiohttp_client):
    app = web.Application()
    app.router.add_get("/api/v1/form-controls", handle_form_controls)
    client = await aiohttp_client(app)
    resp = await client.get("/api/v1/form-controls")
    body = await resp.json()
    schema = json.loads(SCHEMA_PATH.read_text())
    jsonschema.validate(body, schema)


async def test_endpoint_covers_every_field_type(aiohttp_client):
    app = web.Application()
    app.router.add_get("/api/v1/form-controls", handle_form_controls)
    client = await aiohttp_client(app)
    resp = await client.get("/api/v1/form-controls")
    body = await resp.json()
    types = {c["type"] for c in body["controls"]}
    assert types == {ft.value for ft in FieldType}
    assert len(body["controls"]) == len(FieldType)


async def test_each_entry_has_full_metadata(aiohttp_client):
    app = web.Application()
    app.router.add_get("/api/v1/form-controls", handle_form_controls)
    client = await aiohttp_client(app)
    resp = await client.get("/api/v1/form-controls")
    body = await resp.json()
    expected_keys = {
        "type", "label", "description", "category", "icon",
        "snippet", "render_hint", "supports_constraints", "is_container",
    }
    for entry in body["controls"]:
        assert set(entry.keys()) == expected_keys


def test_schema_fixture_is_valid_json_schema():
    """The fixture itself is a well-formed JSON Schema (draft-2020-12)."""
    schema = json.loads(SCHEMA_PATH.read_text())
    # Use the meta-schema to validate it.
    jsonschema.Draft202012Validator.check_schema(schema)
