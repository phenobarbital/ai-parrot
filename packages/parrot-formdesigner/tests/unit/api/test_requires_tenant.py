"""Unit tests for the requires_tenant decorator (FEAT-421 TASK-2199)."""

import pytest
from parrot_formdesigner.api.errors import (
    TenantConflictError,
    TenantForbiddenError,
    TenantNotDeclaredError,
)
from parrot_formdesigner.api.tenant import (
    assert_body_tenant_matches,
    declared_tenant,
    requires_tenant,
)


class _FakeRequest(dict):
    """Minimal stand-in exposing .match_info, .session and dict item access.

    aiohttp's real ``web.Request`` supports ``request["key"] = value`` and
    ``request.get("key")`` via its own Mapping implementation; a plain dict
    subclass gives us that for free while letting us bolt on ``match_info``
    and ``session`` attributes.
    """

    def __init__(self, *, match_info=None, session=None):
        super().__init__()
        self.match_info = match_info or {}
        self.session = session


def make_request(tenant=None, programs=None, superuser=False, with_session=True):
    """Build a fake request declaring a tenant and (optionally) a session."""
    match_info = {"tenant": tenant} if tenant is not None else {}
    session = None
    if with_session:
        session = {"session": {"programs": programs or [], "superuser": superuser}}
    return _FakeRequest(match_info=match_info, session=session)


class TestRequiresTenant:
    async def test_passes_declared_tenant(self):
        req = make_request(tenant="flexroc", programs=["flexroc"])
        seen = {}

        @requires_tenant()
        async def handler(request):
            seen["t"] = declared_tenant(request)
            return "ok"

        assert await handler(req) == "ok"
        assert seen["t"] == "flexroc"

    @pytest.mark.parametrize("value", [None, "", "   "])
    async def test_400_when_not_declared(self, value):
        req = make_request(tenant=value, programs=["flexroc"])

        @requires_tenant()
        async def handler(request):
            return "ok"

        with pytest.raises(TenantNotDeclaredError):
            await handler(req)

    async def test_403_non_member(self):
        req = make_request(tenant="flexroc", programs=["navigator"])

        @requires_tenant()
        async def handler(request):
            return "ok"

        with pytest.raises(TenantForbiddenError):
            await handler(req)

    async def test_allows_superuser(self):
        req = make_request(tenant="anything", programs=[], superuser=True)

        @requires_tenant()
        async def handler(request):
            return "ok"

        assert await handler(req) == "ok"

    async def test_403_no_session(self):
        req = make_request(tenant="flexroc", with_session=False)

        @requires_tenant()
        async def handler(request):
            return "ok"

        with pytest.raises(TenantForbiddenError):
            await handler(req)

    async def test_public_skips_authorization(self):
        req = make_request(tenant="flexroc", with_session=False)

        @requires_tenant(public=True)
        async def handler(request):
            return "ok"

        assert await handler(req) == "ok"

    async def test_public_still_requires_tenant(self):
        req = make_request(tenant=None, with_session=False)

        @requires_tenant(public=True)
        async def handler(request):
            return "ok"

        with pytest.raises(TenantNotDeclaredError):
            await handler(req)


class TestDeclaredTenant:
    def test_raises_without_decorator(self):
        with pytest.raises(RuntimeError):
            declared_tenant(make_request(tenant="flexroc"))


class TestBodyCrossCheck:
    def test_match_ok(self):
        assert_body_tenant_matches({"tenant": "flexroc"}, "flexroc")

    def test_absent_ok(self):
        assert_body_tenant_matches({"title": "x"}, "flexroc")

    def test_conflict_raises(self):
        with pytest.raises(TenantConflictError):
            assert_body_tenant_matches({"tenant": "navigator"}, "flexroc")


class TestNoForbiddenReferences:
    def test_module_does_not_reference_removed_concepts(self):
        import inspect

        from parrot_formdesigner.api import tenant as tenant_module

        source = inspect.getsource(tenant_module)
        assert "tenant_context" not in source
        assert "program_slug" not in source
        assert "default_tenant" not in source
