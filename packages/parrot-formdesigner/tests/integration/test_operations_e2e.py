"""Integration tests for ``PATCH /api/v1/t/navigator/forms/{form_uid}/operations``.

End-to-end via aiohttp test client. Asserts:
- Successful round-trip bumps the version and persists the new shape.
- Atomic failure leaves the registry form untouched.
- Duplicate field_id is rejected with an op-level error.
- Circular ``depends_on`` introduced by ops triggers schema-level 422.
- ``If-Match`` honours optimistic concurrency.

FEAT-393: operations address fields/sections by ``field_uid``/``section_uid``
(``uuid.UUID``), not ``field_id``/``section_id``.
"""

from __future__ import annotations

import uuid

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


async def _tenant_wrapped_operations(request: web.Request) -> web.Response:
    """Stash the URL-declared tenant, mirroring what @requires_tenant does
    (FEAT-421) — these tests exercise operations, not tenant enforcement."""
    request["tenant"] = request.match_info["tenant"]
    return await handle_operations(request)


async def _make_client(aiohttp_client, registry: FormRegistry):
    app = web.Application()
    app["form_registry"] = registry
    app.router.add_patch(
        "/api/v1/t/{tenant}/forms/{form_uid}/operations",
        _tenant_wrapped_operations,
    )
    return await aiohttp_client(app)


async def test_successful_round_trip_bumps_version(aiohttp_client, sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.patch(
        f"/api/v1/t/navigator/forms/{sample_form.form_uid}/operations",
        json={
            "operations": [
                {
                    "op": "add_section",
                    "section": {"section_id": "s2", "fields": []},
                },
            ]
        },
    )
    assert resp.status == 200
    body = await resp.json()
    new_section_uid = next(
        s["section_uid"] for s in body["form"]["sections"] if s["section_id"] == "s2"
    )

    resp2 = await client.patch(
        f"/api/v1/t/navigator/forms/{sample_form.form_uid}/operations",
        json={
            "operations": [
                {
                    "op": "add_field",
                    "section_uid": new_section_uid,
                    "field": {
                        "field_id": "email",
                        "field_type": "email",
                        "label": {"en": "Email"},
                    },
                },
            ]
        },
    )
    assert resp2.status == 200
    body2 = await resp2.json()
    assert body2["form"]["version"] == "1.2"
    assert {s["section_id"] for s in body2["form"]["sections"]} == {"s1", "s2"}

    # Persisted
    again = await registry.get(sample_form.form_uid)
    assert again is not None and again.version == "1.2"
    assert any(s.section_id == "s2" for s in again.sections)


async def test_atomic_failure_no_change(aiohttp_client, sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.patch(
        f"/api/v1/t/navigator/forms/{sample_form.form_uid}/operations",
        json={
            "operations": [
                {
                    "op": "add_section",
                    "section": {"section_id": "x", "fields": []},
                },
                {
                    "op": "remove_field",
                    "section_uid": str(uuid.uuid4()),
                    "field_uid": str(uuid.uuid4()),
                },
            ]
        },
    )
    assert resp.status == 422
    body = await resp.json()
    assert body["errors"][0]["index"] == 1

    again = await registry.get(sample_form.form_uid)
    assert len(again.sections) == len(sample_form.sections)
    assert again.version == "1.0"


async def test_duplicate_field_rejected(aiohttp_client, sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.patch(
        f"/api/v1/t/navigator/forms/{sample_form.form_uid}/operations",
        json={
            "operations": [
                {
                    "op": "add_field",
                    "section_uid": str(sample_form.sections[0].section_uid),
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

    name_field_uid = str(sample_form.sections[0].fields[0].field_uid)

    # Update name to depend on itself.
    resp = await client.patch(
        f"/api/v1/t/navigator/forms/{sample_form.form_uid}/operations",
        json={
            "operations": [
                {
                    "op": "update_field",
                    "section_uid": str(sample_form.sections[0].section_uid),
                    "field_uid": name_field_uid,
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
        f"/api/v1/t/navigator/forms/{sample_form.form_uid}/operations",
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
        f"/api/v1/t/navigator/forms/{sample_form.form_uid}/operations",
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
        "/api/v1/t/navigator/forms/00000000-0000-0000-0000-000000000000/operations",
        json={"operations": []},
    )
    assert resp.status == 404


async def test_invalid_envelope_422(aiohttp_client, sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.patch(
        f"/api/v1/t/navigator/forms/{sample_form.form_uid}/operations",
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
        f"/api/v1/t/navigator/forms/{form.form_uid}/operations",
        json={
            "operations": [
                {
                    "op": "move_field",
                    "from": {
                        "section_uid": str(form.sections[0].section_uid),
                        "field_uid": str(form.sections[0].fields[0].field_uid),
                    },
                    "to": {"section_uid": str(form.sections[1].section_uid), "position": 0},
                }
            ]
        },
    )
    assert resp.status == 200
    body = await resp.json()
    sections = body["form"]["sections"]
    assert sections[0]["fields"] == []
    assert sections[1]["fields"][0]["field_id"] == "x"


async def test_move_field_malformed_uuid_returns_422_not_500(aiohttp_client, sample_form):
    """FEAT-393 code review regression: a malformed UUID string in
    move_field's from/to dict must return 422 (OperationError), not an
    uncaught ValueError -> 500 — the uuid.UUID(...) parses in
    _apply_move_field were previously unguarded."""
    registry = FormRegistry()
    await registry.register(sample_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.patch(
        f"/api/v1/t/navigator/forms/{sample_form.form_uid}/operations",
        json={
            "operations": [
                {
                    "op": "move_field",
                    "from": {
                        "section_uid": "not-a-uuid",
                        "field_uid": str(sample_form.sections[0].fields[0].field_uid),
                    },
                    "to": {"section_uid": str(sample_form.sections[0].section_uid), "position": 0},
                }
            ]
        },
    )
    assert resp.status == 422
    body = await resp.json()
    assert body["errors"][0]["op"] == "move_field"


async def test_duplicate_field_malformed_uuid_returns_422_not_500(aiohttp_client, sample_form):
    """FEAT-393 code review regression: same malformed-UUID guard for
    duplicate_field's from dict."""
    registry = FormRegistry()
    await registry.register(sample_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.patch(
        f"/api/v1/t/navigator/forms/{sample_form.form_uid}/operations",
        json={
            "operations": [
                {
                    "op": "duplicate_field",
                    "from": {"section_uid": "not-a-uuid", "field_uid": "also-not-a-uuid"},
                    "as_field_id": "name_2",
                }
            ]
        },
    )
    assert resp.status == 422
    body = await resp.json()
    assert body["errors"][0]["op"] == "duplicate_field"


async def test_handle_operations_reresolves_rules(aiohttp_client):
    """Renaming a field's field_id via update_field keeps a depends_on
    rule (authored against the OLD field_id) working, because
    handle_operations re-runs resolve_rule_references() post-apply
    (FEAT-393) — the rule was already resolved to field_uid when the form
    was first built, so it is unaffected by the rename either way."""
    trigger = FormField(field_id="trigger", field_type=FieldType.TEXT, label="Trigger")
    form = FormSchema(
        form_id="resolve-test",
        title={"en": "R"},
        tenant="navigator",
        sections=[FormSection(section_id="s1", fields=[trigger])],
    )
    registry = FormRegistry()
    await registry.register(form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.patch(
        f"/api/v1/t/navigator/forms/{form.form_uid}/operations",
        json={
            "operations": [
                {
                    "op": "update_field",
                    "section_uid": str(form.sections[0].section_uid),
                    "field_uid": str(trigger.field_uid),
                    "patch": {"field_id": "trigger_renamed"},
                }
            ]
        },
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["form"]["sections"][0]["fields"][0]["field_id"] == "trigger_renamed"
    assert body["form"]["sections"][0]["fields"][0]["field_uid"] == str(trigger.field_uid)
