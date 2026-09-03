"""FinanceReporter — FEAT-420: tier-2 A2UI budget-variance reporting agent.

Composes :class:`NarrativeMixin` and :class:`InfographicAuthoringMixin` onto
:class:`PandasAgent` and gives the agent's ``DatasetManager`` access to the
Postgres table ``troc.finance_projection`` (daily budget-variance snapshots:
revenue and EBITDA, actual vs budget, per division/project).

Publishes two A2UI recipes built entirely on the registered finance
transformers (``parrot.outputs.a2ui.recipes.library``) — no hand-rolled
aggregation (spec criterion G-B):

- :meth:`report_descriptor` — a ``Report`` profile (narrative-first executive
  summary).
- :meth:`dashboard_descriptor` — an ``Infographic`` profile (visual-first
  dashboard).

Both declare an optional narrative step (skill ``budget-narrative``) so the
published recipe replays deterministically with no narrator configured
(spec criterion G-E), and both are published via
``InfographicAuthoringMixin.publish_recipe`` (tier 2) — this agent no longer
supports the tier-1 ``generate_infographic`` data-splice path (FEAT-326's
reference dashboard template + e2e example were replaced; see FEAT-420
Module 8 and the Completion Note for the full rationale)::

    agent = FinanceReporter(name="finance-reporter", recipe_store=store)
    await agent.register_datasets()
    recipe = await agent.publish_recipe(
        FinanceReporter.REPORT_RECIPE_NAME, FinanceReporter.report_descriptor()
    )

See ``examples/budget_variance_infographic.py`` for the end-to-end runner and
``examples/seed_finance_projection.py`` for the table seeder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, List, Literal, Optional, Union

from aiohttp import web
from parrot.bots.data import PandasAgent
from parrot.bots.mixins import InfographicAuthoringMixin, NarrativeMixin
from parrot.outputs.a2ui.recipes.models import (
    InfographicRecipe,
    LayoutSpec,
    NarrativeSpec,
)
from parrot.registry import register_agent
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from parrot.tools.infographic_recipes.runner import RecipeRunner
from parrot.tools.infographic_sections import (
    GapReport,
    SectionDescriptor,
    SectionSpec,
)
from pydantic import Field

# Retained for documentation only — the A2UI profiles below no longer use a
# data-splice/jinja template; kept as the reference dashboard's fixed
# location in case a tier-1 caller ever wants it (see Completion Note).
DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "sdd" / "artifacts"

# FEAT-420 code-review fix: anchored to this file's location (not process
# cwd, matching `DEFAULT_TEMPLATE_DIR` above) — `SkillRegistryMixin
# .skill_paths` defaults to `[]` (directory discovery is opt-in), and
# `NarrativeMixin` deliberately never sets it itself (criterion G-I: no
# domain-specific wiring baked into the reusable mixin). Without the
# composing agent declaring `skill_paths`, `SkillsDirectoryLoader` never
# scans `.agent/skills/`, `.agent/skills/budget-narrative/` is never
# registered, and `narrate("budget-narrative")` always returns `None` —
# even with a real narrator/LLM configured. Same pattern as
# `agents/security_advisor.py`'s `_SKILLS_DIR`/`skill_paths`.
SKILLS_DIR = Path(__file__).resolve().parents[1] / ".agent" / "skills"

# FEAT-420: renamed from "finance_projection" to "snapshots" — the registered
# DatasetManager alias, NOT the SQL table (`table="troc.finance_projection"`,
# below, is unchanged). `publish_recipe` forces `TransformStep.inputs` to
# equal the SectionDescriptor's declared dataset alias 1:1 (no separate
# dataset/alias distinction the way hand-authored YAML recipes allow), and
# every finance transformer in `library.py` hard-codes its frame input key
# as `"snapshots"` (e.g. `df = inputs["snapshots"]`) — so the alias MUST be
# literally "snapshots" for a published recipe to replay. See the Completion
# Note for the full analysis.
FINANCE_DATASET = "snapshots"
FINANCE_COLUMNS = [
    "snapshot_date",
    "division",
    "project",
    "rev_actual",
    "rev_budget",
    "ebitda_actual",
    "ebitda_budget",
]


def _build_default_artifact_store() -> Any:
    """Build an offline-safe default ``ArtifactStore`` (no network/DB).

    Mirrors ``agents/flex_dashboard.py``'s helper of the same name
    (FEAT-491). Without a default, an instance created through the real
    discovery path — ``AgentRegistry._load_modules_from_directory`` or an
    ``agents.yaml`` entry, neither of which passes ``artifact_store=`` —
    leaves ``InfographicAuthoringMixin._infographic_toolkit`` as ``None``,
    and every tier-2 call (``publish_recipe``, ``publish_report_recipe``,
    ``build_refresh_tool``) raises ``RuntimeError: no InfographicToolkit is
    wired``. Only the hand-wired example/test path worked before this.

    Construction is cheap (no I/O): ``ConversationSQLiteBackend.__init__``
    only stores the path; the schema is created lazily by its async
    ``initialize()``.

    Returns:
        A ready-to-use :class:`~parrot.storage.artifacts.ArtifactStore`.
    """
    from parrot.storage.artifacts import ArtifactStore
    from parrot.storage.backends import build_overflow_store
    from parrot.storage.backends.sqlite import ConversationSQLiteBackend

    backend = ConversationSQLiteBackend(path=":memory:")
    return ArtifactStore(backend, build_overflow_store())


@register_agent(name="finance_reporter")
class FinanceReporter(NarrativeMixin, InfographicAuthoringMixin, PandasAgent):
    """Budget-variance reporting agent over ``troc.finance_projection``."""

    agent_id: str = "finance_reporter"
    llm = "google:gemini-3.5-flash"
    narrative_skill = "budget-narrative"

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

    #: Directory-discovery opt-in (FEAT-420 code-review fix) — see
    #: `SKILLS_DIR`'s comment above for why this is required for
    #: `narrate("budget-narrative")` to ever find the skill in production.
    skill_paths: List[Path] = [SKILLS_DIR]

    TEMPLATE_NAME = "budget_variance_dashboard_Template.html"

    #: Distinct recipe names — publishing both must not collide (a
    #: ``(name, owner)`` collision would otherwise require ``overwrite=True``).
    REPORT_RECIPE_NAME = "budget-variance-report"
    DASHBOARD_RECIPE_NAME = "budget-variance-dashboard"

    #: Shared across every generated `TransformStep` (`descriptor.params` is
    #: descriptor-level, not per-section). The finance transformers default to
    #: `snapshot_col="snapshot"`; the table exposes `snapshot_date` — passed
    #: explicitly to every step so a missing snapshot column never silently
    #: degrades to a whole-frame read (`day_totals`) or a hard failure
    #: (`variance_analysis` raises without it).
    _SNAPSHOT_PARAMS: ClassVar[dict] = {"snapshot_col": "snapshot_date"}

    #: Explicit replay SQL for the `snapshots` dataset, threaded by
    #: `publish_recipe` into `DataSourceSpec.sql`. `troc.finance_projection`
    #: is registered as a `TableSource`, which REJECTS any fetch without an
    #: explicit statement (and any bare `SELECT *`) — without this the
    #: published recipe saves fine but every replay aborts at the `data`
    #: stage. Columns are exactly what the three finance transformers declare
    #: in `requires_columns` (division, project + the four money columns)
    #: plus the `snapshot_col` they compare across days; the table's primary
    #: key IS (snapshot_date, division, project), so this is already the
    #: natural grain — no pandas-side aggregation of a wider read.
    _DATASET_SQL: ClassVar[dict] = {
        FINANCE_DATASET: (
            "SELECT snapshot_date, division, project, "
            "rev_actual, rev_budget, ebitda_actual, ebitda_budget "
            "FROM troc.finance_projection "
            "ORDER BY snapshot_date, division, project"
        ),
    }

    def __init__(
        self,
        *args: Any,
        artifact_store: Optional[Any] = None,
        recipe_store: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Configure the agent's LLM default and its authoring stores.

        Args:
            artifact_store: Optional pre-built ``ArtifactStore`` forwarded to
                ``InfographicAuthoringMixin`` (which builds the
                ``InfographicToolkit`` from it). Defaults to an offline-safe
                local store — see :func:`_build_default_artifact_store` for
                why the default is required rather than merely convenient.
            recipe_store: Optional recipe store forwarded to
                ``InfographicAuthoringMixin`` (enables tier-2
                ``publish_recipe`` and the toolkit's recipe tools).
            **kwargs: Forwarded to the cooperative ``__init__`` chain.

        FEAT-420: no longer defaults ``template_dirs`` to
        ``DEFAULT_TEMPLATE_DIR`` — ``InfographicToolkit``'s ``TemplateEngine``
        validates every entry in ``template_dirs`` EAGERLY at construction
        time (raises if the directory is absent), and the tier-2 A2UI
        profiles below no longer render via a data-splice/jinja template at
        all. ``sdd/artifacts/`` is also a gitignored, non-portable local
        directory (verified: zero git history), so defaulting to it would
        make agent instantiation fail on any checkout that lacks it — as
        discovered by TASK-2195 actually running this agent. Callers that
        DO want the legacy tier-1 template path may still pass
        ``template_dirs=`` explicitly.
        """
        super().__init__(
            *args,
            artifact_store=artifact_store or _build_default_artifact_store(),
            recipe_store=recipe_store,
            llm=kwargs.pop("llm", None) or self.llm,
            python_repl_execution_mode=(
                kwargs.pop("python_repl_execution_mode", None) or self.python_repl_execution_mode
            ),
            **kwargs,
        )

    async def register_datasets(self) -> None:
        """Register the Postgres finance-projection table on the DatasetManager.

        Schema is prefetched (no rows loaded); rows materialize lazily when an
        infographic build or an analysis question needs them.
        """
        await self._dataset_manager.add_table_source(
            name=FINANCE_DATASET,
            table="troc.finance_projection",
            driver="pg",
            description=(
                "Daily budget-variance snapshots per division and project. "
                "One row per (snapshot_date, division, project) with revenue "
                "and EBITDA, actual vs budget: rev_actual, rev_budget, "
                "ebitda_actual, ebitda_budget. "
                "In SQL use: troc.finance_projection"
            ),
            usage_guidance={
                "do": [
                    "Revenue/EBITDA variance vs budget by division or project",
                    "Month-to-date trend analysis across snapshot_date",
                    "Feed the budget-variance report/dashboard recipes",
                ],
            },
        )

    async def configure(
        self,
        app: Optional[web.Application] = None,
        queries: Optional[Union[List[str], dict]] = None,
    ) -> None:
        """Register datasets before base configuration."""
        await self.register_datasets()
        await super().configure(app=app, queries=queries)

    @classmethod
    def _transform_sections(cls) -> List[SectionSpec]:
        """Sections whose NAMES are registered transformer names.

        Order matters: ``publish_recipe`` preserves ``descriptor.sections``
        order into ``TransformStep`` order, and ``narrative_facts`` consumes
        the other three steps' outputs — it must come last.
        """
        return [
            SectionSpec(
                name="variance_analysis",
                target="/variance_analysis",
                datasets=[FINANCE_DATASET],
                shape="mapping",
            ),
            SectionSpec(
                name="top_movers",
                target="/top_movers",
                datasets=[FINANCE_DATASET],
                shape="mapping",
            ),
            SectionSpec(
                name="division_breakdown",
                target="/division_breakdown",
                datasets=[FINANCE_DATASET],
                shape="mapping",
            ),
            SectionSpec(
                name="narrative_facts",
                target="/narrative_facts",
                # Prior-step output_keys, NOT dataset aliases — the generic
                # shape resolved in FEAT-420 Module 1 (spec §2 Overview).
                datasets=["variance_analysis", "top_movers", "division_breakdown"],
                shape="mapping",
            ),
        ]

    @classmethod
    def _narrative_spec(cls) -> NarrativeSpec:
        """Declarative narrative step shared by both profiles."""
        return NarrativeSpec(skill=cls.narrative_skill, facts_key="narrative_facts")

    @classmethod
    def report_descriptor(cls) -> SectionDescriptor:
        """``Report`` profile — narrative-first executive summary."""
        return SectionDescriptor(
            template=cls.TEMPLATE_NAME,
            mode="data-splice",
            sections=cls._transform_sections(),
            params=dict(cls._SNAPSHOT_PARAMS),
            dataset_sql=dict(cls._DATASET_SQL),
            # v2 LayoutSpec (FEAT-470 TASK-2542): props top-level, `{"path"}`
            # bindings; a binding's `optional` marker moves to the layout's
            # own `metadata.extensions.parrot_optional` (a flat list of
            # pointers) rather than an inline sibling key.
            layout=LayoutSpec(
                component="Report",
                title="Daily Budget Variance — Executive Summary",
                summary={"path": "/narrative"},
                sections=[
                    {
                        "heading": "Executive Summary",
                        "text": {"path": "/narrative"},
                    },
                ],
                metadata={"extensions": {"parrot_optional": ["/narrative"]}},
            ),
            narrative=cls._narrative_spec(),
        )

    @classmethod
    def dashboard_descriptor(cls) -> SectionDescriptor:
        """``Infographic`` profile — visual-first dashboard."""
        return SectionDescriptor(
            template=cls.TEMPLATE_NAME,
            mode="data-splice",
            sections=cls._transform_sections(),
            params=dict(cls._SNAPSHOT_PARAMS),
            dataset_sql=dict(cls._DATASET_SQL),
            # v2 LayoutSpec (FEAT-470 TASK-2542): props top-level, `{"path"}`
            # bindings; nested Infographic section-component descriptors
            # keep their OWN "properties" wrapper unchanged (that is the
            # composite's own authored-descriptor shape, not the wire
            # Component shape LayoutSpec mirrors); a binding's `optional`
            # marker moves to the layout's own
            # `metadata.extensions.parrot_optional`.
            layout=LayoutSpec(
                component="Infographic",
                title="Daily Budget Variance Dashboard",
                sections=[
                    {
                        "heading": "Snapshot",
                        "components": [
                            {
                                "component": "KPICard",
                                "properties": {
                                    "label": "Revenue (Actual)",
                                    "value": {"path": "/variance_analysis/last_totals/rev_actual"},
                                },
                            },
                            {
                                "component": "KPICard",
                                "properties": {
                                    "label": "Revenue Variance",
                                    "value": {"path": "/variance_analysis/last_totals/rev_variance"},
                                },
                            },
                            {
                                "component": "KPICard",
                                "properties": {
                                    "label": "EBITDA Variance",
                                    "value": {"path": "/variance_analysis/last_totals/ebitda_variance"},
                                },
                            },
                        ],
                    },
                    {
                        "heading": "Top Movers",
                        "text": {"path": "/narrative"},
                        "components": [
                            {
                                "component": "DataTable",
                                "properties": {
                                    "columns": [
                                        {"name": "division"},
                                        {"name": "project"},
                                        {"name": "ebitda_variance"},
                                        {"name": "trend"},
                                    ],
                                    "data": {"path": "/top_movers/worst"},
                                },
                            },
                        ],
                    },
                ],
                metadata={"extensions": {"parrot_optional": ["/narrative"]}},
            ),
            narrative=cls._narrative_spec(),
        )

    # ── Recipe publication (tier 2) ─────────────────────────────────────

    @classmethod
    def _profile(cls, profile: str) -> tuple[str, SectionDescriptor, str, str]:
        """Resolve a profile name to its (recipe_name, descriptor, kind, title).

        Args:
            profile: ``"report"`` or ``"dashboard"``.

        Returns:
            A 4-tuple of recipe name, section descriptor, ``UISurfaceKind``
            value, and human-readable surface title.

        Raises:
            ValueError: On an unknown profile name.
        """
        if profile == "report":
            return (
                cls.REPORT_RECIPE_NAME,
                cls.report_descriptor(),
                "infographic",
                "Daily Budget Variance — Executive Summary",
            )
        if profile == "dashboard":
            return (
                cls.DASHBOARD_RECIPE_NAME,
                cls.dashboard_descriptor(),
                "dashboard",
                "Daily Budget Variance Dashboard",
            )
        raise ValueError(f"Unknown profile {profile!r}; expected 'report' or 'dashboard'.")

    async def publish_report_recipe(self, overwrite: bool = False) -> Union[InfographicRecipe, GapReport]:
        """Publish the ``Report`` profile under :attr:`REPORT_RECIPE_NAME`."""
        return await self.publish_recipe(self.REPORT_RECIPE_NAME, self.report_descriptor(), overwrite=overwrite)

    async def publish_dashboard_recipe(self, overwrite: bool = False) -> Union[InfographicRecipe, GapReport]:
        """Publish the ``Infographic`` profile under :attr:`DASHBOARD_RECIPE_NAME`."""
        return await self.publish_recipe(self.DASHBOARD_RECIPE_NAME, self.dashboard_descriptor(), overwrite=overwrite)

    # ── Surface publication (FEAT-492 rehydration plane) ────────────────

    async def publish_profile_surface(
        self,
        profile: Literal["report", "dashboard"] = "dashboard",
        *,
        pctx: Any,
        params: Optional[dict] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        surface_store: Optional[Any] = None,
        overwrite: bool = False,
    ) -> str:
        """Replay a published recipe and persist the result as a UI surface.

        Closes the gap between this agent's tier-2 recipes and the FEAT-492
        rehydration plane: without this, nothing ever writes a
        ``navigator.ui_surfaces`` row for a finance profile, so no finance
        dashboard is bookmarkable via ``GET /api/v1/ui/surfaces/{id}``, the
        ``A2UIHandler`` mirror ``GET /api/v1/agents/{agent_id}/a2ui/surfaces/
        {id}``, or refreshable via ``POST .../refresh``.

        Uses the bridge FEAT-492 G8 added for exactly this path —
        ``RecipeRunner.run(include_envelope=True)`` exposes the assembled
        ``CreateSurface`` at ``RenderedArtifact.metadata["source_envelope"]``,
        so no second ArtifactStore round-trip is needed. ``recipe_name`` is
        always threaded through, which is what makes the persisted row
        ``refreshable`` (``UISurfaceRecord.refreshable``).

        .. warning::

           Blocked on a core A2UI bug until the ``parrot_optional`` lowering
           fix lands: ``build_infographic``/``build_surface`` never propagate
           ``LayoutSpec.metadata.extensions.parrot_optional`` onto the wire
           ``Component``, so ``baking._optional_paths`` returns an empty set
           and BOTH profiles raise ``BakeError: Unresolvable data-model path
           '/narrative'`` at render time whenever the narrative is absent
           (no narrator configured, or the figure guard discarded it). This
           method is correct as written and starts working the moment that
           fix lands; see ``sdd/specs/a2ui-optional-binding-lowering.spec.md``.

        Args:
            profile: Which published recipe to replay.
            pctx: The invoker's ``PermissionContext``. Never pass ``None`` —
                ``RecipeRunner.run`` fails OPEN on a falsy ``pctx`` (its own
                docstring warning), disabling DatasetManager's PBAC guards.
            params: Optional param overrides recorded on the row as the
                refresh lane's "stored" precedence tier.
            user_id: Attributed owner of the row; falls back to the agent.
            session_id: Optional originating session, attached verbatim.
            surface_store: Injection seam forwarded to ``publish_surface``.
            overwrite: Forwarded to ``publish_surface``.

        Returns:
            The persisted ``surface_id``.

        Raises:
            RecipeRunException: On any replay abort (stage-tagged).
            RuntimeError: When no recipe store is wired.
        """
        recipe_name, _descriptor, kind, title = self._profile(profile)
        runner = RecipeRunner(self._require_recipe_store(), self._dataset_manager)
        artifact = await runner.run(
            recipe_name,
            params=params,
            pctx=pctx,
            include_envelope=True,
        )
        envelope = artifact.metadata.get("source_envelope")
        if envelope is None:
            raise RuntimeError(
                f"Replay of recipe {recipe_name!r} produced no 'source_envelope' — "
                "RecipeRunner.run(include_envelope=True) contract broken."
            )
        return await self.publish_surface(
            kind=kind,
            title=title,
            envelope=envelope,
            recipe_name=recipe_name,
            recipe_params=params or {},
            overwrite=overwrite,
            surface_store=surface_store,
            user_id=user_id,
            session_id=session_id,
        )

    # ── Refresh lane (FEAT-469/492 pattern) ─────────────────────────────

    def build_refresh_tool(self, pctx: Any) -> RefreshFinanceSurfaceTool:
        """Build and register the ``refresh_dashboard`` agent function.

        Gives the renderer's ``callAgentFunction -> refresh_dashboard`` lane
        (FEAT-492 G3) something to call on this agent — the same wiring
        ``agents/flex_dashboard.py`` exposes. Requires a recipe store to
        already be wired; raises via ``_require_recipe_store()`` otherwise.

        Args:
            pctx: A real ``PermissionContext`` (e.g. from
                ``build_principal_context``). ``RecipeRunner.run`` fails OPEN
                on a falsy ``pctx`` — never pass ``None`` here.

        Returns:
            The registered :class:`RefreshFinanceSurfaceTool` instance.
        """
        runner = RecipeRunner(self._require_recipe_store(), self._dataset_manager)
        tool = RefreshFinanceSurfaceTool(runner=runner, pctx=pctx)
        self.tool_manager.add_tool(tool)
        return tool


class RefreshFinanceSurfaceArgs(AbstractToolArgsSchema):
    """Arguments the renderer may pass on ``callAgentFunction``."""

    profile: Literal["report", "dashboard"] = Field(
        default="dashboard",
        description="Which published budget-variance profile to re-render.",
    )


class RefreshFinanceSurfaceTool(AbstractTool):
    """Deterministically re-render a budget-variance profile from its recipe.

    Takes no filter arguments by design: unlike the Flex dashboard, neither
    finance recipe declares any ``RecipeParam`` (``descriptor.params`` feeds
    ``TransformStep.params``, not the recipe's declared parameters), so there
    is nothing to filter on. A bare re-run is still meaningful — every
    ``DataSourceSpec`` defaults to ``force_refresh=True``, so the replay
    pulls fresh rows from ``troc.finance_projection``.

    Permission-context precedence mirrors ``flex_dashboard``'s tool (adopted
    from its code review): the PER-CALL ``PermissionContext`` injected by
    ``AbstractTool.execute()`` onto ``self._current_pctx`` always wins over
    the ``pctx`` captured at construction, so on a shared/pooled agent one
    user's data-plane scope cannot leak into another user's refresh. The
    constructor ``pctx`` is the fallback for direct calls that never go
    through ``ToolManager.execute_tool``.

    Note: this re-renders and returns artifact metadata. Updating a persisted
    surface row IN PLACE is the REST lane's job —
    ``POST /api/v1/ui/surfaces/{surface_id}/refresh`` already replays the
    stored ``recipe_ref`` under the owner's context and calls
    ``store.update_envelope``.
    """

    name = "refresh_dashboard"
    description = (
        "Re-render a budget-variance profile deterministically via its "
        "published recipe, pulling fresh snapshots. profile: 'report' "
        "(narrative-first executive summary) or 'dashboard' (visual KPIs)."
    )
    args_schema = RefreshFinanceSurfaceArgs

    def __init__(self, runner: RecipeRunner, pctx: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._runner = runner
        self._pctx = pctx

    async def _execute(self, profile: str = "dashboard", **kwargs: Any) -> dict[str, Any]:
        recipe_name, _descriptor, _kind, _title = FinanceReporter._profile(profile)
        # Per-call pctx (set by AbstractTool.execute() from the
        # `_permission_context` kwarg) wins over the constructor-captured one.
        effective_pctx = getattr(self, "_current_pctx", None) or self._pctx
        artifact = await self._runner.run(recipe_name, pctx=effective_pctx)
        return {
            "profile": profile,
            "recipe": recipe_name,
            "artifact_id": artifact.artifact_id,
            "bytes": len(artifact.content or b""),
        }
