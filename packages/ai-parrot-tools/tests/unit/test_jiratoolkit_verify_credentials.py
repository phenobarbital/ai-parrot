"""Unit tests for eager static-credential verification in :class:`JiraToolkit`.

Jira Cloud silently downgrades a session with a bad username/token pair to
*anonymous* (``X-Seraph-Loginreason: AUTHENTICATED_FAILED``) instead of
returning HTTP 401, which later produces misleading errors such as
"No project could be found with key 'X'". The toolkit now probes
``/rest/api/2/myself`` at construction time and raises
:class:`JiraAuthenticationError` on a definitive rejection.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from parrot_tools.jiratoolkit import JiraAuthenticationError, JiraToolkit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal stand-in for a ``requests.Response`` from the JIRA session."""

    def __init__(self, status_code=200, headers=None, body=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("no json body")
        return self._body


def _fake_client(response=None, get_side_effect=None) -> MagicMock:
    """A mocked ``jira.JIRA`` instance whose session returns ``response``."""
    client = MagicMock()
    client._options = {"server": "https://test.atlassian.net"}
    if get_side_effect is not None:
        client._session.get.side_effect = get_side_effect
    else:
        client._session.get.return_value = response
    return client


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    """Keep developer Jira config (env vars / navconfig) out of the tests."""
    for var in (
        "JIRA_INSTANCE", "JIRA_URL", "JIRA_AUTH_TYPE", "JIRA_USERNAME",
        "JIRA_PASSWORD", "JIRA_API_TOKEN", "JIRA_SECRET_TOKEN",
        "JIRA_DEFAULT_PROJECT", "JIRA_PROJECT",
    ):
        monkeypatch.delenv(var, raising=False)
    with patch("parrot_tools.jiratoolkit.nav_config", None):
        yield


def _build_toolkit(client: MagicMock, **kwargs) -> JiraToolkit:
    with patch("parrot_tools.jiratoolkit.JIRA", return_value=client):
        return JiraToolkit(
            server_url="https://test.atlassian.net",
            auth_type="basic_auth",
            username="user@example.com",
            password="api-token",
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Definitive rejections raise at construction time
# ---------------------------------------------------------------------------


class TestRejectedCredentialsRaise:
    def test_seraph_authenticated_failed_raises(self):
        """Jira Cloud's silent anonymous downgrade (200 + Seraph header)."""
        client = _fake_client(_FakeResponse(
            status_code=200,
            headers={"X-Seraph-Loginreason": "AUTHENTICATED_FAILED"},
            body={"errorMessages": []},
        ))
        with pytest.raises(JiraAuthenticationError, match="rejected the configured credentials"):
            _build_toolkit(client)

    def test_http_401_raises(self):
        client = _fake_client(_FakeResponse(
            status_code=401,
            text="Client must be authenticated to access this resource.",
        ))
        with pytest.raises(JiraAuthenticationError):
            _build_toolkit(client)

    def test_error_is_not_a_valueerror(self):
        """Must NOT subclass ValueError — __init__ downgrades ValueError to a
        deferred ``_auth_error`` instead of raising, which would silently
        re-introduce the anonymous-session behaviour."""
        assert not issubclass(JiraAuthenticationError, ValueError)


# ---------------------------------------------------------------------------
# Valid credentials and opt-out
# ---------------------------------------------------------------------------


class TestAcceptedOrSkipped:
    def test_valid_credentials_construct_normally(self):
        client = _fake_client(_FakeResponse(
            status_code=200,
            headers={},
            body={"accountId": "557058:abc", "displayName": "User"},
        ))
        toolkit = _build_toolkit(client)
        assert toolkit.jira is client
        assert toolkit._auth_error is None
        client._session.get.assert_called_once()

    def test_verify_credentials_false_skips_probe(self):
        client = _fake_client(_FakeResponse(status_code=401))
        toolkit = _build_toolkit(client, verify_credentials=False)
        assert toolkit.jira is client
        client._session.get.assert_not_called()


# ---------------------------------------------------------------------------
# Non-verdicts never block construction
# ---------------------------------------------------------------------------


class TestTransportFailuresDoNotRaise:
    def test_connection_error_warns_and_continues(self):
        client = _fake_client(get_side_effect=ConnectionError("network down"))
        toolkit = _build_toolkit(client)
        assert toolkit.jira is client

    def test_probe_crash_warns_and_continues(self):
        """A bare MagicMock client (the pattern used by many existing unit
        tests) must not explode during verification."""
        client = MagicMock()  # headers/dict() interactions raise TypeError
        toolkit = _build_toolkit(client)
        assert toolkit.jira is client
