"""Unit tests for _GitHubAppTokenProvider (FEAT-179, TASK-1207)."""
from __future__ import annotations

import datetime as _dt
from unittest.mock import patch, MagicMock

import pytest

from parrot_tools.gittoolkit import GitToolkitError
# _GitHubAppTokenProvider is private — import via attribute access on the module:
from parrot_tools import gittoolkit as gt


@pytest.fixture
def fake_pem() -> str:
    """Generate an in-memory RSA PEM. PyGithub will not actually parse it
    in unit tests because we mock GithubIntegration entirely."""
    return (
        "-----BEGIN PRIVATE KEY-----\n"
        "FAKE-DOES-NOT-NEED-TO-PARSE\n"
        "-----END PRIVATE KEY-----\n"
    )


def _mock_installation_auth(token: str, expires_in_seconds: int) -> MagicMock:
    inst = MagicMock()
    inst.token = token
    inst.expires_at = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(
        seconds=expires_in_seconds
    )
    return inst


class TestGitHubAppTokenProvider:

    def test_first_call_mints_token(self, fake_pem):
        """First get_token() call invokes GithubIntegration once."""
        provider = gt._GitHubAppTokenProvider(
            app_id=12345, installation_id=67890, private_key_pem=fake_pem,
        )
        with patch.object(gt, "GithubIntegration") as gi_cls:
            gi_cls.return_value.get_access_token.return_value = (
                _mock_installation_auth("ghs_abc", expires_in_seconds=3600)
            )
            token = provider.get_token()
        assert token == "ghs_abc"
        gi_cls.return_value.get_access_token.assert_called_once_with(67890)

    def test_caches_until_near_expiry(self, fake_pem):
        """Second get_token() within the validity window does NOT re-mint."""
        provider = gt._GitHubAppTokenProvider(12345, 67890, fake_pem)
        with patch.object(gt, "GithubIntegration") as gi_cls:
            gi_cls.return_value.get_access_token.return_value = (
                _mock_installation_auth("ghs_abc", expires_in_seconds=3600)
            )
            provider.get_token()
            provider.get_token()
        # Only one mint despite two get_token() calls.
        assert gi_cls.return_value.get_access_token.call_count == 1

    def test_refreshes_when_near_expiry(self, fake_pem):
        """When cached token is <=60s from expiry, get_token() re-mints."""
        provider = gt._GitHubAppTokenProvider(12345, 67890, fake_pem)
        with patch.object(gt, "GithubIntegration") as gi_cls:
            gi_cls.return_value.get_access_token.side_effect = [
                _mock_installation_auth("ghs_old", expires_in_seconds=30),
                _mock_installation_auth("ghs_new", expires_in_seconds=3600),
            ]
            first = provider.get_token()
            second = provider.get_token()
        assert first == "ghs_old"
        assert second == "ghs_new"
        assert gi_cls.return_value.get_access_token.call_count == 2

    def test_mint_failure_raises_gittoolkit_error(self, fake_pem):
        """A PyGithub exception is wrapped in GitToolkitError."""
        provider = gt._GitHubAppTokenProvider(12345, 67890, fake_pem)
        with patch.object(gt, "GithubIntegration") as gi_cls:
            gi_cls.return_value.get_access_token.side_effect = RuntimeError(
                "401 Bad credentials"
            )
            with pytest.raises(GitToolkitError, match="401 Bad credentials"):
                provider.get_token()

    def test_uses_app_auth_with_app_id_and_pem(self, fake_pem):
        """Provider hands (app_id, pem) to Auth.AppAuth on each refresh."""
        provider = gt._GitHubAppTokenProvider(12345, 67890, fake_pem)
        with patch.object(gt, "GithubIntegration") as gi_cls, patch.object(
            gt, "Auth"
        ) as auth_mod:
            gi_cls.return_value.get_access_token.return_value = (
                _mock_installation_auth("ghs_abc", 3600)
            )
            provider.get_token()
        auth_mod.AppAuth.assert_called_once_with(12345, fake_pem)
        gi_cls.assert_called_once_with(auth=auth_mod.AppAuth.return_value)
