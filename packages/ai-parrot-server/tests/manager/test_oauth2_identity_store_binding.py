"""BotManager binds IdentityVaultCredentialStore onto default-store managers."""
import logging

import pytest
from aiohttp import web

from parrot.auth.jira_oauth import JiraOAuthManager
from parrot.manager.manager import BotManager
from parrot.services.identity_credential_sink import IdentityVaultCredentialStore


def _mgr(**kw):
    return JiraOAuthManager("id", "secret", "http://localhost/cb", redis_client=object(), **kw)


def _bm():
    bm = BotManager.__new__(BotManager)
    bm.logger = logging.getLogger("test")
    bm._register_descriptor_oauth2_providers = lambda app, **kwargs: None
    return bm


@pytest.fixture(autouse=True)
def _no_backends(monkeypatch):
    monkeypatch.setattr("parrot.auth.oauth2.registry.register_oauth2_provider", lambda p: None)
    monkeypatch.setattr("parrot.auth.principal.set_principal_resolver", lambda r: None)


@pytest.mark.asyncio
async def test_binds_default_managers_only():
    app = web.Application()
    app["authdb"] = object()
    jira, o365, explicit = _mgr(), _mgr(), _mgr(credential_store=object())
    keep = explicit._store
    app["jira_oauth_manager"] = jira
    app["oauth2_manager_o365"] = o365
    app["oauth2_manager_x"] = explicit
    await BotManager._register_oauth2_providers(_bm(), app)
    assert isinstance(jira._store, IdentityVaultCredentialStore)
    assert isinstance(o365._store, IdentityVaultCredentialStore)
    assert explicit._store is keep


@pytest.mark.asyncio
async def test_no_authdb_leaves_stores():
    app = web.Application()
    jira = _mgr()
    before = jira._store
    app["jira_oauth_manager"] = jira
    await BotManager._register_oauth2_providers(_bm(), app)
    assert jira._store is before
