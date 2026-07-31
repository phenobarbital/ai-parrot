"""Unit tests for FEAT-300 API endpoints (TASK-007, updated FEAT-389).

Tests the six new handler methods on FormAPIHandler:
  - publish_form      POST /forms/{form_uid}/publish
  - list_fields       GET  /fields
  - create_field      POST /fields
  - list_versions     GET  /forms/{form_uid}/versions
  - get_version       GET  /forms/{form_uid}/versions/{version}
  - get_import_report GET  /forms/{form_uid}/import-report

All tests use mocked aiohttp requests — no live HTTP server required.

FEAT-389: URL path identifiers are now ``form_uid`` (validated as a UUID by
``extract_form_uid()``), not ``form_id`` (slug) — ``_make_request()`` takes
a ``form_uid`` kwarg, and "unknown form" tests use well-formed-but-absent
UUID strings rather than arbitrary slugs (which would now fail UUID
validation with 400 before ever reaching the "not found" 404 path).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.tools.services.networkninja import (
    ImportDiffEntry,
    ImportDiffReport,
)

# Well-formed UUIDs that are never registered — used for "unknown form"
# tests, distinct from any auto-generated form.form_uid.
_UNKNOWN_FORM_UID = "00000000-0000-0000-0000-000000000000"
_OTHER_FORM_UID = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_form(form_id: str = "f1", tenant: str = "t1") -> FormSchema:
    """Minimal FormSchema for tests. form_uid is auto-generated."""
    return FormSchema(
        form_id=form_id,
        title="Test Form",
        version="1.0",
        tenant=tenant,
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="q1", field_type=FieldType.TEXT, label="Q1")],
            )
        ],
    )


def _make_request(
    *,
    method: str = "GET",
    form_uid: str = _UNKNOWN_FORM_UID,
    version: str | None = None,
    body: dict | None = None,
    session_programs: list[str] | None = None,
    tenant: str = "t1",
) -> MagicMock:
    """Build a mocked aiohttp web.Request.

    Args:
        method: HTTP method string.
        form_uid: Value for the ``{form_uid}`` path parameter — MUST be a
            well-formed UUID string (validated by ``extract_form_uid()``).
        version: Optional value for the ``{version}`` path parameter.
        body: Optional JSON body dict.
        session_programs: Programs list for the navigator-auth session.
            Defaults to ``[tenant]`` so the handler resolves the right tenant.
        tenant: Convenience param used when ``session_programs`` is omitted.
    """
    from aiohttp import web

    req = MagicMock(spec=web.Request)
    req.method = method
    match_info: dict[str, str] = {"form_uid": form_uid}
    if version is not None:
        match_info["version"] = version
    req.match_info = match_info

    # Session / tenant — default to [tenant] so registry lookups resolve.
    programs = session_programs if session_programs is not None else [tenant]
    session_obj = {"session": {"programs": programs}}
    req.session = session_obj
    req.__contains__ = lambda self, key: False  # no "session" key item access

    # Body
    if body is not None:
        req.json = AsyncMock(return_value=body)
    else:
        req.json = AsyncMock(side_effect=ValueError("no body"))

    return req


def _make_handler(
    registry: FormRegistry | None = None,
    *,
    tenant: str = "t1",
) -> FormAPIHandler:
    """Build a FormAPIHandler with a minimal mock registry.

    Args:
        registry: Optional pre-built ``FormRegistry``. When ``None``, a mock
            registry is constructed that returns ``None`` for all ``get()``
            calls (suitable for 404 tests).
        tenant: Tenant string for the mock registry's ``default_tenant``.
    """
    if registry is None:
        registry = MagicMock(spec=FormRegistry)
        registry.get = AsyncMock(return_value=None)
        registry.storage = None
        registry.default_tenant = tenant
        registry.register = AsyncMock()
    return FormAPIHandler(registry=registry)


# ---------------------------------------------------------------------------
# publish_form
# ---------------------------------------------------------------------------


class TestPublishForm:
    """Tests for FormAPIHandler.publish_form()."""

    async def test_publish_endpoint_200(self):
        """Publish returns 200 with form_uid and version."""
        registry = FormRegistry()
        form = _make_form()
        await registry.register(form, tenant="t1")

        handler = _make_handler(registry)
        req = _make_request(method="POST", form_uid=form.form_uid)

        resp = await handler.publish_form(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["form_uid"] == form.form_uid
        assert "version" in body
        assert body["version"]  # non-empty version string

    async def test_publish_endpoint_404_unknown_form(self):
        """Publishing a non-existent form returns 404."""
        handler = _make_handler()
        req = _make_request(method="POST", form_uid=_UNKNOWN_FORM_UID)

        resp = await handler.publish_form(req)

        assert resp.status == 404
        body = json.loads(resp.body)
        assert "error" in body

    async def test_publish_endpoint_409_frozen_conflict(self):
        """Publishing a version that already exists returns 409."""
        registry = FormRegistry()
        form = _make_form()
        await registry.register(form, tenant="t1")

        handler = _make_handler(registry)
        req = _make_request(method="POST", form_uid=form.form_uid)

        # First publish succeeds; second publish bumps to 1.2, but if we reset
        # the form back to 1.0 and the snapshot for 1.1 already exists → 409.
        await handler.publish_form(req)  # → 1.1

        # Force the live form back to 1.0 so next publish tries to create 1.1 again.
        # Same form_uid as `form` — this represents re-registering the SAME form.
        form_back = _make_form(form_id="f1")
        form_back.form_uid = form.form_uid
        await registry.register(form_back, overwrite=True, tenant="t1")

        resp = await handler.publish_form(req)

        assert resp.status == 409
        body = json.loads(resp.body)
        assert "error" in body


# ---------------------------------------------------------------------------
# list_fields
# ---------------------------------------------------------------------------


class TestListFields:
    """Tests for FormAPIHandler.list_fields()."""

    async def test_list_fields_endpoint(self):
        """GET /fields returns 200 with a fields list (may be empty)."""
        handler = _make_handler()
        req = _make_request(method="GET")

        resp = await handler.list_fields(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert "fields" in body
        assert isinstance(body["fields"], list)

    async def test_list_fields_returns_created_field(self):
        """A field added via create_field appears in list_fields."""
        handler = _make_handler()
        field_body = {
            "field_id": "q1",
            "field_type": "text",
            "label": "Question 1",
        }
        create_req = _make_request(method="POST", body=field_body)
        await handler.create_field(create_req)

        list_req = _make_request(method="GET")
        resp = await handler.list_fields(list_req)

        body = json.loads(resp.body)
        assert len(body["fields"]) == 1
        assert body["fields"][0]["definition"]["field_id"] == "q1"


# ---------------------------------------------------------------------------
# create_field
# ---------------------------------------------------------------------------


class TestCreateField:
    """Tests for FormAPIHandler.create_field()."""

    async def test_create_field_endpoint(self):
        """POST /fields returns 201 with the created ReusableField."""
        handler = _make_handler()
        field_body = {
            "field_id": "name",
            "field_type": "text",
            "label": "Full Name",
        }
        req = _make_request(method="POST", body=field_body)

        resp = await handler.create_field(req)

        assert resp.status == 201
        body = json.loads(resp.body)
        assert "field_id" in body
        assert body["definition"]["label"] == "Full Name"

    async def test_create_field_bad_json(self):
        """Invalid JSON body → 400."""
        from aiohttp import web

        handler = _make_handler()
        req = MagicMock(spec=web.Request)
        req.match_info = {"form_id": "f1"}
        req.session = {"session": {"programs": []}}
        req.__contains__ = lambda self, key: False
        req.json = AsyncMock(side_effect=ValueError("bad json"))

        resp = await handler.create_field(req)

        assert resp.status == 400

    async def test_create_field_invalid_body_422(self):
        """Body with invalid FormField fields → 422."""
        handler = _make_handler()
        req = _make_request(method="POST", body={"field_type": "text"})  # missing field_id

        resp = await handler.create_field(req)

        assert resp.status == 422


# ---------------------------------------------------------------------------
# list_versions
# ---------------------------------------------------------------------------


class TestListVersions:
    """Tests for FormAPIHandler.list_versions()."""

    async def test_list_versions_endpoint(self):
        """GET .../versions returns form_uid + versions list."""
        registry = FormRegistry()
        form = _make_form()
        await registry.register(form, tenant="t1")

        handler = _make_handler(registry)
        # Publish once so there's a version in the history
        pub_req = _make_request(method="POST", form_uid=form.form_uid)
        await handler.publish_form(pub_req)

        req = _make_request(method="GET", form_uid=form.form_uid)
        resp = await handler.list_versions(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["form_uid"] == form.form_uid
        assert isinstance(body["versions"], list)
        assert len(body["versions"]) >= 1
        v = body["versions"][0]
        assert "version" in v
        assert "published_at" in v
        assert "is_current" in v
        assert "published_by" in v

    async def test_list_versions_404_unknown_form(self):
        """Listing versions for an unknown form → 404."""
        handler = _make_handler()
        req = _make_request(method="GET", form_uid=_UNKNOWN_FORM_UID)

        resp = await handler.list_versions(req)

        assert resp.status == 404

    async def test_list_versions_empty_before_publish(self):
        """A form with no publishes has an empty versions list."""
        registry = FormRegistry()
        form = _make_form()
        await registry.register(form, tenant="t1")

        handler = _make_handler(registry)
        req = _make_request(method="GET", form_uid=form.form_uid)
        resp = await handler.list_versions(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["versions"] == []


# ---------------------------------------------------------------------------
# get_version
# ---------------------------------------------------------------------------


class TestGetVersion:
    """Tests for FormAPIHandler.get_version()."""

    async def test_get_version_endpoint_200(self):
        """Known version returns 200 with full FormSchema JSON."""
        registry = FormRegistry()
        form = _make_form()
        await registry.register(form, tenant="t1")

        handler = _make_handler(registry)
        # Publish first
        pub_req = _make_request(method="POST", form_uid=form.form_uid)
        pub_resp = await handler.publish_form(pub_req)
        published_version = json.loads(pub_resp.body)["version"]

        req = _make_request(method="GET", form_uid=form.form_uid, version=published_version)
        resp = await handler.get_version(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["form_uid"] == form.form_uid
        assert body["published_version"] == published_version

    async def test_get_version_endpoint_404(self):
        """Unknown version → 404."""
        handler = _make_handler()
        req = _make_request(method="GET", form_uid=_UNKNOWN_FORM_UID, version="99.0")

        resp = await handler.get_version(req)

        assert resp.status == 404
        body = json.loads(resp.body)
        assert "error" in body

    async def test_get_version_unknown_form_404(self):
        """Unknown form_uid → 404 regardless of version."""
        handler = _make_handler()
        req = _make_request(method="GET", form_uid=_UNKNOWN_FORM_UID, version="1.0")

        resp = await handler.get_version(req)

        assert resp.status == 404


# ---------------------------------------------------------------------------
# get_import_report
# ---------------------------------------------------------------------------


class TestGetImportReport:
    """Tests for FormAPIHandler.get_import_report()."""

    async def test_import_report_endpoint_404_no_report(self):
        """Form with no import history → 404."""
        handler = _make_handler()
        req = _make_request(method="GET", form_uid=_UNKNOWN_FORM_UID)

        resp = await handler.get_import_report(req)

        assert resp.status == 404
        body = json.loads(resp.body)
        assert "error" in body

    async def test_import_report_endpoint(self):
        """A stored ImportDiffReport is returned as JSON (200)."""
        handler = _make_handler()

        # Pre-populate the report store (simulates a completed import flow).
        # Keyed by (tenant, form_uid) — FEAT-389.
        report = ImportDiffReport(
            form_id="f1",
            source="networkninja",
            imported_at=datetime.now(timezone.utc),
            fields=[
                ImportDiffEntry(
                    column_name="col1",
                    source_data_type="FIELD_TEXT",
                    mapped_field_type="text",
                    status="mapeado",
                ),
                ImportDiffEntry(
                    column_name="col2",
                    source_data_type="FIELD_FORMULA",
                    mapped_field_type="formula",
                    status="requiere_intervencion",
                    note="expression unavailable (FEAT-301)",
                ),
            ],
        )
        handler._import_reports[("t1", _UNKNOWN_FORM_UID)] = report

        req = _make_request(method="GET", form_uid=_UNKNOWN_FORM_UID)
        resp = await handler.get_import_report(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["source"] == "networkninja"
        assert all("status" in f for f in body["fields"])
        assert len(body["fields"]) == 2

    async def test_import_report_correct_form_id_lookup(self):
        """Import report is scoped per form_uid — other form returns 404."""
        handler = _make_handler()
        report = ImportDiffReport(
            form_id="f1",
            source="networkninja",
            imported_at=datetime.now(timezone.utc),
        )
        handler._import_reports[("t1", _UNKNOWN_FORM_UID)] = report

        # Request for a DIFFERENT form_uid
        req = _make_request(method="GET", form_uid=_OTHER_FORM_UID)
        resp = await handler.get_import_report(req)

        assert resp.status == 404
