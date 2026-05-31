"""Unit tests for GitToolkit's multi-repository credentials registry.

The registry lets a single ``GitToolkit`` reference several repositories by
alias, each with its own credentials. Every tool call re-resolves the
connection for the named repository ("re-connect per operation"), so the
correct token is used per request.

Network calls are mocked at ``requests.request`` so the tests stay hermetic;
GitHub App token providers are patched via ``GithubIntegration``.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from parrot_tools import gittoolkit as gt
from parrot_tools.gittoolkit import (
    GitToolkit,
    GitToolkitError,
    RepositoryCredential,
)


def _make_response(status_code: int = 200, json_data=None, text: str = ""):
    class _Resp:
        def __init__(self):
            self.status_code = status_code
            self._json = json_data
            self.text = text
            self.headers = {}

        def json(self):
            return self._json

    return _Resp()


def _mock_installation_auth(token: str, expires_in_seconds: int = 3600) -> MagicMock:
    inst = MagicMock()
    inst.token = token
    inst.expires_at = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(
        seconds=expires_in_seconds
    )
    return inst


PEM = "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n"


# ---------------------------------------------------------------------------
# Registry construction + resolution
# ---------------------------------------------------------------------------

class TestRegistryResolution:
    def test_build_from_dict_and_model(self):
        tk = GitToolkit(
            repositories={
                "a": {"repository": "org/a", "github_token": "ta"},
                "b": RepositoryCredential(repository="org/b", github_token="tb"),
            }
        )
        conn_a = tk._resolve_connection("a")
        conn_b = tk._resolve_connection("b")
        assert (conn_a.repository, conn_a.token()) == ("org/a", "ta")
        assert (conn_b.repository, conn_b.token()) == ("org/b", "tb")

    def test_raw_slug_resolves_to_registered_connection(self):
        tk = GitToolkit(
            repositories={"a": {"repository": "org/a", "github_token": "ta"}}
        )
        # Passing the raw slug of a registered repo uses its dedicated creds.
        assert tk._resolve_connection("org/a") is tk._resolve_connection("a")
        assert tk._resolve_connection("org/a").token() == "ta"

    def test_none_resolves_default_entry(self):
        tk = GitToolkit(default_repository="org/d", github_token="g")
        conn = tk._resolve_connection(None)
        assert conn.repository == "org/d"
        assert conn.token() == "g"

    def test_none_without_default_raises(self):
        tk = GitToolkit(
            repositories={"a": {"repository": "org/a", "github_token": "ta"}}
        )
        with pytest.raises(GitToolkitError):
            tk._resolve_connection(None)

    def test_default_alias_collision_raises(self):
        with pytest.raises(GitToolkitError):
            GitToolkit(
                default_repository="org/d",
                github_token="g",
                repositories={"default": {"repository": "org/x", "github_token": "tx"}},
            )

    def test_repository_credential_app_validation(self):
        with pytest.raises(Exception):
            RepositoryCredential(repository="org/a", auth_type="github_app")


# ---------------------------------------------------------------------------
# Per-repository token selection at request time
# ---------------------------------------------------------------------------

class TestPerRepoTokenSelection:
    def test_authorization_header_per_alias(self):
        tk = GitToolkit(
            repositories={
                "a": {"repository": "org/a", "github_token": "ta"},
                "b": {"repository": "org/b", "github_token": "tb"},
            }
        )
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(200, json_data={"number": 1}),
        ) as mocked:
            asyncio.run(tk.get_pull_request(pr_number=1, repository="a"))
            assert "/repos/org/a/pulls/1" in mocked.call_args.args[1]
            assert mocked.call_args.kwargs["headers"]["Authorization"] == "Bearer ta"

            asyncio.run(tk.get_pull_request(pr_number=2, repository="b"))
            assert "/repos/org/b/pulls/2" in mocked.call_args.args[1]
            assert mocked.call_args.kwargs["headers"]["Authorization"] == "Bearer tb"

    def test_app_mode_providers_are_isolated(self):
        tk = GitToolkit(
            repositories={
                "a": RepositoryCredential(
                    repository="org/a",
                    auth_type="github_app",
                    app_id=1,
                    installation_id=11,
                    private_key=PEM,
                ),
                "b": RepositoryCredential(
                    repository="org/b",
                    auth_type="github_app",
                    app_id=2,
                    installation_id=22,
                    private_key=PEM,
                ),
            }
        )
        prov_a = tk._connections["a"]._token_provider
        prov_b = tk._connections["b"]._token_provider
        assert prov_a is not None and prov_b is not None
        assert prov_a is not prov_b
        with patch.object(prov_a, "get_token", return_value="ghs_a"), patch.object(
            prov_b, "get_token", return_value="ghs_b"
        ):
            assert tk._resolve_connection("a").token() == "ghs_a"
            assert tk._resolve_connection("b").token() == "ghs_b"


# ---------------------------------------------------------------------------
# Per-repository default_branch
# ---------------------------------------------------------------------------

class TestPerRepoDefaultBranch:
    def test_context_uses_registered_default_branch_and_token(self):
        tk = GitToolkit(
            repositories={
                "a": {
                    "repository": "org/a",
                    "github_token": "ta",
                    "default_branch": "develop",
                }
            }
        )
        # base_branch omitted -> fall back to the registered repo's default.
        ctx = tk._prepare_github_context("a", None)
        assert ctx.repository == "org/a"
        assert ctx.base_branch == "develop"
        assert ctx.token == "ta"

    def test_context_explicit_branch_overrides_default(self):
        tk = GitToolkit(
            repositories={
                "a": {
                    "repository": "org/a",
                    "github_token": "ta",
                    "default_branch": "develop",
                }
            }
        )
        ctx = tk._prepare_github_context("a", "release")
        assert ctx.base_branch == "release"


# ---------------------------------------------------------------------------
# Ad-hoc unknown slug uses (and caches) global credentials
# ---------------------------------------------------------------------------

class TestAdHocFallback:
    def test_unknown_slug_uses_global_token_and_caches(self):
        tk = GitToolkit(default_repository="org/d", github_token="g")
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(200, json_data={"number": 1}),
        ) as mocked:
            asyncio.run(tk.get_pull_request(pr_number=1, repository="x/y"))
        assert "/repos/x/y/pulls/1" in mocked.call_args.args[1]
        assert mocked.call_args.kwargs["headers"]["Authorization"] == "Bearer g"
        # The ad-hoc connection is cached under the slug for reuse.
        assert "x/y" in tk._connections
        first = tk._resolve_connection("x/y")
        second = tk._resolve_connection("x/y")
        assert first is second

    def test_ad_hoc_reuses_global_app_provider(self):
        with patch.object(gt, "GithubIntegration") as gi_cls:
            gi_cls.return_value.get_access_token.return_value = (
                _mock_installation_auth("ghs_global")
            )
            tk = GitToolkit(
                default_repository="org/d",
                auth_type="github_app",
                app_id=1,
                installation_id=11,
                private_key=PEM,
            )
        conn = tk._resolve_connection("x/y")
        # Ad-hoc app connection reuses the toolkit's single global provider.
        assert conn._token_provider is tk._token_provider


# ---------------------------------------------------------------------------
# Thread-safety smoke test
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_ad_hoc_resolution_single_entry(self):
        tk = GitToolkit(default_repository="org/d", github_token="g")
        with ThreadPoolExecutor(max_workers=8) as pool:
            conns = list(
                pool.map(lambda _: tk._resolve_connection("x/y"), range(32))
            )
        # All threads observe the same cached connection instance.
        assert all(c is conns[0] for c in conns)
        assert list(tk._connections).count("x/y") == 1
