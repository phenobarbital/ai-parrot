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
    """Minimal stand-in shaped like a REAL function-path request.

    On navigator-auth's function path (`_func_wrapper`), the session travels
    as the ``request["session"]`` DICT KEY; the ``request.session``
    ATTRIBUTE is set only by the class-based-view `_method_wrapper`. The
    previous version of this fake set ``self.session`` in its constructor —
    an attribute no real function-path request ever has — so the suite
    stayed green while every production request was refused (0.9.1's
    universal ``tenant_forbidden``). The double is now shaped like the
    request the code actually receives: session under the dict key, NO
    session attribute, and an optional ``user`` attribute standing in for
    the object navigator-auth's middleware attaches.
    """

    def __init__(self, *, match_info=None, session=None, user=None):
        super().__init__()
        self.match_info = match_info or {}
        if session is not None:
            self["session"] = session
        if user is not None:
            self.user = user


class _FakeUser:
    def __init__(self, superuser=False):
        self.superuser = superuser


def make_request(tenant=None, programs=None, superuser=False, with_session=True, user=None):
    """Build a fake request declaring a tenant and (optionally) a session."""
    match_info = {"tenant": tenant} if tenant is not None else {}
    session = None
    if with_session:
        session = {"session": {"programs": programs or [], "superuser": superuser}}
    return _FakeRequest(match_info=match_info, session=session, user=user)


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


class TestSessionDelivery:
    """The 0.9.1 regression, pinned at the exact seam it slipped through."""

    async def test_the_dict_key_alone_is_enough(self):
        """A REAL function-path request carries the session ONLY under
        ``request["session"]``. This is the case 0.9.1 refused universally —
        and the one the old attribute-bearing fake could never exercise."""
        req = _FakeRequest(
            match_info={"tenant": "epson"},
            session={"session": {"programs": ["epson"], "superuser": False}},
        )
        assert not hasattr(req, "session")  # the shape that shipped the bug

        @requires_tenant()
        async def handler(request):
            return "ok"

        assert await handler(req) == "ok"

    async def test_middleware_user_object_grants_superuser(self):
        """``request.user`` is what navigator-auth's middleware attaches on
        every authenticated request; ``AuthUser.superuser`` is a declared
        field. No session dict needed at all for the superuser grant."""
        req = _FakeRequest(match_info={"tenant": "epson"}, user=_FakeUser(superuser=True))

        @requires_tenant()
        async def handler(request):
            return "ok"

        assert await handler(req) == "ok"

    async def test_a_cbv_style_attribute_still_resolves(self):
        """The CBV `_method_wrapper` DOES set the attribute — a caller from
        that path must keep working through the fallback."""
        req = _FakeRequest(match_info={"tenant": "epson"})
        req.session = {"session": {"programs": ["epson"], "superuser": False}}

        @requires_tenant()
        async def handler(request):
            return "ok"

        assert await handler(req) == "ok"

    async def test_non_superuser_user_object_does_not_grant(self):
        req = _FakeRequest(match_info={"tenant": "epson"}, user=_FakeUser(superuser=False))

        @requires_tenant()
        async def handler(request):
            return "ok"

        with pytest.raises(TenantForbiddenError):
            await handler(req)
