"""POST /forms dual-wire surface import tests (FEAT-650, TASK-4203)."""

from __future__ import annotations

import copy
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

pytest.importorskip("parrot.outputs.a2ui")

from parrot_formdesigner.api import a2ui_wire
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.a2ui import A2UIFormRenderer
from parrot_formdesigner.services.registry import FormRegistry

TENANT = "route-tenant"


def _request(
    body: dict, *, content_length: int | None = None, overwrite: str = "", session: dict | None = None
) -> MagicMock:
    """Build the request contract consumed by ``create_form``."""
    request = MagicMock(spec=web.Request)
    request.content_type = "application/json"
    request.content_length = content_length if content_length is not None else len(json.dumps(body))
    request.query = {"overwrite": overwrite} if overwrite else {}
    request.json = AsyncMock(return_value=body)
    request.get = MagicMock(side_effect=lambda key, default=None: TENANT if key == "tenant" else default)
    request.app.get = MagicMock(return_value="/forms")
    if session is not None:
        request.session = {"session": session}
    return request


@pytest.fixture
def handler() -> FormAPIHandler:
    """Provide a handler with no LLM client configured."""
    instance = FormAPIHandler(registry=FormRegistry())
    instance._create_tool.client = None
    return instance


@pytest.fixture
async def surface() -> dict:
    """Render a strict A2UI surface with a stable form UID."""
    form = FormSchema(
        form_uid=uuid.UUID("00000000-0000-0000-0000-000000000420"),
        form_id="imported-form",
        title="Imported Form",
        tenant="surface-tenant",
        sections=[
            FormSection(
                section_id="main",
                fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name")],
            )
        ],
    )
    return (await A2UIFormRenderer().render(form)).content


def test_surface_predicate_does_not_require_ai_parrot() -> None:
    """Surface detection accepts the media type or a createSurface body."""
    request = MagicMock(spec=web.Request)
    request.content_type = "application/json"
    assert a2ui_wire.is_a2ui_surface_body(request, {"version": "v1.0", "createSurface": {}})
    assert not a2ui_wire.is_a2ui_surface_body(request, {"version": "v1.0", "action": {}})
    assert not a2ui_wire.is_a2ui_surface_body(request, {"prompt": "hello"})
    request.content_type = "application/a2ui+json"
    assert a2ui_wire.is_a2ui_surface_body(request, None)


async def test_import_creates_form_without_llm_client(handler: FormAPIHandler, surface: dict) -> None:
    """A createSurface body takes the import path before the 503 LLM guard."""
    response = await handler.create_form(_request(surface))

    assert response.status == 201
    payload = json.loads(response.body)
    assert {"form_uid", "form_id", "url", "dialect", "import"} <= payload.keys()
    imported = await handler.registry.get(uuid.UUID(payload["form_uid"]), tenant=TENANT)
    assert imported is not None
    assert imported.tenant == TENANT


async def test_conflict_then_overwrite_bumps_version(handler: FormAPIHandler, surface: dict) -> None:
    """The same surface conflicts unless overwrite is explicitly requested, and overwrite requires membership."""
    first = await handler.create_form(_request(surface))
    conflict = await handler.create_form(_request(surface))
    overwritten = await handler.create_form(
        _request(surface, overwrite="true", session={"programs": [TENANT]})
    )

    assert first.status == 201
    assert conflict.status == 409
    assert json.loads(conflict.body)["form_uid"] == json.loads(first.body)["form_uid"]
    assert overwritten.status == 201
    form_uid = uuid.UUID(json.loads(first.body)["form_uid"])
    assert (await handler.registry.get(form_uid, tenant=TENANT)).version == "1.1"


async def test_overwrite_without_membership_is_forbidden(handler: FormAPIHandler, surface: dict) -> None:
    """A caller with no tenant-membership session cannot overwrite a private form."""
    from parrot_formdesigner.core.tenant_errors import TenantForbiddenError

    first = await handler.create_form(_request(surface))
    assert first.status == 201

    with pytest.raises(TenantForbiddenError):
        await handler.create_form(_request(surface, overwrite="true"))

    form_uid = uuid.UUID(json.loads(first.body)["form_uid"])
    assert (await handler.registry.get(form_uid, tenant=TENANT)).version == "1.0"


async def test_invalid_surface_returns_422_and_oversize_returns_413(
    handler: FormAPIHandler, surface: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid extraction and the body cap use their specified responses."""
    invalid = copy.deepcopy(surface)
    invalid["createSurface"]["components"].append(copy.deepcopy(invalid["createSurface"]["components"][0]))
    invalid_response = await handler.create_form(_request(invalid))
    assert invalid_response.status == 422
    assert json.loads(invalid_response.body)["error"] == "invalid surface"

    monkeypatch.setattr(a2ui_wire, "A2UI_MAX_BODY_BYTES", 10)
    oversized = await handler.create_form(_request(surface, content_length=11))
    assert oversized.status == 413


async def test_prompt_body_still_requires_llm_client(handler: FormAPIHandler) -> None:
    """Legacy prompt requests retain the no-client response."""
    response = await handler.create_form(_request({"prompt": "make a form"}))

    assert response.status == 503
