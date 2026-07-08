"""Unit tests for _GitHubAppTokenProvider and GitToolkit auth modes (FEAT-179).

TASK-1207: TestGitHubAppTokenProvider
TASK-1208: TestGitToolkitAuthMode
"""
from __future__ import annotations

import datetime as _dt
import os
from unittest.mock import MagicMock, patch

import pytest

from parrot_tools import gittoolkit as gt
from parrot_tools.gittoolkit import GitToolkit, GitToolkitError


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

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


# Sentinel PEM used across TASK-1208 tests.
PEM_SENTINEL = (
    "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n"
)


# ---------------------------------------------------------------------------
# TASK-1207: _GitHubAppTokenProvider
# ---------------------------------------------------------------------------

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

    def test_concurrent_calls_mint_once(self, fake_pem):
        """Concurrent get_token() calls from multiple threads do not double-mint."""
        import concurrent.futures
        from unittest.mock import MagicMock, patch

        provider = gt._GitHubAppTokenProvider(12345, 67890, fake_pem)

        mock_auth = MagicMock()
        mock_auth.token = "ghs_concurrent"
        import datetime as _dt
        mock_auth.expires_at = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=1)

        with patch.object(gt, "GithubIntegration") as gi_cls:
            gi_cls.return_value.get_access_token.return_value = mock_auth
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                tokens = list(pool.map(lambda _: provider.get_token(), range(8)))

        assert all(t == "ghs_concurrent" for t in tokens)
        assert gi_cls.return_value.get_access_token.call_count == 1


# ---------------------------------------------------------------------------
# TASK-1208: GitToolkit auth_type plumbing
# ---------------------------------------------------------------------------

class TestGitToolkitAuthMode:

    # --- PAT mode regression -----------------------------------------

    def test_pat_mode_default(self):
        """auth_type defaults to 'pat' and existing usage works."""
        tk = GitToolkit(default_repository="o/r", github_token="pat_xxx")
        assert tk.auth_type == "pat"
        assert tk._token_provider is None
        assert tk._bearer_token() == "pat_xxx"

    def test_pat_mode_missing_token_raises_on_demand(self):
        """PAT mode does NOT raise at construction; raises on first call."""
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            tk = GitToolkit(default_repository="o/r")
            # Construction succeeds
            assert tk.auth_type == "pat"
            with pytest.raises(GitToolkitError, match="personal access token"):
                tk._bearer_token()

    def test_pat_mode_ignores_app_kwargs(self):
        """auth_type='pat' silently accepts (ignores) App-mode kwargs."""
        tk = GitToolkit(
            default_repository="o/r",
            github_token="pat_xxx",
            app_id=12345,
            installation_id=67890,
            private_key=PEM_SENTINEL,
        )
        assert tk.auth_type == "pat"
        assert tk._token_provider is None

    # --- auth_type validation ----------------------------------------

    def test_invalid_auth_type_raises(self):
        with pytest.raises(GitToolkitError, match="Unsupported auth_type"):
            GitToolkit(default_repository="o/r", auth_type="oauth")  # type: ignore[arg-type]

    # --- App-mode required fields ------------------------------------

    def test_app_mode_missing_app_id_raises(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("GITHUB_APP_ID", "GITHUB_APP_INSTALLATION_ID",
                            "GITHUB_APP_PRIVATE_KEY", "GITHUB_APP_PRIVATE_KEY_PATH")}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(GitToolkitError, match="app_id"):
                GitToolkit(
                    default_repository="o/r",
                    auth_type="github_app",
                    installation_id=67890,
                    private_key=PEM_SENTINEL,
                )

    def test_app_mode_missing_installation_id_raises(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("GITHUB_APP_ID", "GITHUB_APP_INSTALLATION_ID",
                            "GITHUB_APP_PRIVATE_KEY", "GITHUB_APP_PRIVATE_KEY_PATH")}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(GitToolkitError, match="installation_id"):
                GitToolkit(
                    default_repository="o/r",
                    auth_type="github_app",
                    app_id=12345,
                    private_key=PEM_SENTINEL,
                )

    def test_app_mode_missing_key_raises(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("GITHUB_APP_ID", "GITHUB_APP_INSTALLATION_ID",
                            "GITHUB_APP_PRIVATE_KEY", "GITHUB_APP_PRIVATE_KEY_PATH")}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(GitToolkitError, match="private_key"):
                GitToolkit(
                    default_repository="o/r",
                    auth_type="github_app",
                    app_id=12345,
                    installation_id=67890,
                )

    def test_app_mode_rejects_both_keys(self, tmp_path):
        key_file = tmp_path / "key.pem"
        key_file.write_text(PEM_SENTINEL)
        with pytest.raises(GitToolkitError, match="EITHER"):
            GitToolkit(
                default_repository="o/r",
                auth_type="github_app",
                app_id=12345,
                installation_id=67890,
                private_key=PEM_SENTINEL,
                private_key_path=str(key_file),
            )

    # --- App-mode happy path -----------------------------------------

    def test_app_mode_builds_token_provider(self):
        tk = GitToolkit(
            default_repository="o/r",
            auth_type="github_app",
            app_id=12345,
            installation_id=67890,
            private_key=PEM_SENTINEL,
        )
        assert tk.auth_type == "github_app"
        assert isinstance(tk._token_provider, gt._GitHubAppTokenProvider)

    def test_app_mode_loads_pem_from_path(self, tmp_path):
        key_file = tmp_path / "key.pem"
        key_file.write_text(PEM_SENTINEL)
        tk = GitToolkit(
            default_repository="o/r",
            auth_type="github_app",
            app_id=12345,
            installation_id=67890,
            private_key_path=str(key_file),
        )
        # PEM lives inside _token_provider; GitToolkit no longer keeps a copy.
        assert tk._token_provider._private_key_pem == PEM_SENTINEL

    def test_app_mode_replaces_literal_backslash_n(self):
        """Env-injected PEMs with literal '\\n' are normalised to real newlines."""
        pem_with_escapes = (
            "-----BEGIN PRIVATE KEY-----\\nFAKE\\n-----END PRIVATE KEY-----\\n"
        )
        tk = GitToolkit(
            default_repository="o/r",
            auth_type="github_app",
            app_id=12345,
            installation_id=67890,
            private_key=pem_with_escapes,
        )
        # PEM lives inside _token_provider; GitToolkit no longer keeps a copy.
        assert "\\n" not in tk._token_provider._private_key_pem
        assert "\n" in tk._token_provider._private_key_pem

    # --- _bearer_token routing ---------------------------------------

    def test_bearer_token_app_mode_delegates_to_provider(self):
        tk = GitToolkit(
            default_repository="o/r",
            auth_type="github_app",
            app_id=12345,
            installation_id=67890,
            private_key=PEM_SENTINEL,
        )
        with patch.object(tk._token_provider, "get_token", return_value="ghs_xxx"):
            assert tk._bearer_token() == "ghs_xxx"

    @pytest.mark.asyncio
    async def test_request_uses_app_bearer(self):
        """End-to-end: an HTTP method emits Authorization: Bearer <app-token>."""
        tk = GitToolkit(
            default_repository="o/r",
            auth_type="github_app",
            app_id=12345,
            installation_id=67890,
            private_key=PEM_SENTINEL,
        )
        with patch.object(tk._token_provider, "get_token", return_value="ghs_xxx"):
            with patch("parrot_tools.gittoolkit.requests.request") as req:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {}
                req.return_value = mock_resp
                await tk.get_pull_request(pr_number=42)
        call = req.call_args
        assert call.kwargs["headers"]["Authorization"] == "Bearer ghs_xxx"


class TestNoDefaultAuthFallback:
    """The toolkit no longer silently adopts GITHUB_* env credentials. Auth
    must be passed explicitly; otherwise a clear GitToolkitError surfaces to
    the LLM at call time instead of the toolkit acting as a shared account."""

    def test_pat_env_token_no_longer_used(self):
        """A GITHUB_TOKEN in the environment is NOT silently adopted."""
        with patch.dict(os.environ, {"GITHUB_TOKEN": "env_pat"}, clear=False):
            tk = GitToolkit(default_repository="o/r")
        assert tk.github_token is None
        with pytest.raises(GitToolkitError, match="explicitly"):
            tk._bearer_token()

    def test_explicit_pat_still_works_and_ignores_env(self):
        """Regression: an explicit PAT works and env is never consulted."""
        with patch.dict(os.environ, {"GITHUB_TOKEN": "env_pat"}, clear=False):
            tk = GitToolkit(
                default_repository="o/r", github_token="explicit_pat"
            )
        assert tk.github_token == "explicit_pat"
        assert tk._bearer_token() == "explicit_pat"

    def test_ad_hoc_connection_has_no_env_token_fallback(self):
        """Unknown-slug ad-hoc connections also require an explicit token."""
        with patch.dict(os.environ, {"GITHUB_TOKEN": "env_pat"}, clear=False):
            tk = GitToolkit(github_token=None)
            with pytest.raises(GitToolkitError, match="explicitly"):
                tk._resolve_connection("owner/other")

    def test_app_env_ids_no_longer_used(self):
        """GITHUB_APP_* env vars are NOT silently adopted in app mode."""
        env = {
            "GITHUB_APP_ID": "12345",
            "GITHUB_APP_INSTALLATION_ID": "67890",
            "GITHUB_APP_PRIVATE_KEY": PEM_SENTINEL,
        }
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(GitToolkitError, match="app_id"):
                GitToolkit(
                    default_repository="o/r", auth_type="github_app"
                )

    def test_app_env_private_key_no_longer_used(self):
        """GITHUB_APP_PRIVATE_KEY env is ignored; explicit key required."""
        env = {"GITHUB_APP_PRIVATE_KEY": PEM_SENTINEL}
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(GitToolkitError, match="private_key"):
                GitToolkit(
                    default_repository="o/r",
                    auth_type="github_app",
                    app_id=12345,
                    installation_id=67890,
                )
