"""Unit tests for GitToolkit's multi-repository credentials registry."""
from __future__ import annotations

import datetime as _dt
import tempfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from parrot_tools import gittoolkit as gt
from parrot_tools.gittoolkit import (
    GitToolkit,
    GitToolkitError,
    RepositoryCredential,
    _load_pem,
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
    @pytest.mark.asyncio
    async def test_authorization_header_per_alias(self):
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
            await tk.get_pull_request(pr_number=1, repository="a")
            assert "/repos/org/a/pulls/1" in mocked.call_args.args[1]
            assert mocked.call_args.kwargs["headers"]["Authorization"] == "Bearer ta"

            await tk.get_pull_request(pr_number=2, repository="b")
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
    @pytest.mark.asyncio
    async def test_unknown_slug_uses_global_token_and_caches(self):
        tk = GitToolkit(default_repository="org/d", github_token="g")
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(200, json_data={"number": 1}),
        ) as mocked:
            await tk.get_pull_request(pr_number=1, repository="x/y")
        assert "/repos/x/y/pulls/1" in mocked.call_args.args[1]
        assert mocked.call_args.kwargs["headers"]["Authorization"] == "Bearer g"
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
        assert all(c is conns[0] for c in conns)
        assert list(tk._connections).count("x/y") == 1


# ---------------------------------------------------------------------------
# "default" alias in repositories (without legacy default_repository)
# ---------------------------------------------------------------------------

class TestDefaultAliasInRegistry:
    def test_default_alias_resolves_via_none(self):
        tk = GitToolkit(
            repositories={
                "default": {"repository": "org/main", "github_token": "tok"},
            }
        )
        conn = tk._resolve_connection(None)
        assert conn.repository == "org/main"
        assert conn.token() == "tok"

    def test_default_alias_sets_custom_branch(self):
        tk = GitToolkit(
            repositories={
                "default": {
                    "repository": "org/main",
                    "github_token": "tok",
                    "default_branch": "develop",
                },
            }
        )
        ctx = tk._prepare_github_context(None, None)
        assert ctx.base_branch == "develop"


# ---------------------------------------------------------------------------
# _load_pem direct tests
# ---------------------------------------------------------------------------

class TestLoadPem:
    def test_inline_pem_returned_directly(self):
        assert _load_pem("INLINE", None) == "INLINE"

    def test_literal_backslash_n_normalised(self):
        result = _load_pem("line1\\nline2", None)
        assert result == "line1\nline2"

    def test_file_path_reads_contents(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
            f.write("FILE_PEM")
            f.flush()
            result = _load_pem(None, f.name)
        assert result == "FILE_PEM"

    def test_both_set_raises(self):
        with pytest.raises(gt.GitToolkitError, match="EITHER"):
            _load_pem("inline", "/some/path")

    def test_neither_set_raises(self):
        with pytest.raises(gt.GitToolkitError, match="requires"):
            _load_pem(None, None)

    def test_unreadable_path_raises(self):
        with pytest.raises(gt.GitToolkitError, match="Could not read"):
            _load_pem(None, "/nonexistent/path.pem")


# ---------------------------------------------------------------------------
# RepositoryCredential pat-mode validation
# ---------------------------------------------------------------------------

class TestRepositoryCredentialPatValidation:
    def test_pat_mode_without_token_raises(self):
        with pytest.raises(ValueError, match="github_token"):
            RepositoryCredential(repository="org/a", auth_type="pat")

    def test_pat_mode_with_token_succeeds(self):
        cred = RepositoryCredential(repository="org/a", github_token="tok")
        assert cred.github_token == "tok"
