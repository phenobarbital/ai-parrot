"""Two-worktree isolation and per-instance concurrency (FEAT-580, TASK-3508).

Every session in this module runs against the scripted, deterministic
``fake_server.py`` fixture over a real subprocess pipe (already built for
M1/M2) -- never a live Pyright install -- proving distinct evidence across
two independent ``LSPToolkit`` instances, that concurrent callers against
ONE instance are serialized (never racing the single owned session), and
that an in-flight workspace change invalidates the session rather than
letting a stale generation's evidence leak into a later result.
"""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from parrot_tools.lsp.models import LSPConfig
from parrot_tools.lsp.session import PyrightSession
from parrot_tools.lsp.toolkit import LSPToolkit

FAKE_SERVER = Path(__file__).parent / "fake_server.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_repo(root: Path, *, content: str) -> Path:
    """A small, real, independent Git worktree -- never shared with another repo fixture."""
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "pkg").mkdir()
    (root / "pkg" / "mod.py").write_text(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _config(repo_root: Path, **overrides: Any) -> LSPConfig:
    fields: dict[str, Any] = {
        "repo_root": repo_root,
        "environment_id": "worktree-isolation-test",
        "server_command": [sys.executable, str(FAKE_SERVER), "happy_path"],
        "version_command": [sys.executable, "-c", "print('pyright 1.1.414')"],
    }
    fields.update(overrides)
    return LSPConfig(**fields)


# ---------------------------------------------------------------------------
# test_two_worktrees_and_concurrent_callers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_worktrees_and_concurrent_callers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Distinct evidence across two worktrees; one instance serializes its callers."""
    repo_a = _make_repo(tmp_path / "repo_a", content="def foo():\n    return 1\n")
    repo_b = _make_repo(tmp_path / "repo_b", content="def foo():\n    return 2\n")

    toolkit_a = LSPToolkit(_config(repo_a))
    toolkit_b = LSPToolkit(_config(repo_b))
    try:
        text_a = (repo_a / "pkg" / "mod.py").read_text()
        text_b = (repo_b / "pkg" / "mod.py").read_text()

        # --- Distinct evidence across two divergent worktrees -----------
        result_a, result_b = await asyncio.gather(
            toolkit_a.lsp_definition(path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(text_a)),
            toolkit_b.lsp_definition(path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(text_b)),
        )
        assert result_a.status == "ok"
        assert result_b.status == "ok"
        assert result_a.evidence is not None and result_b.evidence is not None
        assert result_a.evidence.repo_root != result_b.evidence.repo_root
        assert result_a.evidence.workspace_id != result_b.evidence.workspace_id
        assert result_a.evidence.workspace_digest != result_b.evidence.workspace_digest

        # --- Serialized per-instance operations --------------------------
        # Concurrent callers against the SAME toolkit instance must never
        # let more than one in-flight session.request() run at a time --
        # the operation lock owns exactly one session per instance.
        in_flight = 0
        max_in_flight = 0
        real_request = PyrightSession.request

        async def _tracked_request(self: PyrightSession, *args: Any, **kwargs: Any) -> Any:
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            try:
                # Yield control so a genuinely concurrent second caller
                # would have a real chance to race in here if the lock
                # were not actually serializing them.
                await asyncio.sleep(0.01)
                return await real_request(self, *args, **kwargs)
            finally:
                in_flight -= 1

        monkeypatch.setattr(PyrightSession, "request", _tracked_request)

        results = await asyncio.gather(
            toolkit_a.lsp_definition(path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(text_a)),
            toolkit_a.lsp_definition(path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(text_a)),
            toolkit_a.lsp_definition(path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(text_a)),
        )
        assert all(result.status == "ok" for result in results)
        assert max_in_flight == 1, f"expected strictly serialized calls, saw {max_in_flight} concurrently in flight"

        monkeypatch.undo()

        # --- Old-generation rejection -------------------------------------
        # A source-only edit changes the on-disk hash the caller must
        # re-verify against (expected_sha256 is per-call), so the OLD
        # generation's captured text can never be replayed successfully;
        # a fresh generation is required, and its evidence must record it.
        generation_before = toolkit_a._session_generation
        first_call = await toolkit_a.lsp_definition(
            path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(text_a)
        )
        assert first_call.status == "ok"

        (repo_a / "pkg" / "mod.py").write_text("def foo():\n    return 99\n")
        stale_replay = await toolkit_a.lsp_definition(
            path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(text_a)
        )
        assert stale_replay.status == "error"
        assert stale_replay.code == "source_changed"

        new_text = (repo_a / "pkg" / "mod.py").read_text()
        fresh_call = await toolkit_a.lsp_definition(
            path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(new_text)
        )
        assert fresh_call.status == "ok"
        assert (
            toolkit_a._session_generation > generation_before
        ), "a workspace change must bump the session generation, never silently reuse the old one"
        assert fresh_call.evidence is not None and first_call.evidence is not None
        assert fresh_call.evidence.workspace_digest != first_call.evidence.workspace_digest
    finally:
        await toolkit_a._close()
        await toolkit_b._close()
