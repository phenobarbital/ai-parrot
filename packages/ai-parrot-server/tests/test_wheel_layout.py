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
