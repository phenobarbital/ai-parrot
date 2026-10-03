"""Regression cases for FEAT-627."""

from pathlib import Path

import pytest

import parrot.interfaces.jira.client as subject


class _Response:
    """Synthetic synchronous Jira response."""

    def __init__(self, status_code: int, payload: dict[str, str], headers: dict[str, str] | None = None) -> None:
        """Initialize the response payload and HTTP metadata."""
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self) -> dict[str, str]:
        """Return the synthetic Jira response body."""
        return self._payload


class _Session:
    """Synthetic Jira session that records the one expected probe."""

    def __init__(self, response: _Response) -> None:
        """Initialize with the response returned by the probe."""
        self.response = response
        self.urls: list[str] = []

    def get(self, url: str) -> _Response:
        """Return the configured response without network access."""
        self.urls.append(url)
        return self.response


class _Client:
    """Minimal pycontribs-compatible client fixture."""

    def __init__(self, response: _Response) -> None:
        """Initialize the synthetic client's session and server options."""
        self._options = {"server": "https://example.atlassian.net"}
        self._session = _Session(response)


@pytest.mark.asyncio
async def test_myself_g9_projection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify myself projects only G9-safe identity fields."""
    assert tmp_path.exists()
    response = _Response(
        200,
        {"accountId": "account-1", "displayName": "Ada Lovelace", "emailAddress": "ada@example.test"},
    )
    iface = subject.JiraInterface(auth_type="token_auth", token="token", verify_credentials=False)
    client = _Client(response)
    iface.attach_client(client)
    ensured = False
    original_ensure_client = iface._ensure_client

    async def ensure_client() -> _Client:
        nonlocal ensured
        ensured = True
        return await original_ensure_client()

    monkeypatch.setattr(iface, "_ensure_client", ensure_client)

    person = await iface.myself()
    probe = await iface._probe_myself()

    assert ensured
    assert person.model_dump() == {"account_id": "account-1", "display_name": "Ada Lovelace"}
    assert "emailAddress" not in person.model_dump()
    assert probe == {
        "authenticated": True,
        "status_code": 200,
        "seraph_login_reason": None,
        "account_id": "account-1",
        "display_name": "Ada Lovelace",
    }
    assert all("emailAddress" not in str(value) for value in probe.values())
    assert client._session.urls == [
        "https://example.atlassian.net/rest/api/2/myself",
        "https://example.atlassian.net/rest/api/2/myself",
    ]


@pytest.mark.asyncio
async def test_auth_and_malformed_user_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify auth and malformed user failures."""
    assert tmp_path.exists()
    cases = (
        _Response(401, {"emailAddress": "denied@example.test"}),
        _Response(403, {"emailAddress": "denied@example.test"}),
        _Response(
            200,
            {"accountId": "account-1", "displayName": "Ada", "emailAddress": "denied@example.test"},
            {"X-Seraph-Loginreason": "AUTHENTICATED_FAILED"},
        ),
        _Response(200, {"emailAddress": "malformed@example.test"}),
    )

    for response in cases:
        iface = subject.JiraInterface(auth_type="token_auth", token="token", verify_credentials=False)
        iface.attach_client(_Client(response))
        with pytest.raises(subject.JiraAuthError):
            await iface.myself()
