"""Unit tests for the _get_tenant / _session_tenant split (FEAT-421 TASK-2202)."""

import pytest
from aiohttp.test_utils import make_mocked_request
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.registry import FormRegistry


@pytest.fixture
def registry():
    return FormRegistry()


@pytest.fixture
def handler(registry):
    return FormAPIHandler(registry=registry)


def _request(*, tenant=None, session_programs=None, match_info=None):
    request = make_mocked_request(
        "GET", "/api/v1/x/forms", match_info=match_info or {}
    )
    if tenant is not None:
        request["tenant"] = tenant
    if session_programs is not None:
        request.session = {"session": {"programs": session_programs}}
    return request


class TestTenantSplit:
    def test_get_tenant_returns_declared(self, handler):
        request = _request(tenant="flexroc")
        assert handler._get_tenant(request) == "flexroc"

    def test_get_tenant_raises_without_decorator(self, handler):
        request = _request()
        with pytest.raises(RuntimeError):
            handler._get_tenant(request)

    def test_get_tenant_never_returns_default(self, handler):
        """The 0.8.21 fallback must be gone from the forms path."""
        request = _request()
        with pytest.raises(RuntimeError):
            handler._get_tenant(request)

    def test_session_tenant_prefers_first_program(self, handler):
        request = _request(session_programs=["navigator", "flexroc"])
        assert handler._session_tenant(request) == "navigator"

    def test_session_tenant_falls_back_to_default(self, handler):
        request = _request(session_programs=[])
        assert handler._session_tenant(request) == handler.registry.default_tenant

    def test_get_tenant_ignores_tenant_context_key(self, handler):
        """FEAT-421: request['tenant_context'] is no longer read (spec AC8)."""
        request = _request(tenant="flexroc")
        request["tenant_context"] = "navigator"
        assert handler._get_tenant(request) == "flexroc"


class TestCrossTenantIsolation:
    async def test_other_tenant_form_is_404(self, handler, registry):
        """404, never 403 — a 403 is an existence oracle."""
        form = FormSchema(
            form_id="contact",
            title={"en": "Contact"},
            tenant="navigator",
            sections=[],
        )
        await registry.register(form, tenant="navigator")

        request = _request(
            tenant="flexroc", match_info={"form_uid": str(form.form_uid)}
        )
        resp = await handler.get_form(request)
        assert resp.status == 404

    async def test_same_tenant_form_is_200(self, handler, registry):
        form = FormSchema(
            form_id="contact",
            title={"en": "Contact"},
            tenant="flexroc",
            sections=[],
        )
        await registry.register(form, tenant="flexroc")

        # FEAT-421 review fix: get_form is mounted tenant="public" (shared
        # with public forms), so a private form (is_public defaults False)
        # still requires tenant membership — declare a matching session.
        request = _request(
            tenant="flexroc",
            session_programs=["flexroc"],
            match_info={"form_uid": str(form.form_uid)},
        )
        resp = await handler.get_form(request)
        assert resp.status == 200

    async def test_private_form_non_member_is_403(self, handler, registry):
        """FEAT-421 review fix (C2): get_form is mounted tenant="public"
        (shared with public forms) — an authenticated non-member must still
        be rejected for a PRIVATE form, not silently let through because
        the route's decorator-level authorization was skipped."""
        form = FormSchema(
            form_id="contact",
            title={"en": "Contact"},
            tenant="flexroc",
            sections=[],
            is_public=False,
        )
        await registry.register(form, tenant="flexroc")

        request = _request(
            tenant="flexroc",
            session_programs=["navigator"],
            match_info={"form_uid": str(form.form_uid)},
        )
        from parrot_formdesigner.api.errors import TenantForbiddenError

        with pytest.raises(TenantForbiddenError):
            await handler.get_form(request)

    async def test_public_form_no_session_is_200(self, handler, registry):
        """A genuinely public form stays reachable unauthenticated — the
        membership gate must not apply to it."""
        form = FormSchema(
            form_id="contact",
            title={"en": "Contact"},
            tenant="flexroc",
            sections=[],
            is_public=True,
        )
        await registry.register(form, tenant="flexroc")

        request = _request(
            tenant="flexroc", match_info={"form_uid": str(form.form_uid)}
        )
        resp = await handler.get_form(request)
        assert resp.status == 200

    def test_assert_form_tenant_raises_404_on_mismatch(self, handler):
        form = FormSchema(
            form_id="contact",
            title={"en": "Contact"},
            tenant="navigator",
            sections=[],
        )
        from aiohttp import web

        with pytest.raises(web.HTTPNotFound):
            handler._assert_form_tenant(form, "flexroc")

    def test_assert_form_tenant_passes_on_match(self, handler):
        form = FormSchema(
            form_id="contact",
            title={"en": "Contact"},
            tenant="flexroc",
            sections=[],
        )
        handler._assert_form_tenant(form, "flexroc")  # must not raise


class TestBodyCrossCheck:
    async def test_conflicting_body_tenant_is_400(self, handler):
        request = make_mocked_request(
            "POST",
            "/api/v1/flexroc/forms/blank",
            match_info={},
        )
        request["tenant"] = "flexroc"

        async def _json():
            return {"title": "My Form", "tenant": "navigator"}

        request.json = _json

        from parrot_formdesigner.api.errors import TenantConflictError

        # A body/URL tenant conflict is raised as an HTTPException — same
        # as any other requires_tenant()-family error — and is converted to
        # a 400 response by aiohttp's router when reached through a real
        # request; called directly here, it propagates as an exception.
        with pytest.raises(TenantConflictError) as exc_info:
            await handler.create_blank_form(request)
        assert exc_info.value.status == 400

    async def test_matching_body_tenant_succeeds(self, handler):
        request = make_mocked_request(
            "POST",
            "/api/v1/flexroc/forms/blank",
            match_info={},
        )
        request["tenant"] = "flexroc"

        async def _json():
            return {"title": "My Form", "tenant": "flexroc"}

        request.json = _json
        resp = await handler.create_blank_form(request)
        assert resp.status == 201

    async def test_absent_body_tenant_succeeds(self, handler):
        request = make_mocked_request(
            "POST",
            "/api/v1/flexroc/forms/blank",
            match_info={},
        )
        request["tenant"] = "flexroc"

        async def _json():
            return {"title": "Another Form"}

        request.json = _json
        resp = await handler.create_blank_form(request)
        assert resp.status == 201


class TestPutPatchTenantStamp:
    """FEAT-421 review fix (2nd pass, CRITICAL — codex P1 finding).

    ``assert_body_tenant_matches()`` only rejects a CONFLICTING body
    tenant; it is a no-op when the field is omitted or explicitly null,
    both valid per ``FormSchema.tenant: str | None = None``. Without
    unconditionally stamping the URL-declared tenant back onto the body
    before ``FormSchema.model_validate()``, an ordinary PUT/PATCH that
    doesn't round-trip the optional ``tenant`` field would silently
    persist ``form.tenant=None`` — permanently 404ing the form for its own
    rightful owner on every subsequent tenant-scoped read.
    """

    async def test_put_without_body_tenant_does_not_corrupt_form_tenant(
        self, handler, registry
    ):
        form = FormSchema(
            form_id="contact",
            title={"en": "Contact"},
            tenant="flexroc",
            sections=[],
        )
        await registry.register(form, tenant="flexroc")

        body = form.model_dump(mode="json", exclude_none=True)
        body.pop("tenant", None)  # legitimate client omission

        put_request = make_mocked_request(
            "PUT",
            f"/api/v1/flexroc/forms/{form.form_uid}",
            match_info={"form_uid": str(form.form_uid)},
        )
        put_request["tenant"] = "flexroc"

        async def _json():
            return body

        put_request.json = _json
        put_resp = await handler.update_form(put_request)
        assert put_resp.status == 200

        # The form must still be readable under its original tenant.
        get_request = _request(
            tenant="flexroc",
            session_programs=["flexroc"],
            match_info={"form_uid": str(form.form_uid)},
        )
        get_resp = await handler.get_form(get_request)
        assert get_resp.status == 200

    async def test_patch_with_null_body_tenant_does_not_corrupt_form_tenant(
        self, handler, registry
    ):
        form = FormSchema(
            form_id="contact",
            title={"en": "Contact"},
            tenant="flexroc",
            sections=[],
        )
        await registry.register(form, tenant="flexroc")

        patch_request = make_mocked_request(
            "PATCH",
            f"/api/v1/flexroc/forms/{form.form_uid}",
            match_info={"form_uid": str(form.form_uid)},
        )
        patch_request["tenant"] = "flexroc"

        async def _json():
            # RFC 7396: an explicit null deletes the key on merge.
            return {"tenant": None}

        patch_request.json = _json
        patch_resp = await handler.patch_form(patch_request)
        assert patch_resp.status == 200

        get_request = _request(
            tenant="flexroc",
            session_programs=["flexroc"],
            match_info={"form_uid": str(form.form_uid)},
        )
        get_resp = await handler.get_form(get_request)
        assert get_resp.status == 200
