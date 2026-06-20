"""Unit tests for GitToolkit.clone_repo / pull_repo (FEAT-250 TASK-002).

The subprocess layer (``_run_subprocess``) is mocked so the tests stay
hermetic — no real ``git``/``gh`` invocation, no network.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from parrot_tools.gittoolkit import GitToolkit, GitToolkitError


TOKEN = "ghp_supersecrettoken123"


def _toolkit() -> GitToolkit:
    return GitToolkit(default_repository="owner/repo", github_token=TOKEN)


class _Recorder:
    """Async stand-in for ``_run_subprocess`` that records argv and replays a result."""

    def __init__(self, rc: int = 0, out: str = "", err: str = "") -> None:
        self.rc, self.out, self.err = rc, out, err
        self.calls: list[list[str]] = []

    async def __call__(self, argv):
        self.calls.append(list(argv))
        return self.rc, self.out, self.err


# ── clone_repo: public ─────────────────────────────────────────────────


async def test_clone_repo_public(tmp_path):
    tk = _toolkit()
    rec = _Recorder(rc=0)
    dest = str(tmp_path / "r")
    with patch.object(GitToolkit, "_run_subprocess", new=rec):
        res = await tk.clone_repo("owner/name", dest)
    assert rec.calls[0][:2] == ["git", "clone"]
    assert dest in rec.calls[0]
    assert res["repository"] == "owner/name"
    assert res["path"] == dest
    assert res["updated"] is False
    # No token in any returned value (public clone has no token anyway).
    assert TOKEN not in " ".join(str(v) for v in res.values())


# ── clone_repo: private (token-in-URL, gh absent) ──────────────────────


async def test_clone_repo_private_uses_token_in_url(tmp_path):
    tk = _toolkit()
    rec = _Recorder(rc=0)
    dest = str(tmp_path / "r")
    with patch.object(GitToolkit, "_gh_available", return_value=False), \
            patch.object(GitToolkit, "_run_subprocess", new=rec):
        res = await tk.clone_repo("owner/name", dest, private=True)
    url_arg = rec.calls[0][-2]
    assert url_arg == f"https://x-access-token:{TOKEN}@github.com/owner/name.git"
    # The returned payload must never carry the token.
    assert TOKEN not in str(res)
    assert res["repository"] == "owner/name"


async def test_clone_repo_private_scrubs_token_on_error(tmp_path):
    tk = _toolkit()
    # Subprocess fails and echoes the tokenized URL into stderr.
    leaky = f"fatal: could not read https://x-access-token:{TOKEN}@github.com/owner/name.git"
    rec = _Recorder(rc=128, err=leaky)
    dest = str(tmp_path / "r")
    with patch.object(GitToolkit, "_gh_available", return_value=False), \
            patch.object(GitToolkit, "_run_subprocess", new=rec):
        with pytest.raises(GitToolkitError) as ei:
            await tk.clone_repo("owner/name", dest, private=True)
    msg = str(ei.value)
    assert TOKEN not in msg
    assert "***" in msg


async def test_clone_repo_private_prefers_gh_when_available(tmp_path):
    tk = _toolkit()
    rec = _Recorder(rc=0)
    dest = str(tmp_path / "r")
    with patch.object(GitToolkit, "_gh_available", return_value=True), \
            patch.object(GitToolkit, "_run_subprocess", new=rec):
        await tk.clone_repo("owner/name", dest, private=True)
    assert rec.calls[0][:3] == ["gh", "repo", "clone"]
    # gh path never embeds a token in argv.
    assert TOKEN not in " ".join(rec.calls[0])


# ── clone_repo: idempotent → pull_repo ─────────────────────────────────


async def test_clone_repo_idempotent_pulls(tmp_path):
    tk = _toolkit()
    dest = tmp_path / "r"
    (dest / ".git").mkdir(parents=True)
    rec = _Recorder(rc=0)
    with patch.object(GitToolkit, "_run_subprocess", new=rec):
        res = await tk.clone_repo("owner/name", str(dest))
    # Should delegate to pull_repo: a `git -C <dest> pull --ff-only`.
    assert rec.calls[0][:4] == ["git", "-C", str(dest), "pull"]
    assert "--ff-only" in rec.calls[0]
    assert res["updated"] is True


# ── pull_repo ──────────────────────────────────────────────────────────


async def test_pull_repo_fast_forwards(tmp_path):
    tk = _toolkit()
    dest = tmp_path / "r"
    (dest / ".git").mkdir(parents=True)
    rec = _Recorder(rc=0)
    with patch.object(GitToolkit, "_run_subprocess", new=rec):
        res = await tk.pull_repo(str(dest), branch="dev")
    assert rec.calls[0] == ["git", "-C", str(dest), "pull", "--ff-only", "origin", "dev"]
    assert res == {"path": str(dest), "branch": "dev", "updated": True}


async def test_pull_repo_rejects_non_clone(tmp_path):
    tk = _toolkit()
    with pytest.raises(GitToolkitError):
        await tk.pull_repo(str(tmp_path / "not-a-clone"))
