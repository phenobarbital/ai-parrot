"""Seat visibility, root isolation, and the operator live-manifest gate (FEAT-580, TASK-3513).

Default (offline) tests configure three independent seat roles --
``research``, ``coding``, ``review`` -- each with its own
``.parrot/mcp-toolkits.yaml`` pointed at the scripted, deterministic
``fake_server.py`` fixture (never a live coding agent or a real Pyright).
A server-level ``tools/list`` success alone is never accepted as proof of
seat visibility here: every role's access is confirmed with a real tool
CALL through its own toolkit instance.

The opt-in live path is gated on ``PARROT_LSP_LIVE_MANIFEST``: when unset,
the live check is explicitly reported as **not executed** -- never
silently treated as passing.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from parrot.mcp.toolkit_config import load_toolkits_config
from parrot_tools.lsp.models import OPERATOR_UNCONFIGURED_ENVIRONMENT_ID
from parrot_tools.lsp.toolkit import LSPToolkit

FAKE_SERVER = Path(__file__).parent / "fake_server.py"

#: The three seat roles spec Module 4 calls out by name ("every
#: research/coding/review seat").
SEAT_ROLES: tuple[str, ...] = ("research", "coding", "review")

_EXPECTED_TOOL_NAMES = ("lsp_definition", "lsp_diagnostic_delta", "lsp_diagnostics", "lsp_references")

_LIVE_MANIFEST_ENV = "PARROT_LSP_LIVE_MANIFEST"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_worktree(root: Path) -> Path:
    """A small, real, independent Git worktree -- never shared with another fixture."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "pkg").mkdir()
    (root / "pkg" / "mod.py").write_text("def foo():\n    return 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _write_worktree_config(root: Path, *, environment_id: str) -> None:
    """Render an explicit, per-worktree `lsp:` section -- never inherited."""
    server_command = [sys.executable, str(FAKE_SERVER), "happy_path"]
    version_command = [sys.executable, "-c", "print('pyright 1.1.414')"]
    parrot_dir = root / ".parrot"
    parrot_dir.mkdir(exist_ok=True)
    (parrot_dir / "mcp-toolkits.yaml").write_text(
        "toolkits:\n"
        "  lsp:\n"
        "    class: parrot_tools.lsp.toolkit.LSPToolkit\n"
        "    kwargs:\n"
        "      config:\n"
        f"        repo_root: {json.dumps(str(root))}\n"
        f"        environment_id: {json.dumps(environment_id)}\n"
        f"        server_command: {json.dumps(server_command)}\n"
        f"        version_command: {json.dumps(version_command)}\n",
        encoding="utf-8",
    )


def _check_seat_tool_access(worktree: Path) -> dict[str, Any]:
    """Construct the toolkit from THIS worktree's own config.

    A `tools/list`-shaped name check alone is never accepted here --
    callers must still exercise a real tool call to prove access (spec:
    "server-level tools/list alone is not accepted as proof").
    """
    cfg = load_toolkits_config(worktree)
    section = cfg.toolkits.get("lsp")
    if section is None:
        return {"visible": False, "fallback_only": True, "reason": "no lsp section declared for this worktree"}
    toolkit = LSPToolkit(**section.kwargs)
    tool_names = tuple(sorted(tool.name for tool in toolkit.get_tools()))
    if toolkit._config.environment_id == OPERATOR_UNCONFIGURED_ENVIRONMENT_ID:
        return {
            "visible": True,
            "fallback_only": True,
            "tool_names": tool_names,
            "reason": "operator-unconfigured sentinel: no LSP process will be started",
            "toolkit": toolkit,
        }
    return {"visible": True, "fallback_only": False, "tool_names": tool_names, "toolkit": toolkit}


@pytest.fixture
def three_role_worktrees(tmp_path: Path) -> dict[str, Path]:
    """Three INDEPENDENTLY configured worktrees, one per seat role."""
    worktrees: dict[str, Path] = {}
    for role in SEAT_ROLES:
        worktree = _make_worktree(tmp_path / role)
        _write_worktree_config(worktree, environment_id=f"{role}-seat-env")
        worktrees[role] = worktree
    return worktrees


# ---------------------------------------------------------------------------
# test_cli_seat_visibility_and_fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cli_seat_visibility_and_fallback(three_role_worktrees: dict[str, Path]) -> None:
    """Each of the three seat roles is checked independently, with a real tool call."""
    for role, worktree in three_role_worktrees.items():
        access = _check_seat_tool_access(worktree)
        assert access["visible"] is True, role
        assert access["fallback_only"] is False, role
        assert access["tool_names"] == _EXPECTED_TOOL_NAMES, role

        toolkit = access["toolkit"]
        text = (worktree / "pkg" / "mod.py").read_text()
        try:
            # A real definition call round-tripped through this role's own
            # toolkit/session, not just a declared tools/list (the fake
            # server's happy_path scenario always publishes diagnostics for
            # a fixed, unrelated URI -- see test_session_diagnostics.py --
            # so lsp_definition is the proof point here, not lsp_diagnostics).
            result = await toolkit.lsp_definition(path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(text))
            assert result.status == "ok", (role, result)
        finally:
            await toolkit._close()

    # Adversarial: a role pointed at the operator-unconfigured sentinel is
    # recorded fallback-only explicitly, never silently treated as available.
    fallback_worktree = three_role_worktrees["research"]
    (fallback_worktree / ".parrot" / "mcp-toolkits.yaml").write_text(
        "toolkits:\n"
        "  lsp:\n"
        "    class: parrot_tools.lsp.toolkit.LSPToolkit\n"
        "    kwargs:\n"
        "      config:\n"
        f"        repo_root: {json.dumps(str(fallback_worktree))}\n"
        f"        environment_id: {OPERATOR_UNCONFIGURED_ENVIRONMENT_ID}\n",
        encoding="utf-8",
    )
    fallback_access = _check_seat_tool_access(fallback_worktree)
    assert fallback_access["visible"] is True  # the toolkit resolves...
    assert fallback_access["fallback_only"] is True  # ...but is explicitly fallback-only, not "available"
    await fallback_access["toolkit"]._close()

    # Adversarial: no `lsp` section declared at all -- absence, not a crash.
    no_section_worktree = _make_worktree(three_role_worktrees["research"].parent / "no-section")
    absent_access = _check_seat_tool_access(no_section_worktree)
    assert absent_access["visible"] is False
    assert absent_access["fallback_only"] is True


# ---------------------------------------------------------------------------
# test_parent_visibility_does_not_imply_child_visibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parent_visibility_does_not_imply_child_visibility(tmp_path: Path) -> None:
    """Blindly copying a parent worktree's rendered config into a child resolves WRONG.

    docs/sdd/lsp-pilot.md explicitly warns against this; this test proves
    the failure mode empirically rather than only documenting it.
    """
    parent = _make_worktree(tmp_path / "parent")
    _write_worktree_config(parent, environment_id="parent-env")

    child = _make_worktree(tmp_path / "child")
    (child / "pkg" / "child_only.py").write_text("value = 'child'\n")
    _git(child, "add", "-A")
    _git(child, "commit", "-q", "-m", "child file")

    # Blindly copy the PARENT's rendered config into the CHILD worktree --
    # exactly the mistake the docs warn against, instead of re-rendering.
    child_parrot_dir = child / ".parrot"
    child_parrot_dir.mkdir(exist_ok=True)
    (child_parrot_dir / "mcp-toolkits.yaml").write_text(
        (parent / ".parrot" / "mcp-toolkits.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )

    cfg = load_toolkits_config(child)
    section = cfg.toolkits["lsp"]
    copied_repo_root = Path(section.kwargs["config"]["repo_root"])
    # The copied config still points at the PARENT's absolute repo_root --
    # visibility from the parent does not imply correctness in the child.
    assert copied_repo_root == parent
    assert copied_repo_root != child

    toolkit = LSPToolkit(**section.kwargs)
    try:
        # Querying the child-only file through the wrongly-copied (parent)
        # config must fail: that file does not exist anywhere in the
        # parent's tracked/untracked workspace manifest at all.
        result = await toolkit.lsp_definition(
            path="pkg/child_only.py", line=1, column=1, expected_sha256=_sha256("value = 'child'\n")
        )
        assert result.status == "error"
        assert result.code == "invalid_request"
    finally:
        await toolkit._close()


# ---------------------------------------------------------------------------
# test_missing_live_manifest_is_not_success
# ---------------------------------------------------------------------------


def _run_live_seat_checks() -> dict[str, Any] | None:
    """Run the operator-opted-in live seat checks, or report "not executed".

    Returns:
        ``None`` when ``PARROT_LSP_LIVE_MANIFEST`` is unset -- this is the
        "not executed" state and must never be conflated with a passing
        result by any caller. Otherwise, one result per declared seat role.
    """
    manifest_path = os.environ.get(_LIVE_MANIFEST_ENV)
    if not manifest_path:
        return None
    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    results: dict[str, Any] = {}
    for role, seat in data["seats"].items():
        completed = subprocess.run(
            seat["argv"],
            capture_output=True,
            text=True,
            timeout=seat.get("timeout_s", 30.0),
            check=False,
        )
        results[role] = {"returncode": completed.returncode, "stdout": completed.stdout}
    return results


def test_missing_live_manifest_is_not_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Absence of the opt-in env var is reported as not-executed, never as a pass."""
    monkeypatch.delenv(_LIVE_MANIFEST_ENV, raising=False)
    result = _run_live_seat_checks()
    assert result is None


def test_live_manifest_when_provided_is_executed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the operator explicitly opts in, the live check actually runs.

    Uses a fake CLI here to stay deterministic and free of live spend; a
    real operator manifest points ``argv`` at the actual research/coding/
    review host binaries instead.
    """
    fake_cli = tmp_path / "fake_cli.py"
    fake_cli.write_text("print('tools/list: lsp_definition,lsp_references,lsp_diagnostics,lsp_diagnostic_delta')\n")
    manifest = {
        "seats": {role: {"argv": [sys.executable, str(fake_cli)], "timeout_s": 5.0} for role in SEAT_ROLES},
    }
    manifest_path = tmp_path / "live_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv(_LIVE_MANIFEST_ENV, str(manifest_path))

    result = _run_live_seat_checks()
    assert result is not None
    assert set(result) == set(SEAT_ROLES)
    assert all(entry["returncode"] == 0 for entry in result.values())
    assert all("lsp_definition" in entry["stdout"] for entry in result.values())
