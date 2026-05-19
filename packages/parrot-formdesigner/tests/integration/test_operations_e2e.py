"""Integration tests for ``PATCH /api/v1/forms/{id}/operations``.

End-to-end via aiohttp test client. Asserts:
- Successful round-trip bumps the version and persists the new shape.
- Atomic failure leaves the registry form untouched.
- Duplicate field_id is rejected with an op-level error.
- Circular ``depends_on`` introduced by ops triggers schema-level 422.
- ``If-Match`` honours optimistic concurrency.
"""

from __future__ import annotations

import pytest
from aiohttp import web

from parrot_formdesigner.api.operations import handle_operations
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry


@pytest.fixture
def sample_form() -> FormSchema:
    return FormSchema(
        form_id="ops-form",
        version="1.0",
        title={"en": "Ops Form"},
        tenant="navigator",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label={"en": "N"},
                    ),
                ],
            )
        ],
    )


async def _make_client(aiohttp_client, registry: FormRegistry):
    app = web.Application()
    app["form_registry"] = registry
    app.router.add_patch(
        "/api/v1/forms/{form_id}/operations", handle_operations
    )
    return await aiohttp_client(app)


async def test_successful_round_trip_bumps_version(aiohttp_client, sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.patch(
        f"/api/v1/forms/{sample_form.form_id}/operations",
        json={
            "operations": [
                {
                    "op": "add_section",
                    "section": {"section_id": "s2", "fields": []},
                },
                {
                    "op": "add_field",
                    "section_id": "s2",
                    "field": {
                        "field_id": "email",
                        "field_type": "email",
                        "label": {"en": "Email"},
                    },
                },
            ]
        },
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["form"]["version"] == "1.1"
    assert {s["section_id"] for s in body["form"]["sections"]} == {"s1", "s2"}

    # Persisted
    again = await registry.get(sample_form.form_id)
    assert again is not None and again.version == "1.1"
    assert any(s.section_id == "s2" for s in again.sections)


async def test_atomic_failure_no_change(aiohttp_client, sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.patch(
        f"/api/v1/forms/{sample_form.form_id}/operations",
        json={
            "operations": [
                {
                    "op": "add_section",
                    "section": {"section_id": "x", "fields": []},
                },
                {
                    "op": "remove_field",
                    "section_id": "MISSING",
                    "field_id": "no",
                },
            ]
        },
    )
    assert resp.status == 422
    body = await resp.json()
    assert body["errors"][0]["index"] == 1

    again = await registry.get(sample_form.form_id)
    assert len(again.sections) == len(sample_form.sections)
    assert again.version == "1.0"


async def test_duplicate_field_rejected(aiohttp_client, sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.patch(
        f"/api/v1/forms/{sample_form.form_id}/operations",
        json={
            "operations": [
                {
                    "op": "add_field",
                    "section_id": "s1",
                    "field": {
                        "field_id": "name",  # duplicate
                        "field_type": "text",
                        "label": {"en": "Dup"},
                    },
                }
            ]
        },
    )
    assert resp.status == 422
    body = await resp.json()
    assert body["errors"][0]["index"] == 0
    assert body["errors"][0]["op"] == "add_field"


async def test_circular_depends_on_rejected(aiohttp_client, sample_form):
    """A self-referential dependency must trigger the post-apply check_schema()."""
    registry = FormRegistry()
    await registry.register(sample_form)
    client = await _make_client(aiohttp_client, registry)

    # Update name to depend on itself.
    resp = await client.patch(
        f"/api/v1/forms/{sample_form.form_id}/operations",
        json={
            "operations": [
                {
                    "op": "update_field",
                    "section_id": "s1",
                    "field_id": "name",
                    "patch": {
                        "depends_on": {
                            "conditions": [
                                {
                                    "field_id": "name",
                                    "operator": "eq",
                                    "value": "loop",
                                }
                            ]
                        }
                    },
                }
            ]
        },
    )
    assert resp.status == 422
    body = await resp.json()
    # Schema errors carry index=null
    assert any(e["index"] is None for e in body["errors"])


async def test_if_match_mismatch_412(aiohttp_client, sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.patch(
        f"/api/v1/forms/{sample_form.form_id}/operations",
        headers={"If-Match": "0.9"},
        json={"operations": []},
    )
    assert resp.status == 412
    body = await resp.json()
    assert body["detail"] == "version mismatch"
    assert body["current"] == "1.0"


async def test_if_match_correct_version_succeeds(aiohttp_client, sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.patch(
        f"/api/v1/forms/{sample_form.form_id}/operations",
        headers={"If-Match": "1.0"},
        json={
            "operations": [
                {
                    "op": "add_section",
                    "section": {"section_id": "s2", "fields": []},
                }
            ]
        },
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["form"]["version"] == "1.1"


async def test_unknown_form_404(aiohttp_client):
    registry = FormRegistry()
    client = await _make_client(aiohttp_client, registry)

    resp = await client.patch(
        "/api/v1/forms/missing/operations",
        json={"operations": []},
    )
    assert resp.status == 404


async def test_invalid_envelope_422(aiohttp_client, sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.patch(
        f"/api/v1/forms/{sample_form.form_id}/operations",
        json={
            "operations": [
                {"op": "unknown_op_type", "foo": "bar"}
            ]
        },
    )
    assert resp.status == 422


async def test_move_field_round_trip(aiohttp_client):
    form = FormSchema(
        form_id="move-test",
        title={"en": "M"},
        tenant="navigator",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="x",
                        field_type=FieldType.TEXT,
                        label={"en": "X"},
                    )
                ],
            ),
            FormSection(section_id="s2", fields=[]),
        ],
    )
    registry = FormRegistry()
    await registry.register(form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.patch(
        f"/api/v1/forms/{form.form_id}/operations",
        json={
            "operations": [
                {
                    "op": "move_field",
                    "from": {"section_id": "s1", "field_id": "x"},
                    "to": {"section_id": "s2", "position": 0},
                }
            ]
        },
    )
    assert resp.status == 200
    body = await resp.json()
    sections = body["form"]["sections"]
    assert sections[0]["fields"] == []
    assert sections[1]["fields"][0]["field_id"] == "x"
