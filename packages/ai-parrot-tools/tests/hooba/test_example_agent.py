"""FEAT-602 TASK-3747 — the example's --smoke path against the fake server."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from parrot_tools.hooba import HoobaSettings
from .fake_server import ACCOUNT_ID, PASSWORD, USERNAME, FakeHoobaState, build_fake_hooba_app

if TYPE_CHECKING:
    from aiohttp.test_utils import TestServer

EXAMPLE = Path(__file__).resolve().parents[4] / "examples" / "agents" / "finance" / "hooba_agent.py"


def _load_example_module():
    """Load the example agent by path (examples/ is not an importable package)."""
    spec = importlib.util.spec_from_file_location("hooba_agent", EXAMPLE)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load example module from {EXAMPLE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_example_smoke_against_fake_server(aiohttp_server, monkeypatch):
    """Smoke test: whoami + list_drafts('invoice') against the fake Hooba server."""
    # Set up the fake server
    state = FakeHoobaState()
    app = build_fake_hooba_app(state)
    server: TestServer = await aiohttp_server(app)

    # Point HoobaSettings at the fake server
    base_url = str(server.make_url("")).rstrip("/")
    settings = HoobaSettings(
        base_url=base_url,
        account_id=ACCOUNT_ID,
    )
    monkeypatch.setenv("HOOBA_USERNAME", USERNAME)
    monkeypatch.setenv("HOOBA_PASSWORD", PASSWORD)

    # Load the example module and build the toolkit
    module = _load_example_module()
    toolkit = module.build_toolkit(settings)

    # Run the smoke test
    result = await module.smoke(toolkit)

    # Verify both envelopes have status "success"
    assert result["whoami"]["status"] == "success", f"whoami failed: {result['whoami']}"
    assert result["drafts"]["status"] == "success", f"drafts failed: {result['drafts']}"

    # Verify whoami returned expected account info
    whoami_data = result["whoami"]["result"]
    assert whoami_data.get("accountId") == ACCOUNT_ID

    # Verify drafts is a list (empty or not)
    drafts_data = result["drafts"]["result"]
    assert isinstance(drafts_data, list)
