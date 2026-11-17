"""JiraToolkit.site_url / browse_url when the API runs through the gateway."""

from typing import Any
from unittest.mock import patch

import pytest

from parrot_tools.jiratoolkit import JiraToolkit

GATEWAY = "https://api.atlassian.com/ex/jira/51890c00-e62e-49ed-bb9a-f9404995733c"
SITE = "https://acme.atlassian.net"


class _FakeJIRA:
    """JIRA stand-in: records its server and answers serverInfo."""

    server_info_calls = 0

    def __init__(self, *args: Any, options: dict | None = None, **kwargs: Any) -> None:
        self._options = dict(options or {})

    def server_info(self) -> dict:
        type(self).server_info_calls += 1
        return {"baseUrl": SITE}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("JIRA_INSTANCE", "JIRA_AUTH_TYPE", "JIRA_SITE_URL", "JIRA_KB_PATH"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("parrot_tools.jiratoolkit.nav_config", None, raising=False)
    _FakeJIRA.server_info_calls = 0


def _make(server_url: str, **kwargs: Any) -> JiraToolkit:
    with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
        return JiraToolkit(
            auth_type="basic_auth",
            server_url=server_url,
            username="svc@example.com",
            password="t",
            verify_credentials=False,
            **kwargs,
        )


def test_site_server_url_is_used_directly() -> None:
    tk = _make(SITE + "/")
    assert tk.site_url == SITE
    assert tk.browse_url("NAV-1") == f"{SITE}/browse/NAV-1"
    assert _FakeJIRA.server_info_calls == 0


def test_gateway_server_url_resolves_site_once() -> None:
    tk = _make(GATEWAY)
    assert tk.browse_url("NAV-1") == f"{SITE}/browse/NAV-1"
    assert tk.browse_url("NAV-2") == f"{SITE}/browse/NAV-2"
    assert tk.server_url == GATEWAY
    assert _FakeJIRA.server_info_calls == 1


def test_explicit_site_url_skips_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_SITE_URL", "https://other.atlassian.net")
    tk = _make(GATEWAY)
    assert tk.site_url == "https://other.atlassian.net"
    assert _FakeJIRA.server_info_calls == 0


def test_browse_url_without_key_is_empty() -> None:
    assert _make(SITE).browse_url(None) == ""


def test_site_url_kwarg_skips_lookup() -> None:
    tk = _make(GATEWAY, site_url="https://kw.atlassian.net/")
    assert tk.site_url == "https://kw.atlassian.net"
    assert _FakeJIRA.server_info_calls == 0
