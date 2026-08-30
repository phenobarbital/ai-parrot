"""Deterministic refresh + inline filtering over A2UI (FEAT-324/326 × FEAT-469).

Lineage: the standalone "Flex Program" report (``documents/flex_program_report.html``)
established the pattern this example generalizes — an agent *authors* a dashboard
once (python/pandas doing the heavy lifting), then a **deterministic recipe**
replays it forever: numbers always come from registered
``@infographic_transformer`` functions over declared datasets, never from
re-running LLM-generated code (FEAT-324 G1). What that lane never had was an
*interactive* leg: the rendered surface could not ask the agent to refresh
itself, and there was no channel for in-dashboard filter state.

FEAT-469 (A2UI Agent Functions runtime) supplies exactly that leg. This example
fuses the two lanes end to end, on seeded synthetic data — no database, no
network, no LLM:

1. **Transformers with declared filter params** — ``{window}`` / ``{plan}``
   placeholders resolve per run, so a *filtered* replay is still deterministic.
2. **Publish** — ``InfographicAuthoringMixin.publish_recipe()`` maps sections
   to registered transformers and persists an ``InfographicRecipe`` whose
   ``LayoutSpec`` (v2, ``{"path": ...}`` bindings) is used verbatim.
3. **Deterministic replay** — ``RecipeRunner.run()`` twice with the same params
   produces byte-identical HTML; params overrides give filtered variants.
4. **The RPC leg** — an ``A2UIRuntime`` over the agent's own ``ToolManager``:
   * ``action`` + ``dataModel`` — the surface pushes its inline filter state,
     persisted per ``surfaceId``.
   * ``callAgentFunction`` → ``refresh_dashboard`` — the renderer asks the
     agent to re-run the recipe (args win over surface state).
   * ``current_a2ui_surface_state()`` — the same tool refreshed *from* the
     persisted surface state when the renderer passes no explicit args.
   * ``callRendererFunction`` / ``rendererFunctionResponse`` — the agent calls
     the renderer back and correlates the response.
5. **Capabilities** — ``export_functions()`` / ``agent_capabilities()`` show
   what a renderer discovers, including the ``a2ui_hidden`` opt-out.

Prerequisites::

    pip install ai-parrot ai-parrot-visualizations[a2ui]

Usage::

    source .venv/bin/activate
    python examples/agents/a2ui/deterministic_refresh_dashboard.py
    python examples/agents/a2ui/deterministic_refresh_dashboard.py --serve

.. note::

   The ``interactive-html`` renderer output needs an HTTP origin — opening the
   files as ``file://`` breaks Chart.js canvas rendering. Use ``--serve``.
"""
from __future__ import annotations

import argparse
import asyncio
import http.server
import json
import os
import re
import socketserver
import sys
import threading
import webbrowser
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import Field

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "artifacts" / "a2ui_deterministic_refresh"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from parrot.auth.permission import build_principal_context
from parrot.bots.data import PandasAgent
from parrot.bots.mixins import InfographicAuthoringMixin
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.catalog.export import (
    agent_capabilities,
    export_functions,
)
from parrot.outputs.a2ui.recipes.models import LayoutSpec, RecipeParam
from parrot.outputs.a2ui.recipes.store import FileRecipeStore
from parrot.outputs.a2ui.recipes.transformers import (
    infographic_transformer,
)
from parrot.outputs.a2ui.runtime import (
    A2UICallContext,
    A2UIRuntime,
    FunctionCallRecord,
    SurfaceState,
)
from parrot.outputs.a2ui.runtime.adapters import ToolManagerExecutor
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.backends import build_overflow_store
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.tools.abstract import (
    AbstractTool,
    AbstractToolArgsSchema,
    current_a2ui_surface_state,
)
from parrot.tools.infographic_recipes.runner import (
    RecipeRunException,
    RecipeRunner,
)
from parrot.tools.infographic_sections import (
    GapReport,
    SectionDescriptor,
    SectionSpec,
)
from synthetic_data import build_monthly_metrics, build_plan_mix

from parrot.registry import register_agent

# The ``interactive-html`` renderer registers itself on import; it ships from
# ai-parrot-visualizations (namespace-merged). Without it, RecipeRunner's
# default render profile cannot resolve.
try:
    import parrot.outputs.a2ui_renderers.interactive_html  # noqa: F401

    _HAS_RENDERER = True
except ImportError:
    _HAS_RENDERER = False

RECIPE_NAME = "deterministic-revenue-dashboard"
#: RecipeRunner assembles the envelope with surface_id=f"{recipe.name}-infographic",
#: so the surface id is stable across runs — the renderer can key its state on it.
SURFACE_ID = f"{RECIPE_NAME}-infographic"
SESSION_ID = "sess-demo"

_PLANS = ("Starter", "Team", "Business", "Enterprise")


def rule(title: str) -> None:
    """Print a section rule with a title."""
    print("\n" + "═" * 72)
    print(f"  {title}")
    print("═" * 72)


# ═══════════════════════════════════════════════════════════════════════════
# Step 1 — Transformers: the deterministic data plane, filterable via params
# ═══════════════════════════════════════════════════════════════════════════
#
# Each transformer receives (inputs, params): the declared dataset frames and
# the recipe's RESOLVED params — ``{window}`` / ``{plan}`` placeholders already
# substituted (declared defaults + run-time overrides). Filtering happens HERE,
# in registered code, so a filtered replay is exactly as deterministic and
# auditable as the unfiltered one.

def _window_slice(df: pd.DataFrame, window: str) -> pd.DataFrame:
    """Slice the 12-month frame to a half-year window (``all``/``h1``/``h2``)."""
    if window == "h1":
        return df.iloc[:6]
    if window == "h2":
        return df.iloc[6:]
    return df


@infographic_transformer(
    name="revenue_overview",
    requires_columns={"monthly": ["month", "mrr", "new_mrr", "churned_mrr", "churn_rate", "nps"]},
    description="Windowed MRR/churn/NPS overview (params: window=all|h1|h2).",
)
def revenue_overview(
    inputs: dict[str, pd.DataFrame], params: dict[str, Any]
) -> dict[str, Any]:
    """KPIs + monthly series for the selected month window."""
    window = str(params.get("window", "all")).lower()
    df = _window_slice(inputs["monthly"], window)
    closing, opening = df.iloc[-1], df.iloc[0]
    return {
        "kpis": {
            "window_label": {"all": "Jan–Dec", "h1": "Jan–Jun", "h2": "Jul–Dec"}.get(window, window),
            "mrr_close": round(float(closing["mrr"]), 2),
            "mrr_growth_pct": round(
                (float(closing["mrr"]) / float(opening["mrr"]) - 1.0) * 100.0, 1
            ),
            "churn_close": float(closing["churn_rate"]),
            "nps_close": int(closing["nps"]),
        },
        "series": df[["month", "mrr", "new_mrr", "churned_mrr"]].to_dict(orient="records"),
    }


@infographic_transformer(
    name="plan_breakdown",
    requires_columns={"plan_mix": ["plan", "accounts", "mrr", "share_pct"]},
    description="Closing-month MRR by plan tier (params: plan=All|<tier>).",
)
def plan_breakdown(
    inputs: dict[str, pd.DataFrame], params: dict[str, Any]
) -> dict[str, Any]:
    """Plan-tier records, optionally narrowed to a single tier."""
    plan = str(params.get("plan", "All"))
    df = inputs["plan_mix"]
    if plan != "All":
        df = df[df["plan"] == plan]
    top = df.sort_values("mrr", ascending=False)
    return {
        "plan_label": plan,
        "records": df.to_dict(orient="records"),
        "top_plan": str(top.iloc[0]["plan"]) if len(top) else "N/A",
        "total_mrr": round(float(df["mrr"].sum()), 2),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Step 2 — Descriptor + v2 LayoutSpec (props top-level, {"path": ...} bindings)
# ═══════════════════════════════════════════════════════════════════════════

def _dashboard_descriptor() -> SectionDescriptor:
    """Declarative recipe descriptor with filter params and an A2UI layout.

    ``descriptor.params`` values are ``{param}`` templates — they land on every
    ``TransformStep.params`` and are substituted from the recipe's *declared*
    params (defaults + run-time overrides) on each replay.
    """
    return SectionDescriptor(
        template="unused-with-layout",  # layout below is used verbatim
        mode="data-splice",
        params={"window": "{window}", "plan": "{plan}"},
        sections=[
            SectionSpec(
                name="revenue_overview",
                target="/revenue_overview",
                datasets=["monthly"],
                shape="mapping",
            ),
            SectionSpec(
                name="plan_breakdown",
                target="/plan_breakdown",
                datasets=["plan_mix"],
                shape="mapping",
            ),
        ],
        layout=LayoutSpec(
            component="Infographic",
            title="Revenue Ops — Deterministic Dashboard",
            subtitle="Recipe replay with inline window/plan filters",
            sections=[
                {
                    "heading": "Revenue overview",
                    "components": [
                        {
                            "component": "KPICard",
                            "properties": {
                                "label": "Window",
                                "value": {"path": "/revenue_overview/kpis/window_label"},
                            },
                        },
                        {
                            "component": "KPICard",
                            "properties": {
                                "label": "Closing MRR (USD)",
                                "value": {"path": "/revenue_overview/kpis/mrr_close"},
                            },
                        },
                        {
                            "component": "KPICard",
                            "properties": {
                                "label": "MRR growth %",
                                "value": {"path": "/revenue_overview/kpis/mrr_growth_pct"},
                            },
                        },
                        {
                            "component": "KPICard",
                            "properties": {
                                "label": "NPS (closing)",
                                "value": {"path": "/revenue_overview/kpis/nps_close"},
                            },
                        },
                        {
                            "component": "Chart",
                            "properties": {
                                "title": "MRR movement by month",
                                "type": "bar",
                                "x": "month",
                                "y": ["mrr", "new_mrr", "churned_mrr"],
                                "showLegend": True,
                                "data": {"path": "/revenue_overview/series"},
                            },
                        },
                    ],
                },
                {
                    "heading": "Plan mix (closing month)",
                    "components": [
                        {
                            "component": "KPICard",
                            "properties": {
                                "label": "Plan filter",
                                "value": {"path": "/plan_breakdown/plan_label"},
                            },
                        },
                        {
                            "component": "KPICard",
                            "properties": {
                                "label": "Top plan",
                                "value": {"path": "/plan_breakdown/top_plan"},
                            },
                        },
                        {
                            "component": "Chart",
                            "properties": {
                                "title": "MRR by plan tier",
                                "type": "bar",
                                "x": "plan",
                                "y": ["mrr"],
                                "showLegend": False,
                                "data": {"path": "/plan_breakdown/records"},
                            },
                        },
                        {
                            "component": "DataTable",
                            "properties": {
                                "columns": [
                                    {"name": "plan"},
                                    {"name": "accounts"},
                                    {"name": "mrr"},
                                    {"name": "share_pct"},
                                ],
                                "data": {"path": "/plan_breakdown/records"},
                            },
                        },
                    ],
                },
            ],
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Step 3 — The agent
# ═══════════════════════════════════════════════════════════════════════════

@register_agent(name="deterministic_reporter")
class DeterministicReporter(InfographicAuthoringMixin, PandasAgent):
    """Reporting agent: authoring mixin + pandas agent, all programmatic.

    The ``llm`` is declared (PandasAgent requires one) but never called —
    determinism is the point: everything below is recipe replay + RPC dispatch.
    """

    agent_id: str = "deterministic_reporter"
    llm = "google:gemini-3.5-flash"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, llm=kwargs.pop("llm", None) or self.llm, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════
# Step 4 — The refresh tool (FEAT-469: renderer-invocable, surface-state aware)
# ═══════════════════════════════════════════════════════════════════════════

class RefreshDashboardArgs(AbstractToolArgsSchema):
    """Arguments the renderer may pass on ``callAgentFunction``."""

    window: str | None = Field(
        default=None, description="Month window filter: all | h1 | h2."
    )
    plan: str | None = Field(
        default=None,
        description=f"Plan tier filter: All | {' | '.join(_PLANS)}.",
    )


class RefreshDashboardTool(AbstractTool):
    """Deterministically re-render the revenue dashboard, optionally filtered.

    Filter precedence per call: explicit args (the renderer's inline filter
    widget) → the surface's last persisted ``dataModel.filters`` (read via
    ``current_a2ui_surface_state()``) → the recipe's declared defaults.
    """

    name = "refresh_dashboard"
    description = (
        "Re-render the revenue dashboard deterministically via its published "
        "recipe. Optional filters: window (all|h1|h2) and plan tier."
    )
    args_schema = RefreshDashboardArgs

    def __init__(
        self,
        runner: RecipeRunner,
        pctx: Any,
        out_dir: Path,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._runner = runner
        self._pctx = pctx
        self._out_dir = out_dir

    async def _execute(
        self,
        window: str | None = None,
        plan: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        state = current_a2ui_surface_state()
        state_filters: dict[str, Any] = {}
        if state is not None:
            state_filters = dict(state.data_model.get("filters") or {})

        params = {
            "window": window or state_filters.get("window") or "all",
            "plan": plan or state_filters.get("plan") or "All",
        }
        artifact = await self._runner.run(RECIPE_NAME, params=params, pctx=self._pctx)

        out = self._out_dir / f"refresh_{params['window']}_{params['plan'].lower()}.html"
        out.write_bytes(artifact.content or b"")
        return {
            "filters": params,
            "filter_source": (
                "args" if (window or plan) else ("surface_state" if state_filters else "defaults")
            ),
            "surface_id": SURFACE_ID,
            "artifact_id": artifact.artifact_id,
            "bytes": len(artifact.content or b""),
            "saved_to": str(out.relative_to(REPO_ROOT)),
        }


class ResetDatasetsTool(AbstractTool):
    """Deliberately hidden from the A2UI catalog (``a2ui_hidden = True``).

    Demonstrates the opt-OUT model: every non-hidden ToolManager tool is
    renderer-invocable, so a destructive/maintenance tool must exclude itself.
    """

    name = "reset_datasets"
    description = "Maintenance: drop and reload every registered dataset."
    a2ui_hidden = True

    async def _execute(self, **kwargs: Any) -> dict[str, Any]:
        return {"reset": False, "detail": "demo stub — never called"}


# ═══════════════════════════════════════════════════════════════════════════
# Step 5 — In-memory runtime adapters (Protocol-shaped, no Redis needed)
# ═══════════════════════════════════════════════════════════════════════════
#
# Production uses ConversationMemorySurfaceStore (both protocols over
# ConversationMemory metadata). The runtime takes the Protocols by injection,
# so a dict-backed pair is all a self-contained example needs.

class InMemorySurfaceStore:
    """Dict-backed ``SurfaceStateStore``: the last ``dataModel`` per surface."""

    def __init__(self) -> None:
        self._store: dict[tuple, SurfaceState] = {}

    async def get(self, session_id: str, surface_id: str) -> SurfaceState | None:
        return self._store.get((session_id, surface_id))

    async def put(self, session_id: str, state: SurfaceState) -> None:
        self._store[(session_id, state.surface_id)] = state

    async def delete(self, session_id: str, surface_id: str) -> None:
        self._store.pop((session_id, surface_id), None)


class InMemoryPendingCalls:
    """Dict-backed ``PendingCallRegistry`` with the standard TTL semantics."""

    def __init__(self) -> None:
        self._store: dict[tuple, FunctionCallRecord] = {}

    async def add(self, session_id: str, record: FunctionCallRecord) -> None:
        self._store[(session_id, record.function_call_id)] = record

    async def resolve(
        self, session_id: str, function_call_id: str, value: Any, error: Any
    ) -> FunctionCallRecord | None:
        key = (session_id, function_call_id)
        record = self._store.get(key)
        if record is None:
            return None
        if datetime.now(UTC) > record.created_at + timedelta(seconds=record.ttl_seconds):
            del self._store[key]
            return None
        del self._store[key]
        return record


# ═══════════════════════════════════════════════════════════════════════════
# Step 6 — Demo lanes
# ═══════════════════════════════════════════════════════════════════════════

async def lane_publish(agent: DeterministicReporter, recipe_store: FileRecipeStore) -> bool:
    """Publish the recipe and declare its run-time filter params."""
    rule("1 — publish_recipe: sections → registered transformers → recipe")

    recipe = await agent.publish_recipe(RECIPE_NAME, _dashboard_descriptor(), overwrite=True)
    if isinstance(recipe, GapReport):
        print("  ✗ GAPS — unregistered transformers:")
        for gap in recipe.gaps:
            print(f"    - {gap.section}")
        return False

    # publish_recipe carries descriptor.params onto every TransformStep, but
    # the DECLARED run-time params (name/default, override whitelist) are the
    # recipe author's call — declare them and re-save. An override for an
    # undeclared name raises (typo protection), so this list is also the
    # public filter contract of the dashboard.
    recipe.params = [
        RecipeParam(name="window", default="all", description="Month window: all|h1|h2"),
        RecipeParam(name="plan", default="All", description="Plan tier filter"),
    ]
    await recipe_store.save(recipe)

    print(f"  recipe        : {recipe.name}")
    print(f"  transforms    : {[t.transformer for t in recipe.transforms]}")
    print(f"  data_sources  : {[ds.alias for ds in recipe.data_sources]}")
    print(f"  declared params: "
          f"{ {p.name: p.default for p in recipe.params} }")
    print(f"  surface_id    : {SURFACE_ID}  (stable across replays)")
    return True


#: The interactive-html renderer mints per-render DOM element ids
#: (``chart-<hex8>``, ``tabs-<hex8>``, ``nested-<hex8>`` via ``uuid4``) — the
#: one thing in the output that is NOT replay-stable. The FEAT-324 determinism
#: guarantee lives at the data plane (params → transforms → dataModel →
#: envelope, all replay-stable, surfaceId included); these ids are internal
#: renderer wiring with no data content. Normalize them before comparing.
_VOLATILE_DOM_ID = re.compile(rb"(chart|tabs|nested)-[0-9a-f]{8}")


def _normalize_render(content: bytes) -> bytes:
    """Replace the renderer's per-render DOM ids with a stable token."""
    return _VOLATILE_DOM_ID.sub(rb"\1-x", content)


async def lane_deterministic_replay(runner: RecipeRunner, pctx: Any) -> None:
    """Prove the refresh is deterministic, then replay with filter overrides."""
    rule("2 — RecipeRunner.run: deterministic replay + filtered variants")

    first = await runner.run(RECIPE_NAME, pctx=pctx)
    second = await runner.run(RECIPE_NAME, pctx=pctx)
    identical = _normalize_render(first.content or b"") == _normalize_render(
        second.content or b""
    )
    print(f"  replay #1     : {len(first.content or b''):,} bytes")
    print(f"  replay #2     : {len(second.content or b''):,} bytes")
    print(f"  identical     : {identical}  (modulo the renderer's per-render DOM")
    print("                  element ids — every number, label, series and the")
    print("                  surfaceId itself is replay-stable)")
    if not identical:
        print("  ⚠ unexpected: same params should produce identical content")

    (OUTPUT_DIR / "01_dashboard_default.html").write_bytes(first.content or b"")

    filtered = await runner.run(
        RECIPE_NAME, params={"window": "h2", "plan": "Enterprise"}, pctx=pctx
    )
    (OUTPUT_DIR / "02_dashboard_h2_enterprise.html").write_bytes(filtered.content or b"")
    print(f"  filtered      : window=h2 plan=Enterprise → "
          f"{len(filtered.content or b''):,} bytes")

    try:
        await runner.run(RECIPE_NAME, params={"regoin": "oops"}, pctx=pctx)
    except RecipeRunException as exc:
        print(f"  typo guard    : undeclared override rejected — {exc.error.detail}")


async def lane_rpc(
    runtime: A2UIRuntime,
    ctx: A2UICallContext,
    surfaces: InMemorySurfaceStore,
    refresh_tool: RefreshDashboardTool,
) -> None:
    """Drive the four FEAT-469 flows the way a renderer would."""
    rule("3 — action + dataModel: the surface pushes its inline filter state")

    action_env = {
        "version": "v1.0",
        "action": {
            "name": "filters_changed",
            "surfaceId": SURFACE_ID,
            "sourceComponentId": "filter-bar",
            "timestamp": datetime.now(UTC).isoformat(),
            "context": {},
            "dataModel": {"filters": {"window": "h2", "plan": "Business"}},
        },
    }
    res = await runtime.dispatch(action_env, ctx)
    print(f"  responses     : {res.messages or '(none — actions ack silently)'}")
    print(f"  user_turn     : {res.user_turn}")
    stored = await surfaces.get(SESSION_ID, SURFACE_ID)
    print(f"  surface state : {stored.data_model if stored else None}")

    rule("4 — callAgentFunction: the renderer asks for a filtered refresh")

    call_env = {
        "version": "v1.0",
        "callAgentFunction": {
            "surfaceId": SURFACE_ID,
            "functionCallId": "fc-refresh-1",
            "callFunction": {
                "call": "refresh_dashboard",
                "args": {"plan": "Enterprise"},  # explicit arg wins over state
                "catalogId": DEFAULT_CATALOG_ID,
            },
        },
    }
    res = await runtime.dispatch(call_env, ctx)
    reply = res.messages[0]
    print(f"  envelope key  : {[k for k in reply if k != 'version']}")
    value = reply.get("agentFunctionResponse", {}).get("value")
    print(f"  tool result   : {json.dumps(value, indent=2) if value else reply}")

    rule("5 — surface-state refresh: no args, filters come from the dataModel")

    # This is what AbstractBot.ask(a2ui_surface_state=...) does for every tool
    # in an A2UI-triggered turn; a direct execute() call takes the same state
    # through the reserved kwarg.
    state = await surfaces.get(SESSION_ID, SURFACE_ID)
    result = await refresh_tool.execute(_a2ui_surface_state=state)
    print(f"  tool result   : {json.dumps(result.result, indent=2)}")

    rule("6 — callRendererFunction: the agent calls the renderer back")

    fc_id, outbound = await runtime.call_renderer(
        SESSION_ID,
        SURFACE_ID,
        "updateDataModel",
        {"path": "/lastRefreshed", "value": datetime.now(UTC).isoformat()},
    )
    print(f"  outbound      : {json.dumps(outbound)}")

    response_env = {
        "version": "v1.0",
        "rendererFunctionResponse": {"functionCallId": fc_id, "value": {"applied": True}},
    }
    res = await runtime.dispatch(response_env, ctx)
    print(f"  correlated    : {'yes (no error envelope)' if not res.messages else res.messages}")


def lane_capabilities(executor: ToolManagerExecutor) -> None:
    """Show what a renderer discovers about this agent."""
    rule("7 — export_functions / agent_capabilities: the discovery documents")

    functions = export_functions(executor)
    capabilities = agent_capabilities([DEFAULT_CATALOG_ID])

    print(f"  functions     : {sorted(functions)}")
    print(f"  hidden        : 'reset_datasets' exported = "
          f"{'reset_datasets' in functions}  (a2ui_hidden=True)")
    print(f"  capabilities  : {json.dumps(capabilities)}")

    doc = OUTPUT_DIR / "03_capabilities.json"
    doc.write_text(json.dumps({"functions": functions, "capabilities": capabilities}, indent=2))
    print(f"  wrote         : {doc.relative_to(REPO_ROOT)}")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

async def main() -> None:
    """Wire storage + agent + runtime, then run every lane."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not _HAS_RENDERER:
        print("✗ ai-parrot-visualizations[a2ui] is not importable — the recipe's")
        print("  'interactive-html' render profile cannot resolve. Install it first.")
        return

    backend = ConversationSQLiteBackend(path=str(OUTPUT_DIR / "artifacts.db"))
    await backend.initialize()
    artifact_store = ArtifactStore(backend, build_overflow_store())
    recipe_store = FileRecipeStore(OUTPUT_DIR / "recipes")

    agent = DeterministicReporter(
        name="deterministic-reporter",
        artifact_store=artifact_store,
        recipe_store=recipe_store,
        injection_detection=False,
    )
    monthly = build_monthly_metrics()
    agent._dataset_manager.add_dataframe(
        "monthly", monthly, description="12-month SaaS revenue-ops series"
    )
    agent._dataset_manager.add_dataframe(
        "plan_mix", build_plan_mix(monthly), description="Closing-month MRR by plan tier"
    )

    if not await lane_publish(agent, recipe_store):
        return

    pctx = build_principal_context("demo-user", channel="script")
    runner = RecipeRunner(recipe_store, agent._dataset_manager)
    await lane_deterministic_replay(runner, pctx)

    # --- FEAT-469 runtime over the agent's own ToolManager ---
    refresh_tool = RefreshDashboardTool(runner=runner, pctx=pctx, out_dir=OUTPUT_DIR)
    agent.tool_manager.add_tool(refresh_tool)
    agent.tool_manager.add_tool(ResetDatasetsTool())

    executor = ToolManagerExecutor(agent.tool_manager)
    surfaces = InMemorySurfaceStore()
    runtime = A2UIRuntime(
        executor=executor, surfaces=surfaces, pending=InMemoryPendingCalls()
    )
    ctx = A2UICallContext(
        agent_id="deterministic_reporter",
        user_id="demo-user",
        session_id=SESSION_ID,
        surface_id=SURFACE_ID,
        transport="http",
        permission_context=pctx,
    )

    await lane_rpc(runtime, ctx, surfaces, refresh_tool)
    lane_capabilities(executor)

    rule("Done")
    print(f"  artifacts in  : {OUTPUT_DIR.relative_to(REPO_ROOT)}")
    for f in sorted(OUTPUT_DIR.glob("*.html")):
        print(f"    - {f.name}")


def _serve_and_open(directory: Path, port: int = 8091) -> None:
    """Serve OUTPUT_DIR over HTTP and open the default dashboard."""
    os.chdir(directory)
    socketserver.TCPServer.allow_reuse_address = True
    try:
        httpd = socketserver.TCPServer(("", port), http.server.SimpleHTTPRequestHandler)
    except OSError as exc:
        print(f"  ⚠ could not bind port {port}: {exc}")
        return

    url = f"http://localhost:{port}/01_dashboard_default.html"
    print(f"\n  🌐 serving at {url} — Ctrl+C to stop\n")
    threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  server stopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Deterministic refresh + inline filtering over A2UI",
    )
    parser.add_argument("--serve", action="store_true", help="serve + open the output")
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args()

    asyncio.run(main())

    if args.serve:
        _serve_and_open(OUTPUT_DIR, port=args.port)

    # Some parrot subsystems may leave non-daemon threads alive; flush + _exit
    # is the same belt-and-suspenders guard the sibling examples use.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
