"""Unit tests for the confinement core and secret deny-list (FEAT-484)."""

from __future__ import annotations

from pathlib import Path

import pytest
from parrot.tools.repo.confinement import (
    PathOutsideRootError,
    SecretFileError,
    is_secret_path,
    resolve_readable_path,
    resolve_within_root,
)
from parrot.tools.repo.models import (
    RepoReadResult,
    RepoSearchHit,
    RepoSearchResult,
    RepoToolError,
)


class TestResolveWithinRoot:
    def test_accepts_nested(self, temp_repo: Path):
        out = resolve_within_root(temp_repo, "pkg/sub/mod.py")
        assert out == (temp_repo / "pkg" / "sub" / "mod.py").resolve()

    def test_rejects_parent_traversal(self, temp_repo: Path):
        with pytest.raises(PathOutsideRootError):
            resolve_within_root(temp_repo, "../../etc/passwd")

    def test_rejects_absolute_outside(self, temp_repo: Path):
        with pytest.raises(PathOutsideRootError):
            resolve_within_root(temp_repo, "/etc/passwd")

    def test_rejects_symlink_escape(self, temp_repo: Path):
        """A symlink INSIDE the root pointing outside is the case a
        string-prefix check would wrongly allow."""
        with pytest.raises(PathOutsideRootError):
            resolve_within_root(temp_repo, "escape/secret.txt")

    def test_root_itself_via_symlink(self, tmp_path: Path, temp_repo: Path):
        link = tmp_path / "link_to_repo"
        link.symlink_to(temp_repo)
        assert resolve_within_root(link, "pkg/sub/mod.py").is_file()


class TestIsSecretPath:
    @pytest.mark.parametrize(
        "p",
        [
            ".env",
            ".env.production",
            "server.pem",
            "server.key",
            "id_rsa",
            "id_rsa.pub",
            "id_ed25519",
            "config/.env",
            "wiki.local.json",
            "credentials",
            ".netrc",
            ".pgpass",
            "a.p12",
            "a.pfx",
            "a.keystore",
            "a.jks",
            ".ENV",
        ],
    )
    def test_denied(self, p):
        assert is_secret_path(p) is True

    @pytest.mark.parametrize(
        "p",
        [
            ".env.example",
            ".env.sample",
            "server.pem.example",
            "server.key.template",
            "credentials.dist",
            "pkg/sub/mod.py",
            "README.md",
        ],
    )
    def test_allowed(self, p):
        assert is_secret_path(p) is False


class TestResolveReadablePath:
    def test_ok(self, temp_repo: Path):
        assert resolve_readable_path(temp_repo, "pkg/sub/mod.py").is_file()

    def test_secret_raises(self, temp_repo: Path):
        with pytest.raises(SecretFileError):
            resolve_readable_path(temp_repo, ".env")

    def test_nested_secret_raises(self, temp_repo: Path):
        with pytest.raises(SecretFileError):
            resolve_readable_path(temp_repo, "config/.env")

    def test_example_allowed(self, temp_repo: Path):
        assert resolve_readable_path(temp_repo, ".env.example").is_file()

    def test_escape_raises(self, temp_repo: Path):
        with pytest.raises(PathOutsideRootError):
            resolve_readable_path(temp_repo, "escape/secret.txt")


class TestModels:
    def test_defaults(self):
        assert RepoToolError(error="not_found", detail="x").path == ""
        assert RepoReadResult(path="a", content="b").truncated is False
        assert RepoSearchHit(page_id="p", path="a").outline == []
        r = RepoSearchResult(query="q")
        assert r.hits == [] and r.degraded is False
