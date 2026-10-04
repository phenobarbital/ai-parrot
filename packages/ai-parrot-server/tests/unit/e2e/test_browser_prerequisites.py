"""Prerequisite/BLOCKED guarantees for TASK-3548's owned ui+browser scenario.

TASK-3531 already unit-tests every one of ``browser``/``ui``'s own
``prepare()`` validation branches directly. This file does not re-derive
that adapter logic; it re-asserts, as TASK-3548's own acceptance evidence
(this task's Scope item 3: "Codified checks require owned isolated browser;
adoption remains exploration-only. Missing binary/version or host
capability produces visible BLOCKED."), the exact real-vs-mocked-absence
prerequisite/rejection contract the owned ``test_ui.py`` scenario depends
on -- using the same real adapters that scenario itself uses, never a
duplicated reimplementation of their internal checks.

Every "missing" case here is exercised twice where the underlying host
state allows it: once against this environment's own real, unmocked
absence (``packages/ai-parrot-server/ui/node_modules`` is confirmed not
installed in this worktree), and once via a mocked absence so the suite
stays green regardless of which binaries a given host happens to have
installed -- the same convention TASK-3530/TASK-3531's own test files
established. No ``unittest.mock.MagicMock`` stands in for a
:class:`~parrot.e2e.targets.base.TargetAdapter` or
:class:`~parrot.e2e.models.RunState`; every fixture below is either a real,
schema-validated model or a small, single-purpose fake.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.e2e.errors import E2EConfigError, E2EPrerequisiteError, EXIT_BLOCKED
from parrot.e2e.models import TargetConfig
from parrot.e2e.targets.browser import build_browser_adapter
from parrot.e2e.targets.ui import build_ui_adapter

_REAL_WORKTREE = Path(__file__).resolve().parents[5]
_UI_NODE_MODULES_INSTALLED = (_REAL_WORKTREE / "packages" / "ai-parrot-server" / "ui" / "node_modules").is_dir()


# ---------------------------------------------------------------------------
# `browser` -- missing owned-browser binary (host capability) blocks before launch
# ---------------------------------------------------------------------------


async def test_missing_obscura_binary_blocks_owned_browser_before_launch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A missing ``obscura`` binary is a visible BLOCKED prerequisite, not a silent skip."""
    monkeypatch.setattr("parrot.e2e.targets.browser.shutil.which", lambda _name: None)
    adapter = build_browser_adapter()

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        await adapter.prepare(TargetConfig(kind="browser"), run_id="blocked-browser", worktree=tmp_path)

    assert excinfo.value.reason_code == "obscura_binary_missing"
    assert excinfo.value.exit_code == EXIT_BLOCKED
    # No private run directory/profile is ever created for a target that
    # never resolved its required binary (spec §2: "raised before any
    # subprocess is spawned").
    assert not (tmp_path / "sdd" / "state" / "e2e").exists()


# ---------------------------------------------------------------------------
# `browser` -- codified/deterministic checks require an owned instance;
# adoption is rejected outright, never silently downgraded to "owned"
# ---------------------------------------------------------------------------


async def test_default_deterministic_profile_rejects_browser_adoption(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The schema-default (``minimal``) profile TASK-3548's own scenario uses never adopts."""
    # obscura's own real/mocked presence is irrelevant here: adoption must be
    # rejected before this adapter would ever look for the binary.
    monkeypatch.setattr("parrot.e2e.targets.browser.shutil.which", lambda _name: None)
    adapter = build_browser_adapter()
    config = TargetConfig(kind="browser", options={"adopt": True, "port": 19222})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="blocked-adopt", worktree=tmp_path)

    assert excinfo.value.reason_code == "browser_adoption_requires_full_profile"


async def test_owned_browser_launch_is_never_adopted_when_obscura_is_available(tmp_path: Path) -> None:
    """Positive-path confirmation: the codified default resolves to a real, owned launch.

    Skipped (rather than failed) when this host has no ``obscura`` on
    ``PATH`` -- a genuinely missing binary is exactly the BLOCKED case
    covered above, not a defect in this confirmation.
    """
    import shutil

    if shutil.which("obscura") is None:
        pytest.skip("obscura binary not installed on this host (spec §2: BLOCKED, not a defect)")

    adapter = build_browser_adapter()
    spec = await adapter.prepare(TargetConfig(kind="browser"), run_id="owned-confirm", worktree=tmp_path)

    assert spec.argv[0] == shutil.which("obscura")
    assert adapter._endpoints["owned-confirm"].adopted is False


# ---------------------------------------------------------------------------
# `ui` -- missing build toolchain (host capability) blocks before launch
# ---------------------------------------------------------------------------


async def test_missing_pnpm_blocks_ui_target_before_launch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A missing ``pnpm`` binary is a visible BLOCKED prerequisite for the UI-in-browser scenario."""
    monkeypatch.setattr("parrot.e2e.targets.ui.shutil.which", lambda _name: None)
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui", options={"backend_url": "http://127.0.0.1:9"})

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        await adapter.prepare(config, run_id="blocked-pnpm", worktree=tmp_path)

    assert excinfo.value.reason_code == "pnpm_binary_missing"
    assert excinfo.value.exit_code == EXIT_BLOCKED
    assert not (tmp_path / "sdd" / "state" / "e2e").exists()


async def test_missing_node_blocks_ui_target_before_launch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A missing ``node`` binary is a visible BLOCKED prerequisite for the UI-in-browser scenario."""

    def _fake_which(name: str) -> str | None:
        return "/usr/bin/pnpm" if name == "pnpm" else None

    monkeypatch.setattr("parrot.e2e.targets.ui.shutil.which", _fake_which)
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui", options={"backend_url": "http://127.0.0.1:9"})

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        await adapter.prepare(config, run_id="blocked-node", worktree=tmp_path)

    assert excinfo.value.reason_code == "node_binary_missing"
    assert excinfo.value.exit_code == EXIT_BLOCKED


async def test_missing_ui_node_modules_blocks_target_real_state(tmp_path: Path) -> None:
    """This worktree's own real, unmocked state: the admin UI's dependencies are not installed.

    Confirms the exact prerequisite ``test_ui.py``'s combined scenario hits
    unmodified in this checkout (skipped only if a future host happens to
    already have them installed -- covered instead by the mocked sibling
    below).
    """
    if _UI_NODE_MODULES_INSTALLED:
        pytest.skip("packages/ai-parrot-server/ui/node_modules IS installed here; covered by the mocked test")
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui", options={"backend_url": "http://127.0.0.1:9"})

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        await adapter.prepare(config, run_id="blocked-node-modules", worktree=_REAL_WORKTREE)

    assert excinfo.value.reason_code == "ui_dependencies_missing"
    assert excinfo.value.exit_code == EXIT_BLOCKED


async def test_missing_ui_node_modules_blocks_target_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Mocked-absence sibling: green regardless of whether this host has ``node_modules`` installed."""
    monkeypatch.setattr("parrot.e2e.targets.ui.shutil.which", lambda _name: "/usr/bin/fake")
    ui_dir = tmp_path / "packages" / "ai-parrot-server" / "ui"
    ui_dir.mkdir(parents=True)
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui", options={"backend_url": "http://127.0.0.1:9"})

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        await adapter.prepare(config, run_id="blocked-node-modules-mocked", worktree=tmp_path)

    assert excinfo.value.reason_code == "ui_dependencies_missing"
    assert excinfo.value.exit_code == EXIT_BLOCKED
