"""Browser site URL resolution for Jira issue links (gateway vs site)."""

from typing import Any

import pytest

from parrot.interfaces.jira.site import SiteUrlResolver, fetch_site_url, is_gateway_url

GATEWAY = "https://api.atlassian.com/ex/jira/51890c00-e62e-49ed-bb9a-f9404995733c"
SITE = "https://acme.atlassian.net"


class _Client:
    def __init__(self, info: Any = None, exc: Exception | None = None) -> None:
        self.info = info if info is not None else {"baseUrl": SITE + "/"}
        self.exc = exc
        self.calls = 0

    def server_info(self) -> Any:
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.info


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (GATEWAY, True),
        (GATEWAY + "/", True),
        (SITE, False),
        ("https://api.atlassian.com/ex/confluence/abc", False),
        ("", False),
        (None, False),
    ],
)
def test_is_gateway_url(url: Any, expected: bool) -> None:
    assert is_gateway_url(url) is expected


def test_fetch_site_url_reads_base_url() -> None:
    assert fetch_site_url(_Client()) == SITE


@pytest.mark.parametrize("info", [{}, {"baseUrl": ""}, {"baseUrl": GATEWAY}, "nope"])
def test_fetch_site_url_rejects_unusable_payloads(info: Any) -> None:
    assert fetch_site_url(_Client(info=info)) is None


def test_fetch_site_url_swallows_errors() -> None:
    assert fetch_site_url(_Client(exc=RuntimeError("401"))) is None
    assert fetch_site_url(None) is None


def test_site_server_url_is_returned_without_lookup() -> None:
    client = _Client()
    assert SiteUrlResolver().resolve(client, SITE + "/") == SITE
    assert client.calls == 0


def test_gateway_resolves_through_server_info_once() -> None:
    client = _Client()
    resolver = SiteUrlResolver()
    assert resolver.resolve(client, GATEWAY) == SITE
    assert resolver.resolve(client, GATEWAY) == SITE
    assert client.calls == 1


def test_explicit_site_wins() -> None:
    client = _Client()
    assert SiteUrlResolver("https://other.atlassian.net/").resolve(client, GATEWAY) == "https://other.atlassian.net"
    assert client.calls == 0


def test_failed_lookup_falls_back_to_api_base_and_retries() -> None:
    client = _Client(exc=RuntimeError("boom"))
    resolver = SiteUrlResolver()
    assert resolver.resolve(client, GATEWAY) == GATEWAY
    assert resolver.resolve(client, GATEWAY) == GATEWAY
    assert client.calls == 2


def test_browse_url() -> None:
    assert SiteUrlResolver.browse_url(SITE + "/", "NAV-1") == f"{SITE}/browse/NAV-1"
    assert SiteUrlResolver.browse_url("", "NAV-1") == ""
    assert SiteUrlResolver.browse_url(SITE, None) == ""
