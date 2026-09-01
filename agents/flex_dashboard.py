"""FlexDashboard — FEAT-491: A2UI dashboard agent for the Flex program.

Composes :class:`NarrativeMixin` and :class:`InfographicAuthoringMixin` onto
:class:`PandasAgent` (mirroring `agents/finance_reporter.py`, FEAT-420) and
gives the agent's ``DatasetManager`` lazy access to the six Flex QuerySource
slugs (spec §2): Master Store List, Finance results, Hours, Employees,
Region utilization, and Rep utilization.

Sibling package ``agents/flex_dashboard/`` holds the pure normalization
layer (:mod:`agents.flex_dashboard.normalize`), the registered
``@infographic_transformer`` functions (:mod:`agents.flex_dashboard.
transformers`), the kb docs (``kb/*.md``), and the composite skills
(``skills/``) — same file+package coexistence pattern as
``agents/finance_reporter.py``::

    agent = FlexDashboard(name="flex-dashboard", recipe_store=store)
    await agent.configure()

See ``sdd/specs/flex-agent-infographic-a2ui.spec.md`` for the full design.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from aiohttp import web
from parrot.bots.data import PandasAgent
from parrot.bots.mixins import InfographicAuthoringMixin, NarrativeMixin
from parrot.registry import register_agent
from parrot.tools.working_memory import WorkingMemoryToolkit

# Import side effect ONLY: registers the Flex transformers (payroll_hero,
# worked_hours_by_month, ..., flex_narrative_facts) on the shared
# `transformer_registry` — see agents/flex_dashboard/transformers.py.
import agents.flex_dashboard.transformers  # noqa: F401

#: This file's own directory — skill_paths/kb glob MUST anchor here, never
#: to process cwd (finance_reporter.py's FEAT-420 lesson, SKILLS_DIR note).
_AGENT_DIR = Path(__file__).resolve().parent
_PACKAGE_DIR = _AGENT_DIR / "flex_dashboard"
SKILLS_DIR = _PACKAGE_DIR / "skills"
KB_DIR = _PACKAGE_DIR / "kb"

#: Frozen dataset aliases (spec §2) — every transformer hard-codes these as
#: its input frame key. Changing one means changing both sides (spec §7
#: Known Risks: "Alias ↔ transformer-key 1:1").
DATASET_SLUGS: dict[str, str] = {
    "msl": "flex_msl_brian_bi",
    "finance": "Finance_results_bi",  # capital F — verbatim, spec §7 gotcha
    "hours": "flex_hours_query_pbi",
    "employees": "flex_empolyees_brian_bi",
    "region_utilization": "fm_regions_avg_employees_html",
    "rep_utilization": "fm_rep_utilization",
}


def _build_default_artifact_store() -> Any:
    """Build an offline-safe default ``ArtifactStore`` (no network/DB).

    Local SQLite conversation backend + local-filesystem overflow store —
    the same offline primitives ``examples/agents/a2ui/
    deterministic_refresh_dashboard.py`` uses for its synthetic-data demo.
    Construction is cheap (no I/O): ``ConversationSQLiteBackend.__init__``
    only stores the path; the schema is created lazily by its (async)
    ``initialize()``, which callers invoke before first real use.

    Returns:
        A ready-to-use :class:`~parrot.storage.artifacts.ArtifactStore`.
    """
    from parrot.storage.artifacts import ArtifactStore
    from parrot.storage.backends import build_overflow_store
    from parrot.storage.backends.sqlite import ConversationSQLiteBackend

    backend = ConversationSQLiteBackend(path=":memory:")
    return ArtifactStore(backend, build_overflow_store())


@register_agent(name="flex_dashboard")
class FlexDashboard(NarrativeMixin, InfographicAuthoringMixin, PandasAgent):
    """Flex program KPI + dashboard agent over six QuerySource datasets."""

    agent_id: str = "flex_dashboard"
    llm = "google:gemini-3.5-flash"
    narrative_skill = "flex-narrative"

    #: Directory-discovery opt-in (FEAT-420-derived pattern) — anchored to
    #: this file's own location so `/widget`, `/infographic`, and
    #: `flex-narrative` are found regardless of process cwd.
    skill_paths: ClassVar[list[Path]] = [SKILLS_DIR]

    DASHBOARD_RECIPE_NAME = "flex-program-dashboard"

    def __init__(
        self,
        *args: Any,
        tools: list[Any] | None = None,
        artifact_store: Any | None = None,
        recipe_store: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Attach WorkingMemory + Infographic toolkits, enable kb + routing.

        Args:
            tools: Extra tools beyond the two attached here.
            artifact_store: Optional pre-built ``ArtifactStore`` forwarded to
                ``InfographicAuthoringMixin`` (which builds the
                ``InfographicToolkit`` from it). Defaults to an offline-safe
                local store (see :func:`_build_default_artifact_store`) so
                the agent instantiates without network/DB.
            recipe_store: Optional recipe store forwarded to
                ``InfographicAuthoringMixin`` (enables ``publish_recipe``
                tier-2 authoring and the toolkit's recipe tools).
            **kwargs: Forwarded to the cooperative ``__init__`` chain.
        """
        tools = list(tools or [])
        tools.append(WorkingMemoryToolkit())

        super().__init__(
            *args,
            tools=tools,
            artifact_store=artifact_store or _build_default_artifact_store(),
            recipe_store=recipe_store,
            output_routing=True,
            use_kb=True,
            llm=kwargs.pop("llm", None) or self.llm,
            **kwargs,
        )

    async def register_datasets(self) -> None:
        """Lazily register the six Flex QuerySource slugs (spec §2).

        Uses ``DatasetManager.add_query`` — the genuinely lazy registration
        path (registers a ``QuerySlugSource`` with NO fetch; data loads on
        first ``fetch_dataset()``/REPL access). ``DatasetManager.add_dataset
        (query_slug=...)`` is NOT used here: it fetches immediately (see the
        Codebase Contract correction in this feature's TASK-2696), which
        would violate "no eager fetch at construction/configure time".
        """
        self._dataset_manager.add_query(
            name="msl",
            query_slug=DATASET_SLUGS["msl"],
            description=(
                "Master Store List: district/region/market/account/store, "
                "lat/lon, city, state. Used for Proximity Staffing."
            ),
            usage_guidance={"do": ["Proximity Staffing store-side geo lookups"]},
        )
        self._dataset_manager.add_query(
            name="finance",
            query_slug=DATASET_SLUGS["finance"],
            description=(
                "Monthly P&L per project: Revenue, PC Revenue, EBITDA, "
                "Payroll, Travel and Expenses, Program Overhead Allocation, "
                "Other Related Expenses, Total Hours, FTE, Visits. Currency "
                "columns arrive as formatted strings."
            ),
            usage_guidance={
                "do": [
                    "Payroll / Revenue / Payroll % to Revenue by month",
                    "FTE cross-check via Total Hours (never Worked Hours source)",
                ],
            },
        )
        self._dataset_manager.add_query(
            name="hours",
            query_slug=DATASET_SLUGS["hours"],
            description=(
                "Hours/wages by month, program, pay_code, cost_center."
            ),
            usage_guidance={
                "do": [
                    "Worked Hours by Month",
                    "Pay Code Hours / Worked Hours by Pay Code Allocation",
                ],
            },
        )
        self._dataset_manager.add_query(
            name="employees",
            query_slug=DATASET_SLUGS["employees"],
            description=(
                "Employee roster with lat/lon, Flex Type, service tenure."
            ),
            usage_guidance={"do": ["Proximity Staffing employee-side geo lookups"]},
        )
        self._dataset_manager.add_query(
            name="region_utilization",
            query_slug=DATASET_SLUGS["region_utilization"],
            description=(
                "Regional monthly employee utilization (BOP/EOP dates); "
                "precomputed Employee Utilization column."
            ),
            usage_guidance={
                "do": ["Cross-check for recomputed Rep Utilization — never the source of truth"],
            },
        )
        self._dataset_manager.add_query(
            name="rep_utilization",
            query_slug=DATASET_SLUGS["rep_utilization"],
            description=(
                "Rep utilization by region/state/category per month "
                "(raw 'catagory' typo column)."
            ),
            usage_guidance={
                "do": ["Rep Utilization = employees_worked / average_active, recomputed"],
            },
        )

    async def _load_kb_docs(self) -> None:
        """Load each ``agents/flex_dashboard/kb/*.md`` doc as one kb fact.

        Requires ``self.kb_store`` to already exist (``use_kb=True`` in
        ``__init__``). Called AFTER ``super().configure()`` so any facts
        ``configure_kb()`` already added (from ``self._kb``, empty here)
        are unaffected — this simply appends the file-based facts.
        """
        if not self.kb_store:
            return
        facts = []
        for doc_path in sorted(KB_DIR.glob("*.md")):
            facts.append(
                {
                    "content": doc_path.read_text(),
                    "metadata": {"category": "kpi", "kpi": doc_path.stem},
                }
            )
        if facts:
            await self.kb_store.add_facts(facts)

    async def configure(
        self,
        app: web.Application | None = None,
        queries: list[str] | dict | None = None,
    ) -> None:
        """Register datasets, run base configuration, then load kb docs."""
        await self.register_datasets()
        await super().configure(app=app, queries=queries)
        await self._load_kb_docs()
