"""Cross-module integration tests for stable UUID-based form identity
(FEAT-389, TASK-1982 — Module 10).

These tests close the specific acceptance-criteria gaps not already
covered by the per-module unit tests added by TASK-1972 through
TASK-1981 (dual-index / slug-uniqueness / rename-stability are already
exercised deeply in ``tests/unit/test_registry_multi_tenancy.py::
TestRegistryFormUid`, and migration integrity/idempotency in
``tests/unit/test_migrations_form_uid.py``):

1. Blank form creation (`POST /forms/blank`) returns a well-formed `form_uid`.
2. Slug search (`GET /forms?slug=...`) filters via `FormRegistry.get_by_slug()`.
3. Malformed `form_uid` path segments are rejected with 400 by
   `extract_form_uid()` before any registry lookup.
4. A full create -> access -> rename -> re-access round trip through the
   `FormAPIHandler` (not just the registry directly), confirming form_uid
   is what stays stable across the API surface.

Handler methods are invoked directly with mocked ``aiohttp.web.Request``
objects — the same pattern used throughout this test suite (see
``tests/unit/test_api_feat300.py``) — rather than through a live HTTP
server, since routes are wrapped with navigator-auth's
``is_authenticated``/``user_session`` decorators at registration time
(``api/routes.py::_wrap_auth``), which direct handler calls bypass.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot_formdesigner.api.handlers import FormAPIHandler, extract_form_uid
from parrot_formdesigner.services.registry import FormRegistry

# A well-formed UUID that is never registered — used for "unknown form"
# checks, distinct from any auto-generated form.form_uid.
_UNKNOWN_FORM_UID = "00000000-0000-0000-0000-000000000000"


def _make_request(
    *,
    method: str = "GET",
    form_uid: str | None = None,
    query: dict[str, str] | None = None,
    body: dict | None = None,
    tenant: str = "t1",
) -> MagicMock:
    """Build a mocked aiohttp web.Request.

    Args:
        method: HTTP method string.
        form_uid: Value for the ``{form_uid}`` path parameter, when the
            route being exercised has one. Omitted entirely from
            ``match_info`` when ``None`` (e.g. for ``list_forms``, which
            has no path parameter).
        query: Query string parameters (e.g. ``{"slug": "my-form"}``).
        body: Optional JSON body dict.
        tenant: Convenience tenant used for the mocked session.
    """
    req = MagicMock(spec=web.Request)
    req.method = method
    req.match_info = {"form_uid": form_uid} if form_uid is not None else {}

    req.query = query or {}
    req.headers = {}
    req.app = {}

    # Session / tenant — mirrors tests/unit/test_api_feat300.py's pattern so
    # FormAPIHandler._get_tenant() resolves the right tenant.
    req.session = {"session": {"programs": [tenant]}}
    req.__contains__ = lambda self, key: False

    if body is not None:
        req.json = AsyncMock(return_value=body)
    else:
        req.json = AsyncMock(side_effect=ValueError("no body"))

    return req


def _make_handler(registry: FormRegistry | None = None) -> FormAPIHandler:
    """Build a FormAPIHandler backed by a real (in-memory) FormRegistry."""
    if registry is None:
        registry = FormRegistry(require_tenant=False, default_tenant="t1")
    return FormAPIHandler(registry=registry)


# ---------------------------------------------------------------------------
# 1. Blank form creation
# ---------------------------------------------------------------------------


class TestCreateBlankForm:
    """POST /forms/blank -> FormAPIHandler.create_blank_form()."""

    async def test_create_blank_form_returns_uid(self) -> None:
        """201 response includes a well-formed form_uid."""
        handler = _make_handler()
        req = _make_request(method="POST", body={"title": "My Blank Form"})

        resp = await handler.create_blank_form(req)

        assert resp.status == 201
        body = json_body(resp)
        assert "form_uid" in body
        uuid.UUID(body["form_uid"])  # raises ValueError if malformed
        assert body["form_id"]  # slugified from title
        assert body["title"] == "My Blank Form"

    async def test_create_blank_form_missing_title_400(self) -> None:
        """Missing 'title' in the body returns 400."""
        handler = _make_handler()
        req = _make_request(method="POST", body={})

        resp = await handler.create_blank_form(req)

        assert resp.status == 400

    async def test_create_blank_form_registers_in_registry(self) -> None:
        """The created form is retrievable from the registry by its form_uid."""
        registry = FormRegistry(require_tenant=False, default_tenant="t1")
        handler = _make_handler(registry)
        req = _make_request(method="POST", body={"title": "Findable"})

        resp = await handler.create_blank_form(req)
        body = json_body(resp)

        found = await registry.get(body["form_uid"], tenant="t1")
        assert found is not None
        assert found.form_id == body["form_id"]


# ---------------------------------------------------------------------------
# 2. Slug search
# ---------------------------------------------------------------------------


class TestListFormsSlugFilter:
    """GET /forms?slug=... -> FormAPIHandler.list_forms()."""

    async def test_list_forms_filter_by_slug(self) -> None:
        """?slug=<form_id> resolves via FormRegistry.get_by_slug()."""
        registry = FormRegistry(require_tenant=False, default_tenant="t1")
        handler = _make_handler(registry)

        create_req = _make_request(method="POST", body={"title": "Findable By Slug"})
        created = json_body(await handler.create_blank_form(create_req))

        list_req = _make_request(query={"slug": created["form_id"]})
        resp = await handler.list_forms(list_req)

        assert resp.status == 200
        body = json_body(resp)
        assert len(body["forms"]) == 1
        assert body["forms"][0]["form_uid"] == created["form_uid"]
        assert body["forms"][0]["form_id"] == created["form_id"]

    async def test_list_forms_filter_by_slug_no_match(self) -> None:
        """?slug=<unknown> returns an empty list, not an error."""
        handler = _make_handler()
        req = _make_request(query={"slug": "does-not-exist"})

        resp = await handler.list_forms(req)

        assert resp.status == 200
        assert json_body(resp)["forms"] == []


# ---------------------------------------------------------------------------
# 3. UUID validation
# ---------------------------------------------------------------------------


class TestFormUidValidation:
    """extract_form_uid() rejects malformed path segments with 400."""

    def test_extract_form_uid_rejects_non_uuid(self) -> None:
        """A non-UUID form_uid path segment raises HTTPBadRequest."""
        req = MagicMock(spec=web.Request)
        req.match_info = {"form_uid": "not-a-uuid"}

        with pytest.raises(web.HTTPBadRequest) as exc_info:
            extract_form_uid(req)

        assert exc_info.value.status == 400
        assert "not-a-uuid" in exc_info.value.text

    def test_extract_form_uid_accepts_well_formed_uuid(self) -> None:
        """A well-formed UUID string round-trips unchanged."""
        req = MagicMock(spec=web.Request)
        req.match_info = {"form_uid": _UNKNOWN_FORM_UID}

        assert extract_form_uid(req) == _UNKNOWN_FORM_UID

    async def test_get_form_invalid_uuid_returns_400(self) -> None:
        """GET /forms/{form_uid} with a malformed form_uid never reaches the
        registry — it 400s from extract_form_uid() first."""
        registry = MagicMock(spec=FormRegistry)
        registry.get = AsyncMock(return_value=None)
        handler = FormAPIHandler(registry=registry)
        req = _make_request(form_uid="not-a-uuid")

        with pytest.raises(web.HTTPBadRequest) as exc_info:
            await handler.get_form(req)

        assert exc_info.value.status == 400
        registry.get.assert_not_called()

    async def test_get_form_unknown_but_well_formed_uuid_404(self) -> None:
        """A well-formed but unregistered form_uid reaches the registry and
        gets a normal 404 — distinguishing 'malformed' from 'not found'."""
        handler = _make_handler()
        req = _make_request(form_uid=_UNKNOWN_FORM_UID)

        resp = await handler.get_form(req)

        assert resp.status == 404


# ---------------------------------------------------------------------------
# 4. Cross-module round trip: create -> access -> rename -> re-access
# ---------------------------------------------------------------------------


class TestFormUidStableAcrossApi:
    """The API surface (not just the registry) treats form_uid as the
    stable identity — renaming the slug never changes it or breaks access."""

    async def test_create_access_rename_reaccess_round_trip(self) -> None:
        """A form created via the API stays reachable by its form_uid after
        its slug (form_id) changes, and the slug index tracks the move."""
        registry = FormRegistry(require_tenant=False, default_tenant="t1")
        handler = _make_handler(registry)

        create_req = _make_request(method="POST", body={"title": "Renameable"})
        created = json_body(await handler.create_blank_form(create_req))
        form_uid = created["form_uid"]
        old_slug = created["form_id"]

        # Access via form_uid (the API's only lookup key post-FEAT-389).
        get_req = _make_request(form_uid=form_uid)
        resp = await handler.get_form(get_req)
        assert resp.status == 200
        assert json_body(resp)["form_uid"] == form_uid

        # Rename the slug directly on the live form and re-register (mirrors
        # the registry-level rename-stability test in
        # test_registry_multi_tenancy.py::TestRegistryFormUid, but exercised
        # here through the handler's own registry instance).
        form = await registry.get(form_uid, tenant="t1")
        assert form is not None
        form.form_id = "renamed-slug"
        await registry.register(form, tenant="t1")

        # form_uid is unchanged and still resolves via the handler.
        resp2 = await handler.get_form(_make_request(form_uid=form_uid))
        assert resp2.status == 200
        body2 = json_body(resp2)
        assert body2["form_uid"] == form_uid
        assert body2["form_id"] == "renamed-slug"

        # The slug index moved: old slug no longer resolves, new one does.
        assert await registry.get_by_slug(old_slug, tenant="t1") is None
        via_new_slug = await registry.get_by_slug("renamed-slug", tenant="t1")
        assert via_new_slug is not None
        assert via_new_slug.form_uid == form_uid


# ---------------------------------------------------------------------------
# Test helper
# ---------------------------------------------------------------------------


def json_body(resp: web.Response) -> dict:
    """Decode a JSONResponse's body back into a dict for assertions.

    Matches the pattern used throughout this suite (e.g.
    ``tests/unit/test_api_feat300.py``) for handler methods invoked
    directly (not through a live HTTP client).
    """
    import json as _json

    return _json.loads(resp.body)
