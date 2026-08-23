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
from typing import Any, ClassVar, List, Optional, Union

from aiohttp import web
from parrot.bots.data import PandasAgent
from parrot.bots.mixins import InfographicAuthoringMixin, NarrativeMixin
from parrot.outputs.a2ui.recipes.models import LayoutSpec, NarrativeSpec
from parrot.registry import register_agent
from parrot.tools.infographic_sections import SectionDescriptor, SectionSpec

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


@register_agent(name="finance_reporter")
class FinanceReporter(NarrativeMixin, InfographicAuthoringMixin, PandasAgent):
    """Budget-variance reporting agent over ``troc.finance_projection``."""

    agent_id: str = "finance_reporter"
    llm = "google:gemini-3.5-flash"
    narrative_skill = "budget-narrative"

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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Configure the agent's LLM default.

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
            llm=kwargs.pop("llm", None) or self.llm,
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
            layout=LayoutSpec(
                component="Report",
                properties={
                    "title": "Daily Budget Variance — Executive Summary",
                    "summary": {"$bind": "/narrative", "optional": True},
                    "sections": [
                        {
                            "heading": "Executive Summary",
                            "text": {"$bind": "/narrative", "optional": True},
                        },
                    ],
                },
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
            layout=LayoutSpec(
                component="Infographic",
                properties={
                    "title": "Daily Budget Variance Dashboard",
                    "sections": [
                        {
                            "heading": "Snapshot",
                            "components": [
                                {
                                    "component": "KPICard",
                                    "properties": {
                                        "label": "Revenue (Actual)",
                                        "value": {
                                            "$bind": "/variance_analysis/last_totals/rev_actual"
                                        },
                                    },
                                },
                                {
                                    "component": "KPICard",
                                    "properties": {
                                        "label": "Revenue Variance",
                                        "value": {
                                            "$bind": "/variance_analysis/last_totals/rev_variance"
                                        },
                                    },
                                },
                                {
                                    "component": "KPICard",
                                    "properties": {
                                        "label": "EBITDA Variance",
                                        "value": {
                                            "$bind": "/variance_analysis/last_totals/ebitda_variance"
                                        },
                                    },
                                },
                            ],
                        },
                        {
                            "heading": "Top Movers",
                            "text": {"$bind": "/narrative", "optional": True},
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
                                        "data": {"$bind": "/top_movers/worst"},
                                    },
                                },
                            ],
                        },
                    ],
                },
            ),
            narrative=cls._narrative_spec(),
        )
