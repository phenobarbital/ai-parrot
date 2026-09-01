"""``FirefliesWikiKBAgent`` — the contract-facing agent façade (FEAT-481,
spec Module 1).

Exposes the operating contract's six plain-English intents (§6):
``ingest``, ``query``, ``health``, ``lint``, ``archive``, and
``build_graph_report``. Deterministic mechanics and semantic compilation
both live under ``parrot/flows/wiki_ingest/`` (nodes/renderers); this class
is a thin façade — it configures the two tiered LLM clients (G7) and
delegates each intent to its owning pipeline module.

**Additive-only (G11).** This agent instantiates its own
``ObsidianToolkit`` (Module 4) and inherits ``add_fireflies_mcp_server``
from ``MCPEnabledMixin`` (already mixed into ``AbstractBot`` →
``BasicAgent`` → ``Agent``) — no existing agent, toolkit, or config file is
modified.
"""

from __future__ import annotations

import logging
from typing import Any

from parrot.bots.agent import Agent
from parrot.clients.base import AbstractClient
from parrot.clients.factory import LLMFactory
from parrot.registry import register_agent
from parrot.scheduler import ScheduleType, schedule

from . import conf
from .runner import IngestReport, WikiIngestContext

logger = logging.getLogger(__name__)


def _cron_fields(cron: str) -> dict[str, str]:
    """Split a 5-field cron expression into ``CronTrigger`` kwargs.

    ``@schedule(schedule_type=ScheduleType.CRON, **kwargs)`` forwards
    ``schedule_config`` straight into APScheduler's ``CronTrigger(**config)``
    (``parrot.scheduler.manager``), which expects individual
    ``minute``/``hour``/``day``/``month``/``day_of_week`` keyword arguments
    — not a single cron string. :data:`~parrot.flows.wiki_ingest.conf.
    WIKI_KB_INGEST_CRON` is a standard 5-field crontab string (same order
    :meth:`~parrot.scheduler.inprocess.InProcessScheduler.add_cron` uses),
    so this helper bridges the two shapes.

    Args:
        cron: A 5-field cron expression (``"minute hour day month
            day_of_week"``).

    Returns:
        A dict with keys ``minute``, ``hour``, ``day``, ``month``,
        ``day_of_week``.

    Raises:
        ValueError: If *cron* does not have exactly 5 fields.
    """
    fields = cron.split()
    if len(fields) != 5:
        raise ValueError(
            f"WIKI_KB_INGEST_CRON must be a 5-field cron expression "
            f"('minute hour day month day_of_week'), got {cron!r}"
        )
    minute, hour, day, month, day_of_week = fields
    return {"minute": minute, "hour": hour, "day": day, "month": month, "day_of_week": day_of_week}


@register_agent(name="fireflies_wiki_kb", at_startup=True)
class FirefliesWikiKBAgent(Agent):
    """Parrot agent that faithfully executes the Obsidian LLM-Wiki
    operating contract for Fireflies meetings.

    Attributes:
        strong_client: Strong-tier :class:`AbstractClient` (reconciliation,
            ambiguous classification, contradiction reasoning) — built from
            :data:`conf.WIKI_KB_LLM_STRONG`.
        cheap_client: Cheap-tier :class:`AbstractClient` (bulk extraction,
            summary-first reads) — built from :data:`conf.WIKI_KB_LLM_CHEAP`.
    """

    def __init__(self, name: str = "FirefliesWikiKB", **kwargs: Any) -> None:
        """Initialize the façade.

        Args:
            name: Agent name.
            **kwargs: Forwarded to :class:`~parrot.bots.agent.Agent`.
        """
        super().__init__(name=name, **kwargs)
        self.strong_client: AbstractClient | None = None
        self.cheap_client: AbstractClient | None = None

    async def configure(self, app: Any = None) -> None:
        """Async setup: build the strong/cheap tier LLM clients (G7).

        Args:
            app: Optional host application, forwarded to the parent
                ``configure()``.
        """
        await super().configure(app)

        self.strong_client = LLMFactory.create(conf.WIKI_KB_LLM_STRONG)
        self.cheap_client = LLMFactory.create(conf.WIKI_KB_LLM_CHEAP)
        self.logger.info(
            "FirefliesWikiKBAgent configured: strong=%s cheap=%s",
            conf.WIKI_KB_LLM_STRONG,
            conf.WIKI_KB_LLM_CHEAP,
        )

    @schedule(schedule_type=ScheduleType.CRON, **_cron_fields(conf.WIKI_KB_INGEST_CRON))
    async def ingest(
        self,
        *,
        limit: int | None = None,
        force_refetch: bool = False,
        since: str | None = None,
        lookback_days: int | None = None,
    ) -> IngestReport:
        """Run the §27 ingest workflow (fetch → compile → validate).

        Delegates to :func:`~parrot.flows.wiki_ingest.runner.run_ingest`
        (spec Module 6), passing ``self`` so the runner can reach
        ``strong_client``/``cheap_client`` and the Fireflies MCP tool
        surface.

        Args:
            limit: Per-run cap on meetings processed (defaults to
                :data:`conf.WIKI_KB_INGEST_LIMIT`).
            force_refetch: Bypass the fetch-gate cheap-skip path.
            since: ISO date lower bound for a manual wide-window ingest.
            lookback_days: Alternative to ``since`` — how many days back
                to widen the fetch window.

        Returns:
            The :class:`IngestReport` produced by the run.
        """
        from .runner import run_ingest

        ctx = WikiIngestContext(
            limit=limit if limit is not None else conf.WIKI_KB_INGEST_LIMIT,
            force_refetch=force_refetch,
            since=since,
            lookback_days=lookback_days,
            agent=self,
        )
        return await run_ingest(ctx)

    async def query(self, question: str) -> Any:
        """Run the §28 query workflow (GraphIndex retrieval → Obsidian verify).

        Args:
            question: Free-text question about the knowledge base.

        Returns:
            The :class:`~.nodes.query.QueryResult`.

        Raises:
            RuntimeError: If ``configure()`` has not run yet (no
                ``strong_client``).
        """
        from . import vault
        from .graph import build_wiki_kb_graph_toolkit
        from .nodes.query import run_query

        if self.strong_client is None:
            raise RuntimeError("FirefliesWikiKBAgent.query() called before configure()")

        wiki_toolkit = await build_wiki_kb_graph_toolkit(conf.WIKI_KB_VAULT_PATH)
        vault_toolkit = vault.build_vault_toolkit(conf.WIKI_KB_VAULT_PATH)
        return await run_query(self.strong_client, wiki_toolkit, vault_toolkit, question)

    async def health(self) -> Any:
        """Run the §29 fast operational health check.

        Returns:
            The :class:`~.nodes.health.HealthReport`.
        """
        from . import vault
        from .nodes.health import run_health

        toolkit = vault.build_vault_toolkit(conf.WIKI_KB_VAULT_PATH)
        registry = vault.build_meeting_registry(conf.WIKI_KB_VAULT_PATH)
        return await run_health(toolkit, registry, vault_path=conf.WIKI_KB_VAULT_PATH)

    async def lint(self, *, fix: bool = False) -> Any:
        """Run the §30 integrity lint (optionally applying safe auto-fixes).

        Args:
            fix: When ``True``, apply safe auto-repairs.

        Returns:
            The :class:`~.nodes.lint.LintReport`.
        """
        from . import vault
        from .nodes.lint import run_lint

        toolkit = vault.build_vault_toolkit(conf.WIKI_KB_VAULT_PATH)
        return await run_lint(toolkit, fix=fix)

    async def archive(self) -> Any:
        """Run the §31 archive workflow (rolling active window, D7).

        Returns:
            The :class:`~.nodes.archive.ArchiveReport`.
        """
        from . import vault
        from .nodes.archive import run_archive

        toolkit = vault.build_vault_toolkit(conf.WIKI_KB_VAULT_PATH)
        registry = vault.build_meeting_registry(conf.WIKI_KB_VAULT_PATH)
        return await run_archive(toolkit, registry)

    async def build_graph_report(self, target: str) -> Any:
        """Run the §32 derived graph report workflow.

        Args:
            target: The graph report target (contract-defined scope).

        Returns:
            The :class:`~.nodes.graph_report.GraphReportResult`.
        """
        from . import vault
        from .nodes.graph_report import run_graph_report

        toolkit = vault.build_vault_toolkit(conf.WIKI_KB_VAULT_PATH)
        return await run_graph_report(toolkit, target)
