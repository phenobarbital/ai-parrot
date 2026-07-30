"""Unit tests for the no-LLM branch of ``POST /api/v1/forms``.

``FormAPIHandler.create_form`` is dual-mode: a body carrying ``prompt``
goes to ``CreateFormTool`` (LLM), anything else builds the ``FormSchema``
directly. These tests cover the manual branch — the one that backs a
"New form" button in the form builder — plus the full
create-blank → add-controls-on-the-canvas round trip via
``PATCH /forms/{form_id}/operations``.

All tests use mocked requests against a real ``FormRegistry``; no HTTP
server and no LLM client are involved.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.api.operations import handle_operations
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.registry import FormRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    *,
    raw_body: str | None = None,
    body: dict | list | None = None,
    match_info: dict | None = None,
    tenant: str = "t1",
    app: dict | None = None,
) -> MagicMock:
    """Build a mocked aiohttp request for the create/operations handlers.

    Args:
        raw_body: Exact payload string. Takes precedence over ``body``; use
            ``""`` to simulate a bodyless POST.
        body: Object to JSON-encode as the payload.
        match_info: Path parameters (e.g. ``{"form_id": "x"}``).
        tenant: Program slug exposed through the mocked session.
        app: Mapping used for ``request.app`` (needed by handle_operations).

    Returns:
        A ``MagicMock`` shaped like ``web.Request``.
    """
    if raw_body is None:
        raw_body = "" if body is None else json.dumps(body)

    req = MagicMock(spec=web.Request)
    req.method = "POST"
    req.match_info = match_info or {}
    req.session = {"session": {"programs": [tenant]}}
    req.headers = {}
    req.text = AsyncMock(return_value=raw_body)

    async def _json():
        return json.loads(raw_body)

    req.json = _json
    req.app = app if app is not None else {}

    user = MagicMock()
    user.id = "test-user"
    user.organizations = []
    req.user = user
    return req


@pytest.fixture
def registry() -> FormRegistry:
    """Empty in-memory registry sealed to the ``t1`` tenant."""
    return FormRegistry(require_tenant=False, default_tenant="t1")


@pytest.fixture
def handler(registry: FormRegistry) -> FormAPIHandler:
    """Handler with NO LLM client — the manual path must not need one."""
    return FormAPIHandler(registry=registry)


async def _create(handler: FormAPIHandler, **kwargs) -> tuple[int, dict]:
    """Call ``create_form`` and return ``(status, decoded body)``."""
    resp = await handler.create_form(_make_request(**kwargs))
    return resp.status, json.loads(resp.body.decode())


# ---------------------------------------------------------------------------
# Blank creation
# ---------------------------------------------------------------------------


async def test_empty_body_creates_blank_form(handler: FormAPIHandler) -> None:
    """A bodyless POST is a valid "give me a blank form" request."""
    status, form = await _create(handler)

    assert status == 201
    assert form["form_id"] == "untitled-form"
    assert form["title"] == "Untitled Form"
    assert form["version"] == "1.0"
    assert form["published_version"] is None
    assert form["tenant"] == "t1"
    # One empty section so the canvas has an add_field target.
    assert len(form["sections"]) == 1
    assert form["sections"][0]["section_id"] == "section_1"
    assert form["sections"][0]["fields"] == []


async def test_blank_form_is_registered(
    handler: FormAPIHandler, registry: FormRegistry
) -> None:
    """The new form is retrievable from the registry under the session tenant."""
    _, form = await _create(handler, body={"title": "Store Visit"})

    stored = await registry.get(form["form_id"], tenant="t1")
    assert stored is not None
    assert stored.form_id == "store-visit"


async def test_no_llm_client_required(handler: FormAPIHandler) -> None:
    """The manual path never hits the 503 LLM guard."""
    assert handler._create_tool.client is None
    status, _ = await _create(handler, body={"title": "No LLM Needed"})
    assert status == 201


async def test_title_derives_form_id(handler: FormAPIHandler) -> None:
    status, form = await _create(handler, body={"title": "¡Encuesta Cliente 2026!"})
    assert status == 201
    assert form["form_id"] == "encuesta-cliente-2026"


async def test_localized_title_derives_form_id(handler: FormAPIHandler) -> None:
    status, form = await _create(
        handler, body={"title": {"en": "Daily Report", "es": "Reporte Diario"}}
    )
    assert status == 201
    assert form["form_id"] == "daily-report"
    assert form["title"] == {"en": "Daily Report", "es": "Reporte Diario"}


async def test_explicit_form_id_honoured(handler: FormAPIHandler) -> None:
    status, form = await _create(
        handler, body={"form_id": "my-custom-id", "title": "Whatever"}
    )
    assert status == 201
    assert form["form_id"] == "my-custom-id"


async def test_explicit_sections_honoured(handler: FormAPIHandler) -> None:
    """``sections: []`` means "no sections" — the default is not applied."""
    status, form = await _create(handler, body={"sections": []})
    assert status == 201
    assert form["sections"] == []


async def test_seeded_sections_honoured(handler: FormAPIHandler) -> None:
    status, form = await _create(
        handler,
        body={
            "title": "Two Steps",
            "sections": [
                {"section_id": "step1", "title": "Step 1", "fields": []},
                {"section_id": "step2", "fields": []},
            ],
        },
    )
    assert status == 201
    assert [s["section_id"] for s in form["sections"]] == ["step1", "step2"]


async def test_extra_schema_fields_pass_through(handler: FormAPIHandler) -> None:
    status, form = await _create(
        handler,
        body={
            "title": "Rich Blank",
            "description": "Created by the builder",
            "form_type": "survey",
            "cancel_allowed": False,
            "meta": {"builder": "canvas"},
        },
    )
    assert status == 201
    assert form["description"] == "Created by the builder"
    assert form["form_type"] == "survey"
    assert form["cancel_allowed"] is False
    assert form["meta"] == {"builder": "canvas"}


# ---------------------------------------------------------------------------
# Reserved / controlled keys
# ---------------------------------------------------------------------------


async def test_version_and_published_version_are_controlled(
    handler: FormAPIHandler,
) -> None:
    """A client cannot forge version state at creation time."""
    status, form = await _create(
        handler,
        body={"title": "Forged", "version": "9.9", "published_version": "9.9"},
    )
    assert status == 201
    assert form["version"] == "1.0"
    assert form["published_version"] is None


async def test_body_tenant_cannot_override_session(handler: FormAPIHandler) -> None:
    """Tenant comes from the session — never from the body."""
    status, form = await _create(
        handler, body={"title": "Cross Tenant", "tenant": "other-tenant"}
    )
    assert status == 201
    assert form["tenant"] == "t1"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


async def test_duplicate_explicit_id_conflicts(handler: FormAPIHandler) -> None:
    body = {"form_id": "dup", "title": "First"}
    assert (await _create(handler, body=body))[0] == 201

    status, payload = await _create(handler, body=body)
    assert status == 409
    assert "already exists" in payload["error"]


async def test_duplicate_derived_id_gets_suffix(
    handler: FormAPIHandler, registry: FormRegistry
) -> None:
    """Clicking "New" twice must not 409 — the derived slug is disambiguated."""
    _, first = await _create(handler, body={"title": "Same Title"})
    status, second = await _create(handler, body={"title": "Same Title"})

    assert status == 201
    assert first["form_id"] == "same-title"
    assert second["form_id"] != first["form_id"]
    assert second["form_id"].startswith("same-title-")
    assert await registry.get(first["form_id"], tenant="t1") is not None
    assert await registry.get(second["form_id"], tenant="t1") is not None


@pytest.mark.parametrize(
    "bad_id",
    [
        "../etc/passwd",
        "has space",
        "with/slash",
        "",
        "a" * 65,
        "-leading-dash",
        "trailing-newline\n",
        "embedded\nnewline",
    ],
)
async def test_invalid_form_id_rejected(
    handler: FormAPIHandler, bad_id: str
) -> None:
    status, payload = await _create(handler, body={"form_id": bad_id})
    assert status == 400
    assert "Invalid form_id" in payload["error"]


async def test_malformed_json_rejected(handler: FormAPIHandler) -> None:
    status, payload = await _create(handler, raw_body="{not json")
    assert status == 400
    assert payload["error"] == "Invalid JSON body"


async def test_non_object_body_rejected(handler: FormAPIHandler) -> None:
    status, payload = await _create(handler, body=["nope"])
    assert status == 400
    assert "JSON object" in payload["error"]


async def test_invalid_schema_returns_422(handler: FormAPIHandler) -> None:
    status, payload = await _create(
        handler, body={"title": "Bad", "sections": [{"fields": []}]}
    )
    assert status == 422
    assert "errors" in payload


# ---------------------------------------------------------------------------
# LLM branch regression
# ---------------------------------------------------------------------------


async def test_prompt_without_client_still_503(handler: FormAPIHandler) -> None:
    """Sending ``prompt`` with no LLM configured keeps the pre-existing 503."""
    status, payload = await _create(handler, body={"prompt": "a contact form"})
    assert status == 503
    assert "No LLM client" in payload["error"]


@pytest.mark.parametrize("empty_prompt", ["", None, 0, []])
async def test_empty_prompt_is_not_a_blank_form_request(
    handler: FormAPIHandler, registry: FormRegistry, empty_prompt: object
) -> None:
    """Mode selection is by key presence: a falsy ``prompt`` is still LLM mode.

    Sending ``prompt`` at all means the caller wanted the LLM path, so an
    empty value must keep erroring instead of silently creating a blank form.
    """
    status, _ = await _create(handler, body={"prompt": empty_prompt})
    assert status in (400, 503)
    assert await registry.list_form_ids(tenant="t1") == []


async def test_empty_prompt_with_client_is_400(registry: FormRegistry) -> None:
    """With an LLM client configured, an empty prompt is the historical 400."""
    handler = FormAPIHandler(registry=registry, client=MagicMock())
    status, payload = await _create(handler, body={"prompt": ""})
    assert status == 400
    assert payload["error"] == "prompt is required"


# ---------------------------------------------------------------------------
# Storage-aware duplicate detection and race handling
# ---------------------------------------------------------------------------


async def test_persisted_form_not_in_memory_conflicts(
    registry: FormRegistry,
) -> None:
    """A persisted form under a non-hydrated tenant must not be overwritten.

    ``registry.get()`` is memory-only and ``PostgresFormStorage.save()``
    upserts, so a memory-only duplicate check would let creation silently
    replace an existing tenant form.
    """
    storage = MagicMock()
    storage.load = AsyncMock(
        return_value=FormSchema(
            form_id="already-persisted",
            title="Persisted",
            sections=[],
            tenant="t1",
        )
    )
    storage.save = AsyncMock()
    registry.set_storage(storage)

    handler = FormAPIHandler(registry=registry)
    status, payload = await _create(
        handler, body={"form_id": "already-persisted", "title": "New One"}
    )

    assert status == 409
    assert "already exists" in payload["error"]
    storage.save.assert_not_awaited()


async def test_derived_id_avoids_persisted_collision(
    registry: FormRegistry,
) -> None:
    """A derived slug colliding with a persisted form gets a suffix, not a 409."""
    storage = MagicMock()
    storage.load = AsyncMock(
        return_value=FormSchema(
            form_id="daily-report", title="Old", sections=[], tenant="t1"
        )
    )
    storage.save = AsyncMock()
    registry.set_storage(storage)

    handler = FormAPIHandler(registry=registry)
    status, form = await _create(handler, body={"title": "Daily Report"})

    assert status == 201
    assert form["form_id"].startswith("daily-report-")
    assert form["form_id"] != "daily-report"


async def test_storage_probe_failure_refuses_to_overwrite(
    registry: FormRegistry,
) -> None:
    """An unreachable storage backend must not be read as "id is free"."""
    storage = MagicMock()
    storage.load = AsyncMock(side_effect=RuntimeError("db down"))
    storage.save = AsyncMock()
    registry.set_storage(storage)

    handler = FormAPIHandler(registry=registry)
    status, _ = await _create(handler, body={"form_id": "unknown", "title": "X"})

    assert status == 409
    storage.save.assert_not_awaited()


async def test_lost_creation_race_returns_409(
    handler: FormAPIHandler, registry: FormRegistry, monkeypatch
) -> None:
    """If another writer wins between the check and register, answer 409.

    ``register(overwrite=False)`` is a silent no-op on a taken id, so without
    the post-register identity check the loser would return 201 for a form
    that was never stored.
    """
    real_register = registry.register

    async def _register_with_interloper(form, **kwargs):
        # Simulate a concurrent creation landing first.
        await real_register(
            FormSchema(
                form_id=form.form_id,
                title="Interloper",
                sections=[],
                tenant="t1",
            ),
            tenant="t1",
            overwrite=True,
        )
        return await real_register(form, **kwargs)

    monkeypatch.setattr(registry, "register", _register_with_interloper)

    status, payload = await _create(handler, body={"form_id": "raced"})
    assert status == 409
    assert "already exists" in payload["error"]

    winner = await registry.get("raced", tenant="t1")
    assert winner is not None
    assert winner.title == "Interloper"


# ---------------------------------------------------------------------------
# The user story: new blank form → drop controls on the canvas
# ---------------------------------------------------------------------------


async def test_blank_form_then_add_controls_via_operations(
    handler: FormAPIHandler, registry: FormRegistry
) -> None:
    """End-to-end manual flow: create blank, then add two fields and a section."""
    _, blank = await _create(handler, body={"title": "Canvas Form"})
    form_id = blank["form_id"]
    section_id = blank["sections"][0]["section_id"]

    ops_req = _make_request(
        match_info={"form_id": form_id},
        app={"form_registry": registry},
        body={
            "operations": [
                {
                    "op": "add_field",
                    "section_id": section_id,
                    "field": {
                        "field_id": "full_name",
                        "field_type": "text",
                        "label": "Full Name",
                        "required": True,
                    },
                },
                {
                    "op": "add_field",
                    "section_id": section_id,
                    "field": {
                        "field_id": "visit_date",
                        "field_type": "date",
                        "label": "Visit Date",
                    },
                },
                {
                    "op": "add_section",
                    "section": {"section_id": "notes", "fields": []},
                },
            ],
        },
    )
    resp = await handle_operations(ops_req)
    assert resp.status == 200

    updated = json.loads(resp.body.decode())["form"]
    assert [f["field_id"] for f in updated["sections"][0]["fields"]] == [
        "full_name",
        "visit_date",
    ]
    assert [s["section_id"] for s in updated["sections"]] == [section_id, "notes"]
    # Version bumped off the 1.0 the blank form was created with.
    assert updated["version"] == "1.1"

    stored = await registry.get(form_id, tenant="t1")
    assert stored is not None
    assert [f.field_id for f in stored.iter_all_fields()] == [
        "full_name",
        "visit_date",
    ]
