"""Unit tests for the wiki-ingest subsystem scaffolding (FEAT-481,
spec Module 1 / TASK-2660).

Covers: package import, agent registration, config defaults, and
``configure()`` building the strong/cheap tier clients from
``provider:model`` config strings (Google default, G7).
"""

from __future__ import annotations

import pytest

# The `ingest` intent is decorated with @schedule(schedule_type=
# ScheduleType.CRON, ...), which resolves through the ai-parrot-server
# satellite lazily at class-definition time (parrot/scheduler/__init__.py).
# Same convention as packages/ai-parrot/tests/test_schedules.py.
pytest.importorskip("apscheduler")

from parrot.flows.wiki_ingest import conf
from parrot.flows.wiki_ingest.agent import FirefliesWikiKBAgent
from parrot.registry import agent_registry


def test_agent_module_imports_and_registers() -> None:
    """The façade module imports cleanly and self-registers under its
    contract-facing name (spec Module 1)."""
    assert "fireflies_wiki_kb" in agent_registry.list_agent_names()


def test_conf_defaults() -> None:
    """Config defaults match spec Module 1 exactly."""
    assert conf.WIKI_KB_LLM_STRONG == "google:gemini-2.5-pro"
    assert conf.WIKI_KB_LLM_CHEAP == "google:gemini-2.5-flash"
    assert conf.WIKI_KB_INGEST_CRON == "0 * * * *"
    assert conf.WIKI_KB_ACTIVE_WINDOW_DAYS == 14
    assert conf.WIKI_KB_RAW_ROOT == "Raw"
    assert conf.FIREFLIES_WIKI_EMAIL_ENABLED is False
    # Reused, not redefined (G11) — FEAT-472's overlap-days knob.
    assert isinstance(conf.FIREFLIES_SYNC_OVERLAP_DAYS, int)


@pytest.mark.asyncio
async def test_agent_configure_builds_tier_clients() -> None:
    """``configure()`` builds strong + cheap clients from the
    ``provider:model`` config (Google default, G7)."""
    agent = FirefliesWikiKBAgent()
    await agent.configure()
    assert agent.strong_client is not None
    assert agent.cheap_client is not None


@pytest.mark.asyncio
async def test_ingest_delegates_to_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ingest()`` delegates to ``runner.run_ingest``, passing itself as
    ``ctx.agent`` (spec Module 6 — TASK-2672 wires the full pipeline)."""
    from unittest.mock import AsyncMock

    from parrot.flows.wiki_ingest import runner as runner_module

    agent = FirefliesWikiKBAgent()
    await agent.configure()

    captured_ctx = {}

    async def _fake_run_ingest(ctx):
        captured_ctx["ctx"] = ctx
        return runner_module.IngestReport(processed=1)

    monkeypatch.setattr(runner_module, "run_ingest", AsyncMock(side_effect=_fake_run_ingest))

    report = await agent.ingest(limit=5)

    assert report.processed == 1
    assert captured_ctx["ctx"].agent is agent
    assert captured_ctx["ctx"].limit == 5
