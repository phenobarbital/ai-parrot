"""``fake_broker`` — a real ``CredentialBroker`` for FEAT-455's real-browser
integration tests.

Relocates/generalizes the ``_StaticResolver``/``CredentialBroker.register()``
pattern already proven in
``packages/ai-parrot-tools/tests/scraping/test_authenticate_broker.py``
(FEAT-453 TASK-2389) into a shared fixture — deliberately NOT the
``CredentialBroker.from_config()``/vault-backed construction path (see
``sdd/tasks/completed/TASK-2408-*.md``'s Codebase Contract for the full
rationale: the vault-backed path needs a fake vault dependency this
simpler, already-precedented pattern does not).

**Secret shape note**: unlike ``test_authenticate_broker.py``'s own
``_StaticSecret``/``_BrokerWrapper.as_resolver()`` (an attribute-based,
bespoke adapter), this fixture's resolver returns a **dict**
(``{"username": ..., "password": ...}``) because this task's tests use the
real production adapter,
:func:`parrot_tools.business_automation.toolkit._credential_resolver_from_broker`,
which only recognizes a dict/tuple/str secret shape — not an
attribute-based object.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from parrot.auth.broker import CredentialBroker
from parrot.auth.credentials import CredentialResolver

from tests.scraping.fixtures.local_site import TEST_PASSWORD, TEST_USERNAME

#: The provider identifier this fixture registers — used as
#: ``Authenticate.credential_provider`` in a real end-to-end plan.
FAKE_BROKER_PROVIDER = "acme"


class _StaticDictResolver(CredentialResolver):
    """Always resolves to a static ``{"username", "password"}`` dict —
    the exact shape :func:`_credential_resolver_from_broker` recognizes.
    """

    def __init__(self, username: str, password: str) -> None:
        self._secret = {"username": username, "password": password}

    async def resolve(self, channel: str, user_id: str) -> Any | None:
        return self._secret

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        raise NotImplementedError("static credentials do not require authorization")


@pytest.fixture
def fake_broker() -> CredentialBroker:
    """A real :class:`CredentialBroker` with one ``"acme"`` provider
    resolving to :data:`~tests.scraping.fixtures.local_site.TEST_USERNAME`/
    :data:`TEST_PASSWORD` — the exact credential
    :func:`~tests.scraping.fixtures.local_site.local_fixture_site`'s
    ``/login`` route accepts, so a real end-to-end login actually succeeds.
    """
    broker = CredentialBroker(audit_ledger=AsyncMock())
    broker.register(
        FAKE_BROKER_PROVIDER,
        _StaticDictResolver(TEST_USERNAME, TEST_PASSWORD),
        auth_kind="static_key",
    )
    return broker
