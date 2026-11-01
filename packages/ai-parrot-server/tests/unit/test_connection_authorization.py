"""NavigatorConnectionAuthorizer against a real PolicyEvaluator (FEAT-777 AC-14)."""

from __future__ import annotations

from typing import Any, Dict

import pytest
from navigator_auth import conf
from navigator_auth.abac.policies.abstract import PolicyEffect
from navigator_auth.abac.policies.evaluator import PolicyEvaluator
from navigator_auth.abac.policies.resource_policy import ResourcePolicy

from parrot.auth.principal import Principal
from parrot.services.connection_authorization import NavigatorConnectionAuthorizer


class FakePDP:
    """Hold a shared evaluator plus tenant evaluators like navigator-auth's PDP."""

    def __init__(self, shared: PolicyEvaluator, tenants: Dict[tuple[int, int], PolicyEvaluator]) -> None:
        """Initialize evaluator storage."""
        self.evaluator = shared
        self._tenants = tenants

    async def _get_tenant_evaluator(self, org_id: int, client_id: int) -> PolicyEvaluator:
        """Return the matching tenant evaluator or the PDP-style shared fallback."""
        return self._tenants.get((org_id, client_id), self.evaluator)


@pytest.fixture
def principal() -> Principal:
    """Return a linked Slack principal."""
    return Principal(user_id="1042", channel="slack", channel_user_id="T01:U02")


def _allow_connect(org_id: int, client_id: int) -> PolicyEvaluator:
    """Create a real tenant-scoped integration allow evaluator."""
    evaluator = PolicyEvaluator(cache_size=8, cache_ttl_seconds=1)
    evaluator.load_policies(
        [
            ResourcePolicy(
                name="allow_jira_connect",
                effect=PolicyEffect.ALLOW,
                resources=["integration:jira"],
                actions=["integration:connect"],
                subjects={"groups": ["*"]},
                org_id=org_id,
                client_id=client_id,
            )
        ]
    )
    return evaluator


async def _current_binding(_: Principal) -> bool:
    """Represent an unchanged exclusive principal binding."""
    return True


def _trusted_user(org_id: int | None = 2, client_id: int | None = 5, **extra: Any) -> dict[str, Any]:
    """Build a trusted auth-storage row for adapter tests."""
    return {
        "user_id": 1042,
        "email": "user@example.test",
        "is_active": True,
        "org_id": org_id,
        "client_id": client_id,
        "groups": ["staff"],
        "roles": ["staff"],
        **extra,
    }


async def test_allowed_tenant(principal: Principal, monkeypatch: pytest.MonkeyPatch) -> None:
    """A matching tenant policy explicitly allows the integration action."""
    monkeypatch.setattr(conf, "ABAC_TENANT_SQL_FILTERING", True)
    authorizer = NavigatorConnectionAuthorizer(
        {"abac": FakePDP(PolicyEvaluator(), {(2, 5): _allow_connect(2, 5)}), "authdb": object()}
    )

    async def load_user(_: str) -> dict[str, Any]:
        return _trusted_user()

    monkeypatch.setattr(authorizer, "_load_trusted_user", load_user)
    monkeypatch.setattr(authorizer, "_binding_is_current", _current_binding)

    assert await authorizer.authorize(principal, "integration:connect", "jira", ["read:jira-work"]) is True


async def test_denied_other_tenant(principal: Principal, monkeypatch: pytest.MonkeyPatch) -> None:
    """A tenant lacking a matching evaluator cannot fall back to global policy."""
    monkeypatch.setattr(conf, "ABAC_TENANT_SQL_FILTERING", True)
    authorizer = NavigatorConnectionAuthorizer(
        {"abac": FakePDP(PolicyEvaluator(), {(2, 5): _allow_connect(2, 5)}), "authdb": object()}
    )

    async def load_user(_: str) -> dict[str, Any]:
        return _trusted_user(3, 7)

    monkeypatch.setattr(authorizer, "_load_trusted_user", load_user)
    monkeypatch.setattr(authorizer, "_binding_is_current", _current_binding)

    assert await authorizer.authorize(principal, "integration:connect", "jira", ["read:jira-work"]) is False


@pytest.mark.parametrize("case", ["no_pdp", "no_user", "inactive", "stale_binding", "no_tenant", "error", "deny"])
async def test_fail_closed(case: str, principal: Principal, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every missing, stale, error, or denied authorization condition rejects access."""
    monkeypatch.setattr(conf, "ABAC_TENANT_SQL_FILTERING", True)
    pdp = FakePDP(PolicyEvaluator(), {(2, 5): _allow_connect(2, 5)})
    app: dict[str, Any] = {"abac": pdp, "authdb": object()}
    if case == "no_pdp":
        app.pop("abac")
    authorizer = NavigatorConnectionAuthorizer(app)

    async def load_user(_: str) -> dict[str, Any] | None:
        if case == "no_user":
            return None
        if case == "inactive":
            return _trusted_user(is_active=False)
        if case == "no_tenant":
            return _trusted_user(None, None)
        return _trusted_user()

    async def binding(_: Principal) -> bool:
        return case != "stale_binding"

    monkeypatch.setattr(authorizer, "_load_trusted_user", load_user)
    monkeypatch.setattr(authorizer, "_binding_is_current", binding)
    if case == "error":

        async def broken_evaluator(*_: Any) -> Any:
            raise RuntimeError("tenant evaluator unavailable")

        monkeypatch.setattr(authorizer, "_select_evaluator", broken_evaluator)
    if case == "deny":
        pdp._tenants[(2, 5)] = PolicyEvaluator()

    assert await authorizer.authorize(principal, "integration:connect", "jira", []) is False


def test_truthy_result_object_is_not_allow() -> None:
    """A truthy non-boolean allowed attribute cannot bypass explicit ALLOW checking."""

    class Truthy:
        """Mimic an incorrectly truthy evaluator result."""

        allowed = 1
        effect = PolicyEffect.ALLOW

    assert NavigatorConnectionAuthorizer._is_explicit_allow(Truthy()) is False
