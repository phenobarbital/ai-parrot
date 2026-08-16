"""End-to-end integration tests for FEAT-393 (Stable UUID-Based Field
Identity) — spec §4 "Integration Tests" (Module 15, TASK-2009).

These three tests are the feature's reason to exist: they exercise the
REAL component stack (operations handler, blob storage, partial saves,
rule evaluator/resolution, EditToolkit, CreateFormTool, the migration
script) together — not unit-level mocks of each other. The only mocked
collaborators are genuinely EXTERNAL systems (the LLM client for
CreateFormTool, the REST field resolver for the upload's external
callback) — the same convention already used throughout this test suite
(e.g. `tests/unit/test_create_form_tool.py`'s `mock_client`,
`tests/unit/renderers/test_rest_html5.py`'s mocked resolver).
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import FormData, web
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.api.operations import handle_operations
from parrot_formdesigner.api.uploads import handle_rest_upload
from parrot_formdesigner.core.constraints import (
    ConditionOperator,
    DependencyRule,
    FieldCondition,
)
from parrot_formdesigner.core.resolution import resolve_rule_references
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.blob_storage import TempBlobStorage
from parrot_formdesigner.services.partial_saves import PartialSaveStore
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.rest_field_resolver import RestFieldResult
from parrot_formdesigner.services.validators import FormValidator
from parrot_formdesigner.tools.create_form import CreateFormTool
from parrot_formdesigner.tools.edit_toolkit import EditToolkit

MIGRATIONS_DIR = Path(__file__).parents[2] / "migrations"


# ---------------------------------------------------------------------------
# Shared in-memory helpers (no live Redis / S3 / LLM required)
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal fake Redis client backed by a plain dict (no live Redis)."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    async def delete(self, key: str) -> int:
        if key in self._store:
            del self._store[key]
            return 1
        return 0

    async def close(self) -> None:
        pass


class InMemoryPartialStore(PartialSaveStore):
    """PartialSaveStore backed by an in-memory dict — no live Redis
    requirement (mirrors the existing stub pattern in
    tests/test_partial_saves_integration.py / test_partial_saves_uid.py)."""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        super().__init__(ttl_seconds=ttl_seconds, redis_url=None)
        self._fake = _FakeRedis()

    async def _get_redis(self):
        return self._fake


def _make_partial_request(
    form_uid: uuid.UUID,
    method: str = "POST",
    session_id: str | None = "sess-1",
    body: dict | None = None,
) -> MagicMock:
    """Mocked aiohttp request for FormAPIHandler.save_partial/get_partial —
    matches the established pattern in tests/test_partial_handlers.py."""
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": str(form_uid)}
    req.method = method

    if session_id is not None:
        req.__contains__ = lambda self, key: key == "session"
        req.__getitem__ = lambda self, key: {"id": session_id} if key == "session" else None
    else:
        req.__contains__ = lambda self, key: False

    if body is not None:
        req.json = AsyncMock(return_value=body)
    else:
        req.json = AsyncMock(side_effect=ValueError("no body"))

    return req


async def _tenant_wrapped(handler):
    """Stash the URL-declared tenant, mirroring what @requires_tenant does.

    These tests exercise the operations/upload handlers' own logic, not
    tenant enforcement (covered by TASK-2199's decorator tests) — matches
    the pattern established in test_render_dispatcher.py /
    test_blob_uid_keys.py for FEAT-421.
    """

    async def _wrapped(request: web.Request) -> web.Response:
        request["tenant"] = request.match_info["tenant"]
        return await handler(request)

    return _wrapped


async def _make_ops_and_upload_client(
    aiohttp_client, registry: FormRegistry, blob_storage, resolver
):
    """aiohttp test client wired with the REAL operations + upload
    handlers (no auth wrapper — matches tests/integration/test_operations_e2e.py
    and tests/integration/test_upload_rest.py's established pattern of
    registering routes directly for handler-level integration testing)."""
    app = web.Application()
    app["form_registry"] = registry
    app["blob_storage"] = blob_storage
    app["rest_resolver"] = resolver
    app.router.add_patch(
        "/api/v1/t/{tenant}/forms/{form_uid}/operations",
        await _tenant_wrapped(handle_operations),
    )
    app.router.add_post(
        "/api/v1/t/{tenant}/forms/{form_uid}/fields/{field_uid}/upload",
        await _tenant_wrapped(handle_rest_upload),
    )
    return await aiohttp_client(app)


# ---------------------------------------------------------------------------
# test_edit_flow_rename_stability
# ---------------------------------------------------------------------------


@pytest.fixture
def rename_flow_form() -> FormSchema:
    """A form with a REST (photo) field, a conditional (state depends on
    country), for the rename-stability flow."""
    country = FormField(field_id="country", field_type=FieldType.TEXT, label="Country")
    state = FormField(
        field_id="state",
        field_type=FieldType.TEXT,
        label="State",
        depends_on=DependencyRule(
            conditions=[FieldCondition(field_id="country", operator=ConditionOperator.EQ, value="US")],
        ),
    )
    photo = FormField(
        field_id="photo",
        field_type=FieldType.REST,
        label="Photo",
        meta={"rest": {"mode": "callback", "callback_ref": "photo_upload"}},
    )
    form = FormSchema(
        form_id="rename-flow-form",
        title="Rename Flow",
        tenant="navigator",
        sections=[FormSection(section_id="s1", fields=[country, state, photo])],
    )
    # Mirrors the real build-boundary resolution pass (extractors,
    # CreateFormTool, blank-form/edit APIs all call this before a form is
    # ever registered) — manual FormField/FormSchema construction in a
    # test must do the same, or depends_on stays field_id-only/unresolved.
    return resolve_rule_references(form)


@pytest.mark.asyncio
async def test_edit_flow_rename_stability(
    aiohttp_client, tmp_path, rename_flow_form: FormSchema
) -> None:
    """create form -> upload to field -> rename field_id via operations ->
    blob reachable, rules evaluate, partial save answers survive under the
    new field_id.

    Exercises the REAL stack: api/operations.py's handle_operations,
    services/blob_storage.py's TempBlobStorage, api/handlers.py's
    FormAPIHandler.save_partial/get_partial, and
    core/resolution.py's resolve_rule_references (already applied when the
    form was built) — only the REST resolver (a genuinely external
    collaborator) is mocked.
    """
    registry = FormRegistry()
    await registry.register(rename_flow_form)

    country_field, _state_field, photo_field = rename_flow_form.sections[0].fields
    country_uid_before = country_field.field_uid
    section_uid = rename_flow_form.sections[0].section_uid

    blob_storage = TempBlobStorage(prefix="rename-flow/")
    resolver = MagicMock()
    resolver.resolve = AsyncMock(
        return_value=RestFieldResult(
            success=True, raw_value=None, answer=None, blob_ref=None,
            display=None, warnings=[], error=None,
        )
    )
    client = await _make_ops_and_upload_client(
        aiohttp_client, registry, blob_storage, resolver
    )

    # 1. Upload a blob to the photo field.
    data = FormData()
    data.add_field(
        "file", io.BytesIO(b"fake photo bytes"), filename="p.jpg", content_type="image/jpeg"
    )
    upload_resp = await client.post(
        f"/api/v1/t/navigator/forms/{rename_flow_form.form_uid}/fields/{photo_field.field_uid}/upload",
        data=data,
    )
    assert upload_resp.status == 200
    upload_body = await upload_resp.json()
    blob_ref = upload_body["blob_ref"]
    assert blob_ref

    # 2. Partial-save an answer for 'country' under its ORIGINAL field_id.
    partial_store = InMemoryPartialStore()
    handler = FormAPIHandler(registry=registry, partial_store=partial_store)
    save_resp = await handler.save_partial(
        _make_partial_request(
            rename_flow_form.form_uid, body={"answers": {"country": "US"}}
        )
    )
    assert save_resp.status == 200

    # 3. Rename 'country' -> 'country_code' via the REAL operations handler.
    rename_resp = await client.patch(
        f"/api/v1/t/navigator/forms/{rename_flow_form.form_uid}/operations",
        json={
            "operations": [
                {
                    "op": "update_field",
                    "section_uid": str(section_uid),
                    "field_uid": str(country_uid_before),
                    "patch": {"field_id": "country_code"},
                }
            ]
        },
    )
    assert rename_resp.status == 200

    # --- Assertion A: blob is still reachable at the SAME blob_ref (blob
    #     keys are field_uid-based, TASK-2002 — a field_id rename never
    #     orphans an existing upload).
    chunks = [c async for c in await blob_storage.get(blob_ref)]
    assert b"".join(chunks) == b"fake photo bytes"

    # --- Assertion B: rules still evaluate — the renamed form's 'state'
    #     depends_on condition still references country's UNCHANGED
    #     field_uid (rule refs are UID-based, TASK-1997/1999 — a field_id
    #     rename never breaks a rule reference).
    renamed_form = await registry.get(rename_flow_form.form_uid)
    renamed_country = next(
        f for f in renamed_form.iter_fields_recursive() if f.field_id == "country_code"
    )
    renamed_state = next(
        f for f in renamed_form.iter_fields_recursive() if f.field_id == "state"
    )
    assert renamed_country.field_uid == country_uid_before
    assert renamed_state.depends_on.conditions[0].field_uid == country_uid_before

    # The rule evaluator still functions end to end against the renamed form.
    # (photo is a REST field — its validator coercion expects a dict shape
    # regardless of `required`; unrelated to field_uid, so a minimal valid
    # value is supplied rather than exercising that pre-existing behavior.)
    validator = FormValidator()
    result = await validator.validate(
        renamed_form,
        {"country_code": "US", "state": "CA", "photo": {"answer": None, "blob_ref": blob_ref}},
    )
    assert result.is_valid is True

    # --- Assertion C: the partial save answer survives the rename — GET
    #     /partial now returns it under the NEW field_id (TASK-2003 — data
    #     is stored field_uid-keyed internally and remapped to the CURRENT
    #     field_id on every read).
    get_resp = await handler.get_partial(
        _make_partial_request(rename_flow_form.form_uid, method="GET")
    )
    assert get_resp.status == 200
    get_body = json.loads(get_resp.body)
    assert get_body["data"] == {"country_code": "US"}
    assert "country" not in get_body["data"]


# ---------------------------------------------------------------------------
# test_llm_create_edit_roundtrip
# ---------------------------------------------------------------------------


_LLM_FORM_JSON = json.dumps({
    "form_id": "llm-roundtrip-form",
    "title": "LLM Roundtrip",
    "sections": [
        {
            "section_id": "main",
            "fields": [
                {"field_id": "name", "field_type": "text", "label": "Name", "required": True},
                {"field_id": "age", "field_type": "integer", "label": "Age"},
            ],
        }
    ],
})


@pytest.mark.asyncio
async def test_llm_create_edit_roundtrip() -> None:
    """CreateFormTool (mocked LLM) generates a form -> EditToolkit edits it
    by field_uid -> validate -> store (registry) -> reload -> UIDs stable.

    The LLM client is the only mock (genuinely external system) — the
    real CreateFormTool, EditToolkit, FormValidator, and FormRegistry are
    exercised together.
    """
    mock_client = AsyncMock()
    mock_client.completion = AsyncMock(return_value=_LLM_FORM_JSON)
    create_tool = CreateFormTool(client=mock_client)

    result = await create_tool.execute(prompt="Create a simple form with name and age")
    assert result.success is True
    created_form = FormSchema.model_validate(result.metadata["form"])

    name_field = next(f for f in created_form.iter_fields_recursive() if f.field_id == "name")
    original_name_uid = name_field.field_uid

    # Edit by field_uid via the real EditToolkit (TASK-2000).
    toolkit = EditToolkit(form=created_form)
    update_result = await toolkit.update_field(
        section_uid=str(created_form.sections[0].section_uid),
        field_uid=str(original_name_uid),
        patch={"label": "Full Name"},
    )
    assert update_result.get("success") is True
    edited_form = toolkit.form

    # Validate the edited form against a real submission.
    validator = FormValidator()
    validation = await validator.validate(edited_form, {"name": "Alice", "age": 30})
    assert validation.is_valid is True

    # Store + reload — UIDs stable across the round-trip.
    registry = FormRegistry(require_tenant=False)
    await registry.register(edited_form)
    reloaded = await registry.get(edited_form.form_uid)

    reloaded_name = next(f for f in reloaded.iter_fields_recursive() if f.field_id == "name")
    assert reloaded_name.field_uid == original_name_uid
    assert reloaded_name.label == "Full Name"
    assert reloaded.form_uid == created_form.form_uid


# ---------------------------------------------------------------------------
# test_migration_end_to_end
# ---------------------------------------------------------------------------


def _load_migration_006():
    module_path = MIGRATIONS_DIR / "006_backfill_element_uids.py"
    spec = importlib.util.spec_from_file_location(
        "migrate_element_uids_006_e2e", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["migrate_element_uids_006_e2e"] = module
    spec.loader.exec_module(module)
    return module


def test_migration_end_to_end(legacy_schema_json: dict) -> None:
    """Legacy-shaped stored form (no UIDs, field_id-keyed rules) ->
    migration -> loads clean (FormSchema.model_validate succeeds), rules
    resolved to field_uid, and re-running the migration is a no-op.
    """
    migration_006 = _load_migration_006()

    # 1. Run the migration once against the legacy document.
    first_result = migration_006.migrate_schema_document(legacy_schema_json)
    assert first_result.skipped_reason is None
    assert first_result.changed is True

    # 2. The migrated document loads clean through FormSchema — every
    #    field/section now carries a field_uid/section_uid.
    migrated_form = FormSchema.model_validate(first_result.migrated_json)
    country = next(f for f in migrated_form.iter_fields_recursive() if f.field_id == "country")
    state = next(f for f in migrated_form.iter_fields_recursive() if f.field_id == "state")
    assert country.field_uid is not None
    assert migrated_form.sections[0].section_uid is not None

    # 3. Rules are resolved: state's depends_on condition now carries
    #    country's field_uid.
    assert state.depends_on.conditions[0].field_uid == country.field_uid

    # 4. Re-running the migration on the already-migrated document is a
    #    no-op — byte-identical output, nothing re-minted or re-resolved.
    second_result = migration_006.migrate_schema_document(first_result.migrated_json)
    assert second_result.changed is False
    assert second_result.migrated_json == first_result.migrated_json
