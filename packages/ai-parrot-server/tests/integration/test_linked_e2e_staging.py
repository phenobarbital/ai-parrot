"""FEAT-611 M9 — live tier (§9 S9): same assertions as run_e2e.py; never the deterministic verdict.

The marker is still called ``staging`` but means "live target": ``ENV=staging`` or ``ENV=dev`` (production is
never accepted). Needs a running ``examples/agents/a2ui/linked_e2e/server.py`` (``E2E_BASE_URL``, default
http://127.0.0.1:5000), querysource >= 5.1.2 and ``E2E_USER`` / ``E2E_PASSWORD``. Optional: ``E2E_DENY_BASE_URL``,
``E2E_NOGUARD_BASE_URL``, ``E2E_SHARE_USER`` / ``E2E_SHARE_PASSWORD``, ``E2E_S2_RANGE_A`` / ``E2E_S2_RANGE_B``,
``E2E_RANGE`` (dev defaults: 2025-03-01:2025-03-07 / 2025-03-11:2025-03-15).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
LIVE_ENVS = ("staging", "dev")  # == run_e2e.LIVE_ENVS
RUN_E2E = REPO / "examples/agents/a2ui/linked_e2e/run_e2e.py"


def _qs_ok() -> bool:
    try:
        from parrot_tools.querysource._qs import installed_version
    except ImportError:
        return False
    try:
        major, minor, patch = (int(p) for p in installed_version().split(".")[:3])
    except (TypeError, ValueError, AttributeError):
        return False
    return (major, minor, patch) >= (5, 1, 2)


pytestmark = [
    pytest.mark.staging,
    pytest.mark.asyncio,
    pytest.mark.skipif(os.environ.get("ENV") not in LIVE_ENVS, reason="live tier: ENV=staging or ENV=dev required"),
    pytest.mark.skipif(not _qs_ok(), reason="querysource >= 5.1.2 required"),
    pytest.mark.skipif(
        not (os.environ.get("E2E_USER") and os.environ.get("E2E_PASSWORD")),
        reason="E2E_USER / E2E_PASSWORD not set",
    ),
]


def _runner():
    """Load run_e2e.py by path (examples/ is not a package); registered so its dataclasses resolve."""
    name = "linked_e2e_run_e2e"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, RUN_E2E)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def ctx():
    """Log in against E2E_BASE_URL (a running server.py) and yield an E2EContext."""
    import aiohttp

    run_e2e = _runner()
    base_url = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:5000")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
        yield await run_e2e.open_context(
            session,
            base_url,
            deny_base_url=os.environ.get("E2E_DENY_BASE_URL"),
            noguard_base_url=os.environ.get("E2E_NOGUARD_BASE_URL"),
            via_agent=os.environ.get("E2E_VIA_AGENT") == "1",
        )


@pytest.mark.parametrize("scenario", ["s1", "s2", "s3", "s5"])
async def test_staging_scenario(ctx, scenario):
    run_e2e = _runner()
    results = await getattr(run_e2e, f"run_{scenario}")(ctx)
    run_e2e.write_table(results)
    failed = [r for r in results if not r.skipped and not r.passed]
    assert any(not r.skipped for r in results), "every check was skipped"
    assert not failed, "\n".join(f"{r.id}: {r.detail}" for r in failed)
