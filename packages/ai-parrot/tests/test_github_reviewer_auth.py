"""Unit tests for GitHubReviewer._build_git_toolkit auth_type routing (FEAT-179, TASK-1209)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from parrot.bots.github_reviewer import GitHubReviewer
from parrot_tools.gittoolkit import GitToolkit


PEM_SENTINEL = (
    "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n"
)


def _make_reviewer() -> GitHubReviewer:
    """Build a bare GitHubReviewer with the minimum scaffolding needed to
    invoke _build_git_toolkit. The reviewer's __init__ pulls in heavy
    dependencies; we bypass it via __new__ + manual attribute setup."""
    reviewer = GitHubReviewer.__new__(GitHubReviewer)
    reviewer.repository = "owner/repo"
    reviewer.logger = MagicMock()
    return reviewer


class TestBuildGitToolkitAuthType:

    def test_pat_mode_default_with_token(self):
        """No GITHUB_AUTH_TYPE → PAT mode, token present → toolkit built."""
        reviewer = _make_reviewer()

        def fake_config_get(key, fallback=None):
            return {
                "GITHUB_TOKEN": "pat_xxx",
                "GIT_DEFAULT_BRANCH": "main",
            }.get(key, fallback)

        with patch(
            "parrot.bots.github_reviewer.config.get", side_effect=fake_config_get
        ):
            tk = reviewer._build_git_toolkit()
        assert isinstance(tk, GitToolkit)
        assert tk.auth_type == "pat"
        assert tk.github_token == "pat_xxx"

    def test_pat_mode_missing_token_disables(self):
        reviewer = _make_reviewer()
        with patch(
            "parrot.bots.github_reviewer.config.get", return_value=None,
        ):
            tk = reviewer._build_git_toolkit()
        assert tk is None
        reviewer.logger.error.assert_called()
        args, _ = reviewer.logger.error.call_args
        assert "GITHUB_TOKEN" in args[0]

    def test_app_mode_full_config_builds_toolkit(self):
        reviewer = _make_reviewer()
        env = {
            "GITHUB_AUTH_TYPE": "github_app",
            "GITHUB_APP_ID": "12345",
            "GITHUB_APP_INSTALLATION_ID": "67890",
            "GITHUB_APP_PRIVATE_KEY": PEM_SENTINEL,
        }
        with patch(
            "parrot.bots.github_reviewer.config.get",
            side_effect=lambda k, fallback=None: env.get(k, fallback),
        ):
            tk = reviewer._build_git_toolkit()
        assert isinstance(tk, GitToolkit)
        assert tk.auth_type == "github_app"
        assert tk.app_id == 12345
        assert tk.installation_id == 67890

    def test_app_mode_with_private_key_path(self, tmp_path):
        reviewer = _make_reviewer()
        key_file = tmp_path / "key.pem"
        key_file.write_text(PEM_SENTINEL)
        env = {
            "GITHUB_AUTH_TYPE": "github_app",
            "GITHUB_APP_ID": "12345",
            "GITHUB_APP_INSTALLATION_ID": "67890",
            "GITHUB_APP_PRIVATE_KEY_PATH": str(key_file),
        }
        with patch(
            "parrot.bots.github_reviewer.config.get",
            side_effect=lambda k, fallback=None: env.get(k, fallback),
        ):
            tk = reviewer._build_git_toolkit()
        assert isinstance(tk, GitToolkit)
        assert tk.auth_type == "github_app"

    @pytest.mark.parametrize("missing", [
        "GITHUB_APP_ID",
        "GITHUB_APP_INSTALLATION_ID",
        "GITHUB_APP_PRIVATE_KEY",
    ])
    def test_app_mode_missing_required_var_disables(self, missing):
        reviewer = _make_reviewer()
        env = {
            "GITHUB_AUTH_TYPE": "github_app",
            "GITHUB_APP_ID": "12345",
            "GITHUB_APP_INSTALLATION_ID": "67890",
            "GITHUB_APP_PRIVATE_KEY": PEM_SENTINEL,
        }
        env.pop(missing)
        with patch(
            "parrot.bots.github_reviewer.config.get",
            side_effect=lambda k, fallback=None: env.get(k, fallback),
        ):
            tk = reviewer._build_git_toolkit()
        assert tk is None
        reviewer.logger.error.assert_called()

    def test_unknown_auth_type_disables(self):
        reviewer = _make_reviewer()
        env = {"GITHUB_AUTH_TYPE": "oauth"}
        with patch(
            "parrot.bots.github_reviewer.config.get",
            side_effect=lambda k, fallback=None: env.get(k, fallback),
        ):
            tk = reviewer._build_git_toolkit()
        assert tk is None
        args, _ = reviewer.logger.error.call_args
        assert "unknown GITHUB_AUTH_TYPE" in args[0]

    def test_app_mode_constructor_failure_is_caught(self):
        """If GitToolkit.__init__ raises (e.g. bad int), the
        reviewer logs and disables — does not propagate."""
        reviewer = _make_reviewer()
        env = {
            "GITHUB_AUTH_TYPE": "github_app",
            "GITHUB_APP_ID": "not-an-int",  # int() will raise
            "GITHUB_APP_INSTALLATION_ID": "67890",
            "GITHUB_APP_PRIVATE_KEY": PEM_SENTINEL,
        }
        with patch(
            "parrot.bots.github_reviewer.config.get",
            side_effect=lambda k, fallback=None: env.get(k, fallback),
        ):
            tk = reviewer._build_git_toolkit()
        assert tk is None
        reviewer.logger.error.assert_called()
