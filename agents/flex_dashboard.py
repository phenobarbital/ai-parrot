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
(``skills/``)::

    agent = FlexDashboard(name="flex-dashboard", recipe_store=store)
    await agent.configure()
    recipe = await agent.publish_dashboard_recipe(overwrite=True)

.. warning::

   **Known, confirmed limitation (external code review finding)**: because
   ``agents/flex_dashboard/`` is a REGULAR package (has its own
   ``__init__.py``), Python's ``FileFinder`` always resolves a plain
   ``import agents.flex_dashboard`` — or ``from agents.flex_dashboard
   import FlexDashboard`` — to that PACKAGE, never to THIS file, even
   though ``FlexDashboard`` is only ever defined here. This is reproducible
   directly (``python -c "from agents.flex_dashboard import
   FlexDashboard"`` raises ``ImportError``). It does NOT affect the
   application as actually deployed: ``parrot.registry.registry
   .AgentRegistry._load_modules_from_directory`` — the real production
   agent-discovery path — globs ``agents/*.py`` and loads each file via
   ``importlib.util.spec_from_file_location`` under a synthetic name,
   never a plain dotted import, so ``@register_agent(name="flex_dashboard")``
   fires correctly at boot. Every test file and the example runner in this
   feature load this module the SAME way for the same reason (see any
   test file's ``_load_module``/``_load_package`` helpers). A caller that
   writes the natural ``from agents.flex_dashboard import FlexDashboard``
   in a notebook, script, or a future ``agents.yaml``-driven
   ``config.module`` entry WILL hit this ``ImportError`` — there is no
   compositional fix available from within this agent's own file(s) that
   preserves both "the class is importable via the natural path" and "the
   sibling package's submodules (``normalize``/``transformers``) are
   importable" simultaneously with this exact file/directory naming.
   Resolving it for real requires renaming the sibling package (e.g. to
   ``agents/flex_dashboard_kit/``) and updating every internal reference —
   out of scope for this feature to do unilaterally, since the spec's own
   Module 3 architecture mandates the current name; flagged here for the
   PR reviewer to decide.

Prefer :meth:`FlexDashboard.publish_dashboard_recipe` over calling the
inherited ``publish_recipe()`` directly for ``DASHBOARD_RECIPE_NAME`` — the
base mixin has no ``params=`` argument, so a bare ``publish_recipe()`` call
leaves the recipe's declared ``RecipeParam`` overrides unset, which breaks
even the unfiltered default replay (see ``publish_dashboard_recipe``'s own
docstring for the full reasoning).

See ``sdd/specs/flex-agent-infographic-a2ui.spec.md`` for the full design.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from aiohttp import web
from parrot.bots.data import PandasAgent
from parrot.bots.mixins import InfographicAuthoringMixin, NarrativeMixin
from parrot.outputs.a2ui.recipes.models import LayoutSpec, NarrativeSpec, RecipeParam
from parrot.registry import register_agent
from parrot.tools.abstract import (
    AbstractTool,
    AbstractToolArgsSchema,
    current_a2ui_surface_state,
)
from parrot.tools.infographic_recipes.runner import RecipeRunner
from parrot.tools.infographic_sections import GapReport, SectionDescriptor, SectionSpec
from parrot.tools.working_memory import WorkingMemoryToolkit
from pydantic import Field

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

    #: Temporary workaround: the WorkerPool-backed sandbox
    #: (`PythonREPLTool`'s default `execution_mode="worker"`) is currently
    #: unable to operate. Pins this agent's `python_repl_pandas` tool to
    #: `execution_mode="inprocess"` (generated code runs inside the host
    #: process — no process isolation, rlimits, or SIGKILL deadline; see
    #: `parrot.tools.pythonrepl.PythonREPLTool.__init__`) so the agent stays
    #: usable while the worker pool is down. Override per-instance with the
    #: `python_repl_execution_mode=` constructor kwarg (e.g. `"worker"`) once
    #: it's fixed, or flip this class attribute back to `"worker"`.
    python_repl_execution_mode: ClassVar[str] = "inprocess"

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
            python_repl_execution_mode=(
                kwargs.pop("python_repl_execution_mode", None) or self.python_repl_execution_mode
            ),
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
            description=("Hours/wages by month, program, pay_code, cost_center."),
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
            description=("Employee roster with lat/lon, Flex Type, service tenure."),
            usage_guidance={"do": ["Proximity Staffing employee-side geo lookups"]},
        )
        self._dataset_manager.add_query(
            name="region_utilization",
            query_slug=DATASET_SLUGS["region_utilization"],
            description=(
                "Regional monthly employee utilization (BOP/EOP dates); " "precomputed Employee Utilization column."
            ),
            usage_guidance={
                "do": ["Cross-check for recomputed Rep Utilization — never the source of truth"],
            },
        )
        self._dataset_manager.add_query(
            name="rep_utilization",
            query_slug=DATASET_SLUGS["rep_utilization"],
            description=("Rep utilization by region/state/category per month " "(raw 'catagory' typo column)."),
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

    # ── Dashboard recipe (TASK-2697, spec §3 Module 4) ──────────────────

    @classmethod
    def _transform_sections(cls) -> list[SectionSpec]:
        """Sections whose NAMES are registered transformer names.

        Order matters: ``publish_recipe`` preserves ``descriptor.sections``
        order into ``TransformStep`` order, and ``flex_narrative_facts``
        consumes the other steps' outputs — it must come last
        (FinanceReporter pattern, ``agents/finance_reporter.py:189-223``).
        """
        return [
            SectionSpec(
                name="payroll_hero",
                target="/payroll_hero",
                datasets=["hours", "finance"],
                shape="mapping",
            ),
            SectionSpec(
                name="worked_hours_by_month",
                target="/worked_hours_by_month",
                datasets=["hours"],
                shape="mapping",
            ),
            SectionSpec(
                name="payroll_by_month",
                target="/payroll_by_month",
                datasets=["finance"],
                shape="mapping",
            ),
            SectionSpec(
                name="revenue_by_month",
                target="/revenue_by_month",
                datasets=["finance"],
                shape="mapping",
            ),
            SectionSpec(
                name="payroll_pct_by_month",
                target="/payroll_pct_by_month",
                datasets=["finance"],
                shape="mapping",
            ),
            SectionSpec(
                name="pay_code_hours",
                target="/pay_code_hours",
                datasets=["hours"],
                shape="mapping",
            ),
            SectionSpec(
                name="pay_code_allocation",
                target="/pay_code_allocation",
                datasets=["hours"],
                shape="mapping",
            ),
            SectionSpec(
                name="rep_utilization_by_region",
                target="/rep_utilization_by_region",
                datasets=["rep_utilization", "region_utilization"],
                shape="mapping",
            ),
            SectionSpec(
                name="proximity_staffing",
                target="/proximity_staffing",
                datasets=["msl", "employees"],
                shape="mapping",
            ),
            SectionSpec(
                name="flex_narrative_facts",
                target="/flex_narrative_facts",
                # Prior-step output_keys, NOT dataset aliases — the generic
                # shape resolved in FEAT-420 Module 1 (spec §2 Overview).
                datasets=["payroll_hero", "worked_hours_by_month", "rep_utilization_by_region"],
                shape="mapping",
            ),
        ]

    @classmethod
    def _narrative_spec(cls) -> NarrativeSpec:
        """Declarative narrative step — optional, replays with no narrator."""
        return NarrativeSpec(skill=cls.narrative_skill, facts_key="flex_narrative_facts")

    #: Descriptor-level ``{param}`` templates, applied IDENTICALLY to every
    #: ``TransformStep`` by ``publish_recipe`` — each transformer only reads
    #: the keys it declared support for (per-section filter rule, spec
    #: proposal U1, enforced in ``agents/flex_dashboard/transformers.py``).
    _RECIPE_PARAM_TEMPLATE: ClassVar[dict[str, str]] = {
        "month": "{month}",
        "flex_type": "{flex_type}",
        "pay_code": "{pay_code}",
        "cost_center": "{cost_center}",
        "category": "{category}",
        "radius_miles": "{radius_miles}",
        "nearest_n": "{nearest_n}",
    }

    @classmethod
    def recipe_params(cls) -> list[RecipeParam]:
        """Declared, overridable filter params for the published recipe.

        ``resolve_params`` (``parrot.outputs.a2ui.recipes.params``) raises
        when a declared param has no default AND no override is supplied —
        every param below therefore needs a concrete, non-``None`` default.
        Optional filters default to ``""``, which
        ``agents/flex_dashboard/transformers.py``'s ``_apply_filters``
        treats the same as "unset" (falsy check) — the sentinel that makes
        an unfiltered replay work with no caller-supplied overrides.
        """
        return [
            RecipeParam(name="month", default="", description="YYYY-MM filter."),
            RecipeParam(name="flex_type", default="", description="Employee Flex Type filter."),
            RecipeParam(name="pay_code", default="", description="Pay code filter."),
            RecipeParam(name="cost_center", default="", description="Cost center filter."),
            RecipeParam(
                name="category",
                default="",
                description="Rep utilization category filter.",
            ),
            RecipeParam(
                name="radius_miles",
                default="50",
                description="Proximity Staffing coverage radius, miles.",
            ),
            RecipeParam(
                name="nearest_n",
                default="3",
                description="Proximity Staffing nearest-N count.",
            ),
        ]

    @classmethod
    def dashboard_descriptor(cls) -> SectionDescriptor:
        """Flex program dashboard: hero row + month series + pay-code +
        utilization + proximity sections, LayoutSpec v2."""
        return SectionDescriptor(
            template="unused-with-layout",  # layout below is used verbatim
            mode="data-splice",
            sections=cls._transform_sections(),
            params=dict(cls._RECIPE_PARAM_TEMPLATE),
            # v2 LayoutSpec (FEAT-470 TASK-2542): props top-level, `{"path"}`
            # bindings; nested Infographic section-component descriptors
            # keep their OWN "properties" wrapper (the composite's own
            # authored-descriptor shape, not the wire Component shape
            # LayoutSpec mirrors — agents/finance_reporter.py:267-273
            # comment); a binding's `optional` marker moves to the layout's
            # own `metadata.extensions.parrot_optional`.
            layout=LayoutSpec(
                component="Infographic",
                title="Flex Program Dashboard",
                sections=[
                    {
                        "heading": "Payroll Contribution — Hero",
                        "components": [
                            {
                                "component": "KPICard",
                                "properties": {
                                    "label": "Worked Hours",
                                    "value": {"path": "/payroll_hero/worked_hours_total"},
                                },
                            },
                            {
                                "component": "KPICard",
                                "properties": {
                                    "label": "Payroll",
                                    "value": {"path": "/payroll_hero/payroll_total"},
                                },
                            },
                            {
                                "component": "KPICard",
                                "properties": {
                                    "label": "P&L Revenue",
                                    "value": {"path": "/payroll_hero/revenue_total"},
                                },
                            },
                            {
                                "component": "KPICard",
                                "properties": {
                                    "label": "Payroll % to Revenue",
                                    "value": {"path": "/payroll_hero/payroll_pct"},
                                },
                            },
                        ],
                    },
                    {
                        "heading": "Payroll Contribution — Month Series",
                        "components": [
                            {
                                "component": "Chart",
                                "properties": {
                                    "title": "Worked Hours by Month",
                                    "type": "line",
                                    "x": "month",
                                    "y": ["worked_hours"],
                                    "data": {"path": "/worked_hours_by_month/series"},
                                },
                            },
                            {
                                "component": "Chart",
                                "properties": {
                                    "title": "Payroll by Month",
                                    "type": "line",
                                    "x": "month",
                                    "y": ["payroll"],
                                    "data": {"path": "/payroll_by_month/series"},
                                },
                            },
                            {
                                "component": "Chart",
                                "properties": {
                                    "title": "P&L Revenue by Month",
                                    "type": "line",
                                    "x": "month",
                                    "y": ["revenue"],
                                    "data": {"path": "/revenue_by_month/series"},
                                },
                            },
                            {
                                "component": "Chart",
                                "properties": {
                                    "title": "Payroll % to Revenue by Month",
                                    "type": "line",
                                    "x": "month",
                                    "y": ["payroll_pct"],
                                    "data": {"path": "/payroll_pct_by_month/series"},
                                },
                            },
                        ],
                    },
                    {
                        "heading": "Pay Code",
                        "components": [
                            {
                                "component": "DataTable",
                                "properties": {
                                    "columns": [{"name": "pay_code"}, {"name": "hours"}],
                                    "data": {"path": "/pay_code_hours/records"},
                                },
                            },
                            {
                                "component": "DataTable",
                                "properties": {
                                    "columns": [
                                        {"name": "pay_code"},
                                        {"name": "hours"},
                                        {"name": "share_pct"},
                                    ],
                                    "data": {"path": "/pay_code_allocation/records"},
                                },
                            },
                        ],
                    },
                    {
                        "heading": "Rep Utilization",
                        "components": [
                            {
                                "component": "DataTable",
                                "properties": {
                                    "columns": [
                                        {"name": "region"},
                                        {"name": "category"},
                                        {"name": "month"},
                                        {"name": "utilization"},
                                        {"name": "cross_check_utilization"},
                                    ],
                                    "data": {"path": "/rep_utilization_by_region/records"},
                                },
                            },
                        ],
                    },
                    {
                        "heading": "Proximity Staffing",
                        # NOTE (TASK-2699 finding): NOT binding a "text":
                        # {"path": "/narrative"} field here, unlike
                        # FinanceReporter's identical-looking pattern
                        # (finance_reporter.py's "Top Movers" section) —
                        # `RecipeRunner._assemble_envelope_or_raise`'s
                        # Infographic path (`build_infographic` ->
                        # `build_surface`) never threads `layout.metadata`
                        # (and therefore never `metadata.extensions.
                        # parrot_optional`) onto the built wire `Component`,
                        # so ANY layout-level binding to an absent
                        # `/narrative` key raises `BakeError` unconditionally
                        # at render time — regardless of the optional-paths
                        # declared on `LayoutSpec.metadata`. This is a
                        # pre-existing, cross-cutting core bug (confirmed
                        # reproducible on `dev`, unrelated to FEAT-491):
                        # FinanceReporter's OWN e2e tests for this exact
                        # behavior — `test_dashboard_profile_replay` AND
                        # `test_report_profile_replay_no_narrator` — are
                        # BOTH independently broken by it too. Filing a fix
                        # in core is out of this feature's scope (spec §1
                        # Non-Goals: "No changes to core packages"); the
                        # `narrative=` `NarrativeSpec` below is kept (a
                        # narrator, if ever configured, still runs and
                        # populates `/narrative` in the data model — it
                        # just is not bound anywhere in this layout, so its
                        # ABSENCE never triggers the runner's broken
                        # optional-binding check in the first place).
                        "components": [
                            {
                                "component": "Map",
                                "properties": {
                                    "title": "Store & Employee Proximity",
                                    "layers": [
                                        {
                                            "layer": "stores",
                                            "labelField": "store_name",
                                            "markerColor": "#1f77b4",
                                            "dataShape": "rows",
                                            "columns": [
                                                {"name": "store_name"},
                                                {"name": "latitude"},
                                                {"name": "longitude"},
                                            ],
                                            "data": {"path": "/proximity_staffing/store_layer"},
                                        },
                                        {
                                            "layer": "employees",
                                            "labelField": "display_name",
                                            "markerColor": "#ff7f0e",
                                            "dataShape": "rows",
                                            "columns": [
                                                {"name": "display_name"},
                                                {"name": "latitude"},
                                                {"name": "longitude"},
                                            ],
                                            "data": {"path": "/proximity_staffing/employee_layer"},
                                        },
                                    ],
                                },
                            },
                            {
                                "component": "DataTable",
                                "properties": {
                                    "columns": [
                                        {"name": "store_name"},
                                        {"name": "nearest_employees"},
                                        {"name": "employees_within_radius"},
                                    ],
                                    "data": {"path": "/proximity_staffing/coverage"},
                                },
                            },
                        ],
                    },
                ],
                # No `metadata.extensions.parrot_optional` entry: nothing in
                # this layout binds `/narrative` (see the Proximity Staffing
                # section's NOTE above) — there is no optional pointer to
                # declare.
            ),
            narrative=cls._narrative_spec(),
        )

    async def publish_dashboard_recipe(self, *, overwrite: bool = False) -> Any:
        """Publish the dashboard recipe AND persist its declared filter params.

        Code-review finding (adopted): ``InfographicAuthoringMixin
        .publish_recipe()`` has no ``params=`` argument — it never persists
        ``RecipeParam`` declarations on its own. A caller that publishes via
        the base ``publish_recipe()`` directly and forgets the follow-up
        ``recipe.params = FlexDashboard.recipe_params(); await
        recipe_store.save(recipe)`` step gets a recipe with `params=[]`,
        which makes EVERY replay fail — even the unfiltered default one —
        because ``dashboard_descriptor()``'s ``{month}``/etc. placeholders
        have nothing to resolve against (``resolve_params`` raises). This
        wraps both steps atomically so that footgun cannot happen; prefer
        this over calling ``publish_recipe`` directly for
        ``DASHBOARD_RECIPE_NAME``.

        Args:
            overwrite: Forwarded to ``publish_recipe`` — replace an
                existing ``(name, owner)`` recipe when True.

        Returns:
            The saved :class:`~parrot.outputs.a2ui.recipes.models.InfographicRecipe`,
            or a :class:`~parrot.tools.infographic_sections.GapReport` on
            partial transformer coverage (nothing is saved in that case,
            matching ``publish_recipe``'s own contract).
        """
        recipe = await self.publish_recipe(self.DASHBOARD_RECIPE_NAME, self.dashboard_descriptor(), overwrite=overwrite)
        if isinstance(recipe, GapReport):
            return recipe
        recipe.params = self.recipe_params()
        await self._require_recipe_store().save(recipe)
        return recipe

    # ── Refresh lane (FEAT-469 pattern) ─────────────────────────────────

    def build_refresh_tool(self, pctx: Any) -> RefreshDashboardTool:
        """Build and register the ``refresh_dashboard`` tool.

        Requires a recipe store to already be wired (``recipe_store=`` at
        construction, or a toolkit configured with one) — raises via
        ``_require_recipe_store()`` otherwise.

        Args:
            pctx: A real ``PermissionContext`` (e.g. from
                ``build_principal_context``). ``RecipeRunner.run`` fails
                OPEN on a falsy ``pctx`` (its own docstring warning) — never
                pass ``None`` here.

        Returns:
            The registered :class:`RefreshDashboardTool` instance.
        """
        runner = RecipeRunner(self._require_recipe_store(), self._dataset_manager)
        tool = RefreshDashboardTool(runner=runner, pctx=pctx)
        self.tool_manager.add_tool(tool)
        return tool


class RefreshDashboardArgs(AbstractToolArgsSchema):
    """Arguments the renderer may pass on ``callAgentFunction``."""

    month: str | None = Field(default=None, description="YYYY-MM filter.")
    flex_type: str | None = Field(default=None, description="Employee Flex Type filter.")
    pay_code: str | None = Field(default=None, description="Pay code filter.")
    cost_center: str | None = Field(default=None, description="Cost center filter.")
    category: str | None = Field(default=None, description="Rep utilization category filter.")
    radius_miles: float | None = Field(default=None, description="Proximity Staffing coverage radius, miles.")
    nearest_n: int | None = Field(default=None, description="Proximity Staffing nearest-N count.")


class RefreshDashboardTool(AbstractTool):
    """Deterministically re-render the Flex dashboard, optionally filtered.

    Filter precedence per call (FEAT-469 example pattern): explicit args
    (the renderer's inline filter widget) → the surface's last persisted
    ``dataModel.filters`` (read via ``current_a2ui_surface_state()``) →
    the recipe's own declared defaults (empty-string "no filter" / 50 / 3).

    Permission-context precedence (code-review finding, adopted): the
    PER-CALL ``PermissionContext`` — injected by ``AbstractTool.execute()``
    onto ``self._current_pctx`` whenever the caller (e.g.
    ``ToolManagerExecutor.call`` → ``ToolManager.execute_tool``) supplies
    one via the ``_permission_context`` kwarg — always wins over the
    ``pctx`` captured at construction time. On a shared/pooled agent
    instance serving multiple callers, always using the CONSTRUCTION-time
    ``pctx`` would let one user's DatasetManager PBAC/tenant scope leak
    into another user's refresh. The constructor ``pctx`` is kept only as
    the fallback for direct/demo calls that never go through
    ``ToolManager.execute_tool`` (e.g. this feature's own example runner).
    """

    name = "refresh_dashboard"
    description = (
        "Re-render the Flex program dashboard deterministically via its "
        "published recipe. Optional filters: month, flex_type, pay_code, "
        "cost_center, category, radius_miles, nearest_n."
    )
    args_schema = RefreshDashboardArgs

    def __init__(self, runner: RecipeRunner, pctx: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._runner = runner
        self._pctx = pctx

    async def _execute(
        self,
        month: str | None = None,
        flex_type: str | None = None,
        pay_code: str | None = None,
        cost_center: str | None = None,
        category: str | None = None,
        radius_miles: float | None = None,
        nearest_n: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        state = current_a2ui_surface_state()
        state_filters: dict[str, Any] = {}
        if state is not None:
            state_filters = dict(state.data_model.get("filters") or {})

        def _pick(arg: Any, key: str) -> Any:
            if arg is not None:
                return arg
            return state_filters.get(key)

        params: dict[str, Any] = {}
        for key, arg in (
            ("month", month),
            ("flex_type", flex_type),
            ("pay_code", pay_code),
            ("cost_center", cost_center),
            ("category", category),
            ("radius_miles", radius_miles),
            ("nearest_n", nearest_n),
        ):
            value = _pick(arg, key)
            if value is not None:
                params[key] = value

        # Per-call pctx (set by AbstractTool.execute() from the
        # `_permission_context` kwarg) wins over the constructor-captured
        # one — see the class docstring.
        effective_pctx = getattr(self, "_current_pctx", None) or self._pctx
        artifact = await self._runner.run(FlexDashboard.DASHBOARD_RECIPE_NAME, params=params, pctx=effective_pctx)
        return {
            "filters": params,
            "filter_source": (
                "args"
                if any(
                    v is not None for v in (month, flex_type, pay_code, cost_center, category, radius_miles, nearest_n)
                )
                else ("surface_state" if state_filters else "defaults")
            ),
            "artifact_id": artifact.artifact_id,
            "bytes": len(artifact.content or b""),
        }
