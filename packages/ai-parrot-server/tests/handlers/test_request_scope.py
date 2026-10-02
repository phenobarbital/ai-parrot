"""FEAT-605 M1 — RequestScope seam (spec §4 unit tests)."""
from __future__ import annotations

import itertools

import pytest
from parrot.handlers import ui_surfaces_scope as legacy
from parrot.handlers.scope import (
    EMPTY_SCOPE,
    RequestScope,
    SessionScopeResolver,
    get_scope_resolver,
    has_installed_resolver,
    normalize_visibility,
    scope_grants,
)


class _Resolver:
    def __init__(self, tag: str) -> None:
        self.tag = tag

    async def resolve(self, request):
        return RequestScope(user_id=self.tag, tenant=None, groups=frozenset())


def test_legacy_aliases_identity():
    assert legacy.SurfaceScope is RequestScope
    assert legacy.SessionSurfaceScopeResolver is SessionScopeResolver
    old = legacy.SurfaceScope(user_id="u", tenant="t", groups=frozenset(), is_superuser=True)
    assert (old.may_author, old.may_administer, old.studio_enabled) == (True, False, True)
    assert legacy.EMPTY_SCOPE is EMPTY_SCOPE and legacy.SurfaceScope.EMPTY is EMPTY_SCOPE


def test_resolver_key_precedence():
    new, old = _Resolver("new"), _Resolver("old")
    assert get_scope_resolver({"scope_resolver": new, "ui_surfaces_scope_resolver": old}) is new
    assert get_scope_resolver({"ui_surfaces_scope_resolver": old}) is old
    assert isinstance(get_scope_resolver({}), SessionScopeResolver)
    assert has_installed_resolver({"ui_surfaces_scope_resolver": old}) and not has_installed_resolver({})
    assert has_installed_resolver({"scope_resolver": new})


_CASES = list(
    itertools.product(
        [None, "other", "t1"],  # record tenant
        ["private", "tenant", "groups", "bogus"],
        [False, True],  # superuser
        [False, True],  # may_administer
        [False, True],  # group overlap
    )
)


@pytest.mark.parametrize("rec_tenant,vis,su,adm,overlap", _CASES)
def test_scope_grants_matrix(rec_tenant, vis, su, adm, overlap):
    scope = RequestScope(
        user_id="u", tenant="t1", groups=frozenset({"g1"}), is_superuser=su, may_administer=adm
    )
    allowed = ["g1"] if overlap else ["g2"]
    got = scope_grants(tenant=rec_tenant, visibility=vis, allowed_groups=allowed, scope=scope)
    if rec_tenant != "t1":
        expected = False
    elif su or adm:
        expected = True
    else:
        expected = vis == "tenant" or (vis == "groups" and overlap)
    assert got is expected


def test_scope_grants_scope_without_tenant_never_matches():
    scope = RequestScope(user_id="u", tenant=None, groups=frozenset({"g"}), is_superuser=True, may_administer=True)
    assert not scope_grants(tenant="t", visibility="tenant", allowed_groups=[], scope=scope)
    assert not scope_grants(tenant=None, visibility="tenant", allowed_groups=[], scope=scope)


def test_normalize_visibility():
    from parrot.handlers.models.ui_surfaces import SurfaceVisibility

    assert normalize_visibility(SurfaceVisibility.tenant) == "tenant"
    assert normalize_visibility("groups") == "groups"
    assert normalize_visibility("x") == "private"
    assert normalize_visibility(None) == "private"
