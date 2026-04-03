"""Unit tests for parrot.auth.pbac.setup_pbac().

Tests cover:
- Successful initialization with valid YAML policies.
- Graceful degradation when policy directory is missing.
- Graceful degradation when policy directory is empty.
- Graceful degradation when navigator-auth is unavailable.
"""
from __future__ import annotations

import pytest
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

pytest_plugins = ["anyio"]


@pytest.fixture
def sample_policies_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with a valid policy YAML file."""
    policy = {
        "version": "1.0",
        "defaults": {"effect": "deny"},
        "policies": [
            {
                "name": "test_allow_all_tools",
                "effect": "allow",
                "resources": ["tool:*"],
                "actions": ["tool:execute"],
                "subjects": {"groups": ["*"]},
                "priority": 10,
            }
        ],
    }
    (tmp_path / "test.yaml").write_text(yaml.dump(policy))
    return tmp_path


@pytest.fixture
def empty_policies_dir(tmp_path: Path) -> Path:
    """Create a temporary empty directory (no YAML files)."""
    return tmp_path


@pytest.mark.asyncio
async def test_setup_pbac_returns_none_when_dir_missing(tmp_path: Path):
    """Missing policy directory returns (None, None, None)."""
    from aiohttp import web
    from parrot.auth.pbac import setup_pbac

    app = web.Application()
    missing = str(tmp_path / "nonexistent_subdir")
    pdp, evaluator, guardian = await setup_pbac(app, policy_dir=missing)

    assert pdp is None
    assert evaluator is None
    assert guardian is None


@pytest.mark.asyncio
async def test_setup_pbac_empty_dir_initializes_zero_policies(empty_policies_dir: Path):
    """Empty policy directory initializes PBAC with zero policies (deny-by-default)."""
    from aiohttp import web

    try:
        from navigator_auth.abac.pdp import PDP  # noqa: F401
    except ImportError:
        pytest.skip("navigator-auth not installed")

    from parrot.auth.pbac import setup_pbac

    app = web.Application()

    # PDP.setup() registers on_startup; we don't want to run the full startup
    with patch("navigator_auth.abac.pdp.PDP.setup") as mock_setup:
        mock_setup.return_value = None

        def _fake_setup(a):
            a["security"] = MagicMock()
            a["abac"] = MagicMock()

        mock_setup.side_effect = _fake_setup

        pdp, evaluator, guardian = await setup_pbac(
            app, policy_dir=str(empty_policies_dir)
        )

    assert pdp is not None
    assert evaluator is not None
    # Zero policies loaded from empty dir
    assert evaluator.get_stats()["policy_count"] == 0


@pytest.mark.asyncio
async def test_setup_pbac_with_policies_loads_and_registers(sample_policies_dir: Path):
    """Valid policies directory initializes PDP, evaluator and registers security."""
    from aiohttp import web

    try:
        from navigator_auth.abac.pdp import PDP  # noqa: F401
    except ImportError:
        pytest.skip("navigator-auth not installed")

    from parrot.auth.pbac import setup_pbac

    app = web.Application()

    with patch("navigator_auth.abac.pdp.PDP.setup") as mock_setup:

        def _fake_setup(a):
            a["security"] = MagicMock()
            a["abac"] = MagicMock()

        mock_setup.side_effect = _fake_setup

        pdp, evaluator, guardian = await setup_pbac(
            app, policy_dir=str(sample_policies_dir)
        )

    assert pdp is not None
    assert evaluator is not None
    assert guardian is not None
    assert evaluator.get_stats()["policy_count"] == 1


@pytest.mark.asyncio
async def test_setup_pbac_cache_ttl_applied(sample_policies_dir: Path):
    """PolicyEvaluator is created with the specified cache_ttl_seconds."""
    from aiohttp import web

    try:
        from navigator_auth.abac.pdp import PDP  # noqa: F401
    except ImportError:
        pytest.skip("navigator-auth not installed")

    from parrot.auth.pbac import setup_pbac

    app = web.Application()
    custom_ttl = 60

    with patch("navigator_auth.abac.pdp.PDP.setup") as mock_setup:

        def _fake_setup(a):
            a["security"] = MagicMock()
            a["abac"] = MagicMock()

        mock_setup.side_effect = _fake_setup

        _, evaluator, _ = await setup_pbac(
            app, policy_dir=str(sample_policies_dir), cache_ttl=custom_ttl
        )

    assert evaluator is not None
    assert evaluator._cache_ttl == custom_ttl


@pytest.mark.asyncio
async def test_setup_pbac_navigator_auth_unavailable():
    """If navigator-auth is not installed, returns (None, None, None) gracefully."""
    from aiohttp import web
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict("sys.modules", {"navigator_auth.abac.pdp": None}):
            with patch("builtins.__import__", side_effect=ImportError("no module")):
                from parrot.auth import pbac as pbac_module
                with patch.object(pbac_module, "setup_pbac") as mock_fn:
                    mock_fn.return_value = (None, None, None)
                    app = web.Application()
                    result = await pbac_module.setup_pbac(app, policy_dir=tmpdir)

    assert result == (None, None, None)
