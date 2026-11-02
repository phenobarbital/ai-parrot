"""Late binding of the credential store on OAuth2 managers."""
from parrot.auth.jira_oauth import JiraOAuthManager


def _mgr(**kw):
    return JiraOAuthManager("id", "secret", "http://localhost/cb", redis_client=object(), **kw)


def test_default_store_is_replaced():
    m = _mgr()
    new = object()
    assert m.bind_credential_store(new) is True
    assert m._store is new
    assert m._store_is_default is False


def test_explicit_store_is_kept():
    explicit = object()
    m = _mgr(credential_store=explicit)
    assert m.bind_credential_store(object()) is False
    assert m._store is explicit


def test_force_replaces_explicit_store():
    m = _mgr(credential_store=object())
    new = object()
    assert m.bind_credential_store(new, force=True) is True
    assert m._store is new
