"""Wheel-content verification for FEAT-203.

Locks the PEP 420 decision into CI:
- The satellite wheel must NOT contain __init__.py at any of the 8 namespace levels.
- The satellite wheel MUST contain all expected server files.

Tests that use the ``satellite_wheel_path`` fixture (which builds the wheel via
``uv build``) are marked ``@pytest.mark.wheel_build`` and are skipped automatically
when ``uv`` is not available on PATH.
"""
import pathlib
import pytest


# The 8 namespace directories that must not have __init__.py
FORBIDDEN_INIT_PATHS = [
    "parrot/__init__.py",
    "parrot/mcp/__init__.py",
    "parrot/a2a/__init__.py",
    "parrot/handlers/__init__.py",
    "parrot/manager/__init__.py",
    "parrot/services/__init__.py",
    "parrot/scheduler/__init__.py",
    "parrot/autonomous/__init__.py",
]

# Expected backend files that must exist in the satellite src tree
EXPECTED_BACKEND_FILES = [
    "manager/manager.py",
    "a2a/server.py",
    "mcp/server.py",
    "services/agent_service.py",
    "scheduler/manager.py",
    "autonomous/orchestrator.py",
    "handlers/bots.py",
    "mcp/oauth_server.py",
    "mcp/transports/__init__.py",
]

SATELLITE_SRC = pathlib.Path(__file__).parent.parent / "src" / "parrot"


class TestWheelHasNoInitAtNamespaceLevels:
    """PEP 420: no __init__.py at the 8 namespace levels."""

    @pytest.mark.wheel_build
    @pytest.mark.parametrize("forbidden", FORBIDDEN_INIT_PATHS)
    def test_no_init_at(self, satellite_wheel_namelist, forbidden):
        """Assert the satellite wheel does not contain the forbidden __init__.py."""
        assert forbidden not in satellite_wheel_namelist, (
            f"satellite wheel must not contain {forbidden!r} "
            f"(violates PEP 420 namespace package). "
            f"Found names: {[n for n in satellite_wheel_namelist if forbidden in n]}"
        )


class TestWheelContainsAdminUI:
    """FEAT-468: the embedded Admin UI's built assets must ship in the wheel.

    ``dist/`` is gitignored (TASK-2523) — the Node/pnpm build
    (``pnpm generate && pnpm build`` in ``packages/ai-parrot-server/ui/``)
    must have populated ``src/parrot/server/ui/dist/`` BEFORE ``uv build``
    runs (which is what ``satellite_wheel_path`` invokes), or the
    ``"parrot.server.ui" = ["dist/*", "dist/assets/*"]`` package-data glob
    in ``pyproject.toml`` has nothing to pick up and the wheel silently
    ships no UI. This test fails in that case and passes once the UI has
    been built — see the release pipeline stage (Makefile
    ``build-server-ui`` target) that runs the build before publishing.
    """

    @pytest.mark.wheel_build
    def test_dist_index_present(self, satellite_wheel_namelist):
        """The wheel contains the built SPA's index.html entrypoint."""
        assert "parrot/server/ui/dist/index.html" in satellite_wheel_namelist, (
            "wheel is missing parrot/server/ui/dist/index.html — the Admin UI "
            "was not built (run `pnpm generate && pnpm build` in "
            "packages/ai-parrot-server/ui/ before `uv build`). "
            f"Found names under parrot/server/ui/: "
            f"{[n for n in satellite_wheel_namelist if n.startswith('parrot/server/ui/')]}"
        )

    @pytest.mark.wheel_build
    def test_dist_assets_present(self, satellite_wheel_namelist):
        """The wheel contains at least one built asset (JS/CSS bundle)."""
        assets = [
            n for n in satellite_wheel_namelist
            if n.startswith("parrot/server/ui/dist/assets/")
        ]
        assert assets, (
            "wheel is missing parrot/server/ui/dist/assets/* — the Admin UI "
            "build produced no assets (or was skipped entirely)."
        )

    @pytest.mark.wheel_build
    def test_agentchat_chunk_present(self, satellite_wheel_namelist):
        """FEAT-476: the vendored AgentChat lazy chunk ships in the wheel.

        Matched by substring + suffix rather than a specific filename —
        Vite content-hashes chunk names (e.g. ``AgentChat-DPxnpXKV.js``),
        so this must not assume a fixed hash.
        """
        chunks = [
            n for n in satellite_wheel_namelist
            if n.startswith("parrot/server/ui/dist/assets/")
            and "AgentChat" in n
            and n.endswith(".js")
        ]
        assert chunks, (
            "wheel is missing the AgentChat chunk — was the UI built with "
            "the chat module? (packages/ai-parrot-server/ui/src/lib/"
            "components/agents/AgentChat.svelte, wired into the "
            "/admin/agents/:name/chat route by TASK-2597)"
        )


class TestSatelliteSourceLayout:
    """Validate the satellite src/ directory layout (without building a wheel)."""

    @pytest.mark.parametrize("relpath", EXPECTED_BACKEND_FILES)
    def test_expected_file_exists(self, relpath):
        """Expected backend files exist in satellite src/parrot/."""
        full = SATELLITE_SRC / relpath
        assert full.exists(), (
            f"Expected {relpath} in satellite src/parrot/, but not found at {full}"
        )

    @pytest.mark.parametrize("namespace_dir", [
        "",        # parrot/
        "mcp",     # parrot/mcp/
        "a2a",     # parrot/a2a/
        "handlers",
        "manager",
        "services",
        "scheduler",
        "autonomous",
    ])
    def test_no_init_in_src(self, namespace_dir):
        """PEP 420: namespace directories in src must not have __init__.py."""
        d = SATELLITE_SRC / namespace_dir if namespace_dir else SATELLITE_SRC
        init = d / "__init__.py"
        assert not init.exists(), (
            f"__init__.py found in {d} — violates PEP 420 namespace package requirement"
        )
