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
    """The CODE defaults (fallbacks) match spec Module 1 exactly.

    ``WIKI_KB_LLM_*`` (and the rest) are env-overridable per Module 1 ("exact ids
    via env"), and ``conf`` resolves them from ``env/.env`` at import — so this test
    must NOT depend on the operator's ambient env. It stubs the navconfig source to
    return each key's declared ``fallback`` (i.e. "key not set anywhere"), reloads
    ``conf``, asserts the code defaults, then restores.
    """
    import importlib

    from navconfig import config as navconf
    from parrot.flows.wiki_ingest import conf as conf_module

    saved = (navconf.get, navconf.getint, navconf.getboolean, navconf.getlist)
    navconf.get = lambda key, fallback=None: fallback  # type: ignore[assignment,method-assign]
    navconf.getint = lambda key, fallback=None: fallback  # type: ignore[assignment,method-assign]
    navconf.getboolean = lambda key, fallback=None: fallback  # type: ignore[assignment,method-assign]
    navconf.getlist = lambda key: []  # type: ignore[assignment,method-assign]
    try:
        importlib.reload(conf_module)
        assert conf_module.WIKI_KB_LLM_STRONG == "google:gemini-2.5-pro"
        assert conf_module.WIKI_KB_LLM_CHEAP == "google:gemini-2.5-flash"
        assert conf_module.WIKI_KB_INGEST_CRON == "0 * * * *"
        assert conf_module.WIKI_KB_ACTIVE_WINDOW_DAYS == 14
        assert conf_module.WIKI_KB_RAW_ROOT == "Raw"
        assert conf_module.FIREFLIES_WIKI_EMAIL_ENABLED is False
        assert conf_module.WIKI_KB_MAX_REPROCESS_ATTEMPTS == 3
        # Reused, not redefined (G11) — FEAT-472's overlap-days knob.
        assert isinstance(conf_module.FIREFLIES_SYNC_OVERLAP_DAYS, int)
    finally:
        navconf.get, navconf.getint, navconf.getboolean, navconf.getlist = saved  # type: ignore[method-assign]
        importlib.reload(conf_module)  # restore env-resolved values for other tests


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


class _CtxClient:
    """Minimal async-context client that records enter/exit (no network / SDK).

    Stands in for a tier LLM client to prove the agent opens it: the real
    runner calls ``client.invoke()``, which raises unless the per-loop client is
    entered — so the intents MUST open their clients (Module 1 lifecycle fix).
    """

    def __init__(self) -> None:
        self.entered = False
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self) -> "_CtxClient":
        self.entered = True
        self.enter_count += 1
        return self

    async def __aexit__(self, *exc: object) -> bool:
        self.entered = False
        self.exit_count += 1
        return False


@pytest.mark.asyncio
async def test_ingest_opens_both_tier_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ingest()`` opens BOTH tier clients for the duration of the run and closes
    them after — so the runner's ``client.invoke()`` calls never hit the
    "not initialised" guard (regression test for the client-lifecycle fix)."""
    from parrot.flows.wiki_ingest import runner as runner_module

    agent = FirefliesWikiKBAgent()
    strong, cheap = _CtxClient(), _CtxClient()
    agent.strong_client = strong  # type: ignore[assignment]
    agent.cheap_client = cheap  # type: ignore[assignment]

    seen: dict[str, bool] = {}

    async def _fake_run_ingest(ctx: object) -> object:
        # The clients must be OPEN at the moment the runner uses them.
        seen["strong"] = ctx.agent.strong_client.entered  # type: ignore[attr-defined]
        seen["cheap"] = ctx.agent.cheap_client.entered  # type: ignore[attr-defined]
        return runner_module.IngestReport(processed=1)

    monkeypatch.setattr(runner_module, "run_ingest", _fake_run_ingest)

    report = await agent.ingest(limit=1)

    assert report.processed == 1
    assert seen == {"strong": True, "cheap": True}
    assert strong.enter_count == 1 and cheap.enter_count == 1
    assert strong.exit_count == 1 and cheap.exit_count == 1  # closed after the run


@pytest.mark.asyncio
async def test_ingest_before_configure_raises_clear_error() -> None:
    """``ingest()`` before ``configure()`` (clients unset) raises a clear error,
    not an opaque 'not initialised' from deep inside the pipeline."""
    agent = FirefliesWikiKBAgent()
    with pytest.raises(RuntimeError, match="called before configure"):
        await agent.ingest(limit=1)


@pytest.mark.asyncio
async def test_query_opens_strong_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """``query()`` opens the strong-tier client for the run and closes it after."""
    from unittest.mock import AsyncMock

    from parrot.flows.wiki_ingest import graph as graph_module
    from parrot.flows.wiki_ingest import vault as vault_module
    from parrot.flows.wiki_ingest.nodes import query as query_module

    agent = FirefliesWikiKBAgent()
    strong = _CtxClient()
    agent.strong_client = strong  # type: ignore[assignment]

    monkeypatch.setattr(graph_module, "build_wiki_kb_graph_toolkit", AsyncMock(return_value=object()))
    monkeypatch.setattr(vault_module, "build_vault_toolkit", lambda _vp: object())

    seen: dict[str, bool] = {}

    async def _fake_run_query(client: object, _wiki: object, _vault: object, _question: str) -> str:
        seen["entered"] = client.entered  # type: ignore[attr-defined]
        return "answer"

    monkeypatch.setattr(query_module, "run_query", _fake_run_query)

    result = await agent.query("what did we decide?")

    assert result == "answer"
    assert seen["entered"] is True
    assert strong.enter_count == 1 and strong.exit_count == 1
