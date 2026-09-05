"""A2UI v1.0 dashboards from an agent — a layer-by-layer walkthrough.

This example takes ONE synthetic dataset and follows it all the way down the
A2UI stack, printing what each layer did to it. It is written to be *read*
top-to-bottom like a notebook, not just executed.

The eight steps::

    1. The agent          — PandasAgent + InfographicToolkit (dual-emit by default, FEAT-527)
    2. The contract       — a template's positional block contract
    3. The blocks         — typed InfographicBlocks built from a DataFrame
    4. The render         — InfographicRenderResult (HTML artifact + envelope)
    5. The wire           — the A2UI v1.0 envelope-by-key (FEAT-470)
    6. Lowering           — Parrot composites become Basic Catalog primitives
    7. Baking             — data-model bindings resolve to literals
    8. Renderers          — the baked surface becomes HTML

By default nothing calls an LLM: step 3 builds the typed blocks in Python, so
the walkthrough runs anywhere, offline, in a few seconds. The data is seeded and
the whole mapping is pure, so every run produces the same surface *content* —
only ``surfaceId`` changes, because it is derived from the id of the artifact
persisted on that run. ``--live`` replaces step 3 with a real
``agent.ask(...)`` so you can watch the LLM choose the tools itself and see
``OutputMode.A2UI`` route the result.

Usage::

    source .venv/bin/activate
    python examples/agents/a2ui/a2ui_dashboard_walkthrough.py
    python examples/agents/a2ui/a2ui_dashboard_walkthrough.py --open
    python examples/agents/a2ui/a2ui_dashboard_walkthrough.py --live   # needs an API key

Output lands in ``artifacts/a2ui_dashboard/``.

.. note::

   The ``interactive-html`` renderer emits a self-contained document with an
   embedded Chart.js bundle and a small vanilla-JS runtime. Browsers apply
   same-origin restrictions to ``file://`` pages that break canvas rendering,
   so ``--open`` serves the directory over HTTP rather than opening the file
   directly.

Related: ``docs/outputs/a2ui-v1.md`` (the wire), ``docs/toolkits/
infographic_toolkit.md`` (the toolkit), ``examples/simple_infographic_agent.py``
(the recipe/replay lane this example deliberately does not cover).
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import http.server
import json
import socketserver
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "artifacts" / "a2ui_dashboard"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from parrot.a2a.models import Artifact  # noqa: E402
from parrot.bots.data import PandasAgent  # noqa: E402
from parrot.bots.mixins import InfographicAuthoringMixin  # noqa: E402
from parrot.models.outputs import OutputMode  # noqa: E402
from parrot.outputs.a2ui.baking import bake_envelope  # noqa: E402
from parrot.outputs.a2ui.catalog import get_component  # noqa: E402
from parrot.outputs.a2ui.catalog.base import to_components  # noqa: E402
from parrot.outputs.a2ui.models import CreateSurface  # noqa: E402
from parrot.outputs.a2ui.renderers import get_a2ui_renderer  # noqa: E402
from parrot.registry import register_agent  # noqa: E402
from parrot.storage.artifacts import ArtifactStore  # noqa: E402
from parrot.storage.backends import build_overflow_store  # noqa: E402
from parrot.storage.backends.sqlite import ConversationSQLiteBackend  # noqa: E402
from parrot.tools.infographic_toolkit import InfographicToolkit  # noqa: E402

from synthetic_data import (  # noqa: E402
    COMPANY,
    as_money,
    build_goals,
    build_monthly_metrics,
    build_plan_mix,
)

# The A2UI renderers ship in the ai-parrot-visualizations satellite and register
# themselves on import. Two of them (``interactive-html``, ``ssr_html``) are used
# below; importing the module here rather than relying on ``get_a2ui_renderer``'s
# lazy import is deliberate — that lazy path derives a module name from the
# registry name, which only works when the two match. ``interactive-html``
# (hyphen) lives in ``interactive_html.py`` (underscore), so it must already be
# imported by the time ``get_a2ui_renderer("interactive-html")`` is called.
try:
    import parrot.outputs.a2ui_renderers.interactive_html  # noqa: F401,E402
    import parrot.outputs.a2ui_renderers.ssr_html  # noqa: F401,E402

    HAS_RENDERERS = True
except ImportError:  # pragma: no cover - depends on optional extra
    HAS_RENDERERS = False

#: Built-in infographic template this walkthrough targets. Its positional block
#: contract (step 2) is what the blocks in step 3 must satisfy.
TEMPLATE = "dashboard"

#: Question the ``--live`` LLM path is asked. The deterministic path builds the
#: same dashboard directly, so both lanes converge on step 4.
LIVE_QUESTION = (
    "Build a dashboard infographic from the `metrics` and `plans` dataframes.\n"
    "\n"
    "Use `infographic_build_block` for EVERY block, in this exact order, so the\n"
    "chart and table blocks are derived from the dataframes rather than hand-written:\n"
    "  1. block_type='title'     — block={'type':'title','title':'Northwind Cloud — "
    "Revenue Operations','subtitle':'12 months of synthetic data'}\n"
    "  2. block_type='hero_card' — block={'type':'hero_card','label':'Closing MRR',"
    "'value':<the last row's mrr, formatted>,'trend':'up'}\n"
    "  3. block_type='chart'     — data_variable='metrics', chart_type='line', "
    "label_column='month', value_columns=['mrr','new_mrr'], title='MRR trend'\n"
    "  4. block_type='chart'     — data_variable='plans', chart_type='bar', "
    "label_column='plan', value_columns=['mrr'], title='MRR by plan'\n"
    "  5. block_type='table'     — data_variable='metrics', table_columns="
    "['month','mrr','churn_rate','active_accounts','nps'], title='Monthly detail'\n"
    "  6. block_type='progress'  — block={'type':'progress','title':'Goal completion',"
    "'items':[{'label':'ARR target','value':90.0}]}\n"
    "\n"
    "Then call infographic_render(template_name='dashboard', theme='dark', "
    "mode='deterministic', data_variables=['metrics','plans'], "
    "blocks_variable='infographic_blocks')."
)


def rule(title: str) -> None:
    """Print a step header.

    Args:
        title: The step title to display.
    """
    print(f"\n{'=' * 72}\n  {title}\n{'=' * 72}")


# ═══════════════════════════════════════════════════════════════════════════
# The agent
# ═══════════════════════════════════════════════════════════════════════════


@register_agent(name="a2ui_dashboard")
class A2UIDashboardAgent(InfographicAuthoringMixin, PandasAgent):
    """A PandasAgent that answers with A2UI dashboard surfaces.

    Two things make this agent emit A2UI rather than plain HTML:

    1. Its ``InfographicToolkit`` emits by default (FEAT-527: ``emit_a2ui=True``
       is the default), so every render additionally produces a
       catalog-validated envelope alongside the HTML artifact. The toolkit is
       still passed in explicitly here for clarity — ``InfographicAuthoringMixin``
       will happily build one for you from ``artifact_store=`` and it emits
       just the same, since it inherits the default.
    2. Callers ask with ``output_mode=OutputMode.A2UI``. ``BaseBot`` then routes
       the result through ``finalize_a2ui_response`` (``parrot/outputs/a2ui/
       emission.py``), which bypasses the legacy ``OutputFormatter`` entirely
       and leaves the envelope on ``response.a2ui_envelope``.

    The A2UI lane is *additive*: if envelope construction fails, the toolkit
    logs and returns ``a2ui_envelope=None``, and the agent still answers with
    the HTML artifact. A broken surface never costs you the dashboard.
    """

    agent_id: str = "a2ui_dashboard"
    llm = "google:gemini-3.5-flash"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, llm=kwargs.pop("llm", None) or self.llm, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════
# Step 1 — the agent
# ═══════════════════════════════════════════════════════════════════════════


async def step1_agent(
    frames: Dict[str, pd.DataFrame], artifact_store: ArtifactStore
) -> tuple[A2UIDashboardAgent, InfographicToolkit]:
    """Build the agent and its A2UI-emitting toolkit.

    Args:
        frames: DataFrames to load into the agent's pandas REPL, keyed by the
            name they get in that namespace.
        artifact_store: Where rendered artifacts are persisted.

    Returns:
        The (already opened) agent and the toolkit bound to it.
    """
    rule("Step 1 — the agent: PandasAgent + InfographicToolkit (dual-emit by default)")

    toolkit = InfographicToolkit(artifact_store=artifact_store, emit_a2ui=True)
    agent = A2UIDashboardAgent(
        name="a2ui-dashboard",
        df=frames,
        infographic_toolkit=toolkit,
        generate_eda=False,
        injection_detection=False,
    )
    await agent.__aenter__()

    print(f"  agent          : {agent.name} (llm={A2UIDashboardAgent.llm})")
    print(f"  emit_a2ui      : {toolkit._emit_a2ui}")
    print("  tools exposed  :")
    for tool in toolkit.get_tools():
        print(f"     - {tool.name}")

    # The toolkit reads its data straight out of the agent's pandas REPL — the
    # same namespace the LLM's code runs in. `data_variables` in step 4 must
    # name frames that live here.
    repl = await agent._get_repl_locals()
    frames_in_repl = sorted(k for k, v in repl.items() if isinstance(v, pd.DataFrame))
    print(f"  REPL dataframes: {frames_in_repl}")
    return agent, toolkit


# ═══════════════════════════════════════════════════════════════════════════
# Step 2 — the template contract
# ═══════════════════════════════════════════════════════════════════════════


async def step2_contract(toolkit: InfographicToolkit) -> List[Dict[str, Any]]:
    """Print the template's positional block contract.

    A template is not a free-form canvas: it declares an ordered list of block
    slots, each with a required type and optional item-count bounds. Blocks are
    matched to slots **by position**, and ``render()`` refuses anything that
    does not line up — wrong type, missing required slot, or extra blocks.

    This is the contract the LLM is shown (via ``infographic_get_template_contract``)
    before it builds anything, and it is why the deterministic and ``--live``
    lanes can converge on the same envelope.

    Args:
        toolkit: The toolkit whose template registry to query.

    Returns:
        The contract's ``block_specs`` list.
    """
    rule(f"Step 2 — the contract: template {TEMPLATE!r} is positional")

    contract = await toolkit.get_template_contract(TEMPLATE)
    print(f"  {contract['description']}")
    print(f"  default theme  : {contract['default_theme']}\n")
    print("  position  type         required  items")
    print("  --------  -----------  --------  -----")
    for spec in contract["block_specs"]:
        bounds = ""
        if spec["min_items"] or spec["max_items"]:
            bounds = f"{spec['min_items'] or '-'}..{spec['max_items'] or '-'}"
        print(
            f"  {spec['position']:^8}  {spec['block_type']:<11}  " f"{'yes' if spec['required'] else 'no':<8}  {bounds}"
        )
    return contract["block_specs"]


# ═══════════════════════════════════════════════════════════════════════════
# Step 3 — the typed blocks
# ═══════════════════════════════════════════════════════════════════════════


def step3_blocks(monthly: pd.DataFrame, plans: pd.DataFrame) -> List[Dict[str, Any]]:
    """Build the six typed blocks the ``dashboard`` template expects.

    In the ``--live`` lane the LLM produces exactly this structure by calling
    ``infographic_build_block`` / ``infographic_render``. Building it in Python
    here keeps the walkthrough deterministic and shows precisely what shape the
    LLM is being asked for.

    Note what is NOT here: no colors, no HTML, no layout. Typed blocks are
    *semantic* — the template owns the styling and the A2UI catalog owns the
    component mapping.

    Args:
        monthly: The 12-month metrics series.
        plans: The closing-month plan breakdown.

    Returns:
        Six block dicts, in the template's slot order.
    """
    rule("Step 3 — the blocks: typed, semantic, positional")

    closing = monthly.iloc[-1]
    opening_mrr = float(monthly["mrr"].iloc[0])
    closing_mrr = float(closing["mrr"])
    growth_pct = (closing_mrr / opening_mrr - 1.0) * 100.0

    blocks: List[Dict[str, Any]] = [
        # 0 — title
        {
            "type": "title",
            "title": f"{COMPANY} — Revenue Operations",
            "subtitle": "12 months of synthetic data, closing December",
            "date": "FY2026",
        },
        # 1 — hero_card
        {
            "type": "hero_card",
            "label": "Closing MRR",
            "value": as_money(closing_mrr),
            "trend": "up" if growth_pct >= 0 else "down",
            "trend_value": f"{growth_pct:+.1f}% YoY",
        },
        # 2 — chart: the primary trend
        {
            "type": "chart",
            "chart_type": "line",
            "title": "MRR trend",
            "labels": list(monthly["month"]),
            "series": [
                {"name": "MRR", "values": [float(v) for v in monthly["mrr"]]},
                {"name": "New MRR", "values": [float(v) for v in monthly["new_mrr"]]},
            ],
            "y_axis_label": "USD",
            "show_legend": True,
        },
        # 3 — chart: the composition
        {
            "type": "chart",
            "chart_type": "bar",
            "title": "MRR by plan (December)",
            "labels": list(plans["plan"]),
            "series": [{"name": "MRR", "values": [float(v) for v in plans["mrr"]]}],
            "show_legend": False,
        },
        # 4 — table: the detail behind the charts
        {
            "type": "table",
            "title": "Monthly detail",
            "columns": ["Month", "MRR", "Churn %", "Accounts", "NPS"],
            "rows": [
                [
                    row["month"],
                    as_money(float(row["mrr"])),
                    f"{row['churn_rate']:.2f}",
                    int(row["active_accounts"]),
                    int(row["nps"]),
                ]
                for _, row in monthly.iterrows()
            ],
            "sortable": True,
        },
        # 5 — progress: optional slot
        {"type": "progress", "title": "Goal completion", "items": build_goals(monthly)},
    ]

    for idx, block in enumerate(blocks):
        label = block.get("title") or block.get("label") or ""
        print(f"  [{idx}] {block['type']:<11} {label}")
    return blocks


# ═══════════════════════════════════════════════════════════════════════════
# Step 4 — the render
# ═══════════════════════════════════════════════════════════════════════════


async def step4_render(
    toolkit: InfographicToolkit,
    agent: "A2UIDashboardAgent",
    artifact_store: ArtifactStore,
    blocks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Render the blocks into an HTML artifact plus an A2UI envelope.

    ``render()`` validates the blocks against the contract, renders the HTML
    skeleton, persists it, and — because ``emit_a2ui`` defaults to ``True``
    (FEAT-527) — additionally maps the same ``InfographicResponse`` through
    ``parrot.outputs.a2ui.adapters.infographic_response_to_envelope``. Both
    outputs therefore describe identical content by construction; the envelope
    is never a second, drifting source of truth.

    Args:
        toolkit: The A2UI-emitting toolkit, already bound to the agent.
        agent: The bound agent, used to resolve the artifact's storage scope.
        artifact_store: The store the HTML artifact was persisted to.
        blocks: The six typed blocks from step 3.

    Returns:
        The A2UI envelope dict carried on the result.

    Raises:
        RuntimeError: If envelope construction degraded to ``None``.
    """
    rule("Step 4 — the render: one call, two surfaces")

    result = await toolkit.render(
        template_name=TEMPLATE,
        theme="dark",
        mode="deterministic",  # "enhance" would spend LLM tokens on JS interactivity
        data_variables=["metrics", "plans"],  # provenance: REPL frames behind the numbers
        blocks=blocks,
    )

    print(f"  artifact_id    : {result.artifact_id}")
    print(f"  template/theme : {result.template_name} / {result.theme}")
    print(f"  data_variables : {result.data_variables}")
    print(f"  a2ui_envelope  : {'present' if result.a2ui_envelope else 'None (degraded)'}")

    if result.a2ui_envelope is None:
        raise RuntimeError(
            "The A2UI lane degraded to HTML-only — check the toolkit logs for "
            "the CatalogValidationError that caused it."
        )

    # The HTML is echoed back inline only when it is small (under 50 KB); past
    # that the result carries just the id and URL, and you read it back out of
    # the artifact store. `_resolve_scope` is the toolkit's own internal helper
    # for the (user, agent, session) triple it persisted under.
    html = result.html_inline
    if html is None:
        print("  html_inline    : None (over the 50 KB inline threshold)")
        user_id, agent_id, session_id = toolkit._resolve_scope(agent)
        artifact = await artifact_store.get_artifact(user_id, agent_id, session_id, result.artifact_id)
        html = (artifact.definition or {}).get("html") if artifact else None
        print(f"  from store     : {len(html or ''):,} chars")
    else:
        print(f"  html_inline    : {len(html):,} chars")

    if html:
        html_path = OUTPUT_DIR / "01_infographic_template.html"
        html_path.write_text(html)
        print(f"  wrote          : {html_path.relative_to(REPO_ROOT)}")

    return result.a2ui_envelope


# ═══════════════════════════════════════════════════════════════════════════
# Step 5 — the A2UI v1.0 wire
# ═══════════════════════════════════════════════════════════════════════════


def step5_wire(wire: Dict[str, Any]) -> CreateSurface:
    """Show the A2UI v1.0 envelope-by-key that the toolkit emits.

    FEAT-470 made the Pydantic models *be* the wire, and the toolkit emits that
    wire directly — ``InfographicRenderResult.a2ui_envelope`` (and therefore
    ``response.a2ui_envelope``) is the finished envelope, ready to hand to
    ``Artifact.from_a2ui_envelope`` or an external renderer with no re-shaping.

    Four shape rules matter, and all four are visible in the JSON this step
    writes:

    * **Envelope by key** — ``{"version": "v1.0", "createSurface": {...}}``,
      exactly two keys. ``version`` is written in exactly one place in the whole
      codebase (``serialization.serialize``), never by the message models.
    * **camelCase on the wire** — ``surfaceId``, ``catalogId``, ``dataModel``.
      The Python models use snake_case field names; the aliases are the wire.
    * **Top-level props** — catalog properties (``title``, ``sections``, ...) sit
      directly on the component, NOT nested under a ``properties`` key. The one
      surviving exception is the ``Infographic`` composite's own
      ``sections[].components[]`` *descriptors*, which are not wire components.
    * **Bindings** — a dynamic value is ``{"path": "/pointer"}`` (RFC 6901), not
      the pre-v1.0 ``{"$bind": ...}``. Chart and table rows live in the surface's
      ``dataModel`` and are referenced by pointer.

    Every ``CreateSurface`` also carries exactly one component with ``id: "root"``.

    Args:
        wire: The v1.0 envelope carried on the render result.

    Returns:
        The ``CreateSurface`` model for the inner surface, used by later steps.
    """
    rule("Step 5 — the wire: A2UI v1.0 envelope-by-key")

    print(f"  envelope keys            : {sorted(wire)}")
    print(f"  version                  : {wire['version']!r}")

    inner = wire["createSurface"]
    root = inner["components"][0]
    # Derived from the artifact id, which the toolkit uses verbatim as the
    # surface id — so this is the one field that differs between two otherwise
    # identical runs.
    print(f"  surfaceId                : {inner['surfaceId']}")
    print(f"  catalogId                : {inner['catalogId']}")
    print(
        f"  components               : {len(inner['components'])} "
        f"(root id={root['id']!r}, component={root['component']!r})"
    )
    print(f"  root top-level props     : {sorted(k for k in root if k not in ('id', 'component'))}")
    print(f"  dataModel keys           : {sorted(inner.get('dataModel', {}))}")

    # Show the bindings the adapter created for the chart/table rows.
    print(f"  data bindings            : {_find_bindings(root)}")

    # The envelope is A2A-ready as-is — no re-serialization at the boundary.
    artifact = Artifact.from_a2ui_envelope(wire, name="dashboard")
    print(f"  A2A artifact             : accepted " f"(mimeType={artifact.parts[0].metadata['mimeType']})")

    wire_path = OUTPUT_DIR / "02_envelope_v1.json"
    wire_path.write_text(json.dumps(wire, indent=2))
    print(f"  wrote                    : {wire_path.relative_to(REPO_ROOT)}")

    # Later steps operate on the inner surface model, not the wrapper.
    return CreateSurface.model_validate(inner)


def _find_bindings(node: Any, found: Optional[List[str]] = None) -> List[str]:
    """Collect every ``{"path": ...}`` binding pointer in a component subtree.

    Args:
        node: Any nested dict/list from a component tree.
        found: Accumulator used by the recursion.

    Returns:
        The sorted, de-duplicated list of JSON-pointer strings.
    """
    found = [] if found is None else found
    if isinstance(node, dict):
        if set(node) == {"path"} and isinstance(node["path"], str):
            found.append(node["path"])
        for value in node.values():
            _find_bindings(value, found)
    elif isinstance(node, list):
        for item in node:
            _find_bindings(item, found)
    return sorted(set(found))


# ═══════════════════════════════════════════════════════════════════════════
# Step 6 — catalog lowering
# ═══════════════════════════════════════════════════════════════════════════


def step6_lowering(surface: CreateSurface) -> CreateSurface:
    """Lower the Parrot composite into official Basic Catalog primitives.

    A2UI defines two catalogs here: the official **Basic** catalog (18
    primitives, 14 functions) and Parrot's own presentation catalog
    (``Infographic``, ``Chart``, ``DataTable``, ``KPICard``, ``InfoCard``,
    ``Map``, ``Timeline``, ``Report``). Every non-primitive component MUST
    implement ``lower()`` — enforced at registration time — returning a tree
    built purely from Basic primitives.

    This is what makes a Parrot surface portable: renderers dispatch on Basic
    Catalog names only, so a surface built from Parrot composites still renders
    on anything that speaks plain A2UI v1.0.

    Args:
        surface: The validated ``CreateSurface`` from step 5.

    Returns:
        The same surface with its composite replaced by lowered primitives.
    """
    rule("Step 6 — lowering: Parrot composites → Basic Catalog primitives")

    lowered: List[Any] = []
    for component in surface.components:
        try:
            entry = get_component(component.component)
        except KeyError:
            entry = None
        if entry is not None and not entry.definition.is_primitive:
            tree = entry.component_cls().lower(component, surface.data_model)
            flat = to_components(tree, id_prefix=f"{component.id}-lc")
            print(f"  {component.component:<14} (composite) → {len(flat)} primitives")
            lowered.extend(flat)
        else:
            print(f"  {component.component:<14} (primitive)  → kept as-is")
            lowered.append(component)

    kinds: Dict[str, int] = {}
    for component in lowered:
        kinds[component.component] = kinds.get(component.component, 0) + 1
    print(f"  primitive mix  : {dict(sorted(kinds.items()))}")
    return surface.model_copy(update={"components": lowered})


# ═══════════════════════════════════════════════════════════════════════════
# Step 7 — baking
# ═══════════════════════════════════════════════════════════════════════════


def step7_baking(lowered: CreateSurface) -> List[Dict[str, Any]]:
    """Resolve every binding so the surface is self-contained.

    Live A2UI renderers keep bindings live and re-resolve them as the data
    model updates. Static renderers (HTML, PDF, Adaptive Cards) cannot, so
    ``bake_envelope`` walks the tree once, resolves each ``{"path": ...}``
    against the data model, expands any ``ChildTemplate`` into concrete cloned
    children, and guarantees as a post-condition that no live expression
    survives.

    Order matters: lowering MUST happen first. Baking a surface whose composite
    is still opaque leaves the composite's internal bindings untouched — which
    is why step 6 comes before step 7.

    Args:
        lowered: The lowered surface from step 6.

    Returns:
        The flat list of baked component dicts.
    """
    rule("Step 7 — baking: bindings → literals")

    baked = bake_envelope(lowered)
    live = [p for component in baked for p in _find_bindings(component)]

    # The count grows: a `ChildTemplate` is one source component before baking
    # and one clone per bound list item after it — this is where the twelve
    # monthly table rows stop being a pointer and become twelve real subtrees.
    print(f"  components in  : {len(lowered.components)}")
    print(f"  components out : {len(baked)}  (template expansion)")
    print(f"  live bindings  : {len(live)} (post-condition: must be 0)")

    baked_path = OUTPUT_DIR / "03_baked_components.json"
    baked_path.write_text(json.dumps(baked, indent=2))
    print(f"  wrote          : {baked_path.relative_to(REPO_ROOT)}")
    return baked


# ═══════════════════════════════════════════════════════════════════════════
# Step 8 — renderers
# ═══════════════════════════════════════════════════════════════════════════


async def step8_render_surfaces(surface: CreateSurface) -> Optional[Path]:
    """Render the surface through two A2UI renderers.

    Both renderers are handed the SAME unlowered envelope — each runs lowering
    and baking itself, in that order. They differ in what they do with the
    result:

    * ``ssr_html`` — fully static, no JavaScript. Charts and tables degrade to
      their lowered text form.
    * ``interactive-html`` — intercepts ``Chart``/``DataTable``/``Infographic``
      *before* lowering and renders real graphics with a vendored Chart.js
      bundle plus a small vanilla-JS runtime (tab switching, metric toggles,
      column sort), then lowers everything else normally.

    Args:
        surface: The original (unlowered) surface from step 5.

    Returns:
        The path to the interactive HTML file, or ``None`` when the
        visualizations satellite is unavailable.
    """
    rule("Step 8 — renderers: the same surface, two targets")

    if not HAS_RENDERERS:
        print("  ai-parrot-visualizations[a2ui] not installed — skipping.")
        print("  install with: pip install ai-parrot-visualizations[a2ui]")
        return None

    interactive_path: Optional[Path] = None
    targets = [("ssr_html", "04_surface_static.html"), ("interactive-html", "05_surface_interactive.html")]

    for name, filename in targets:
        renderer = get_a2ui_renderer(name)()
        artifact = await renderer.render(surface)
        path = OUTPUT_DIR / filename
        path.write_bytes(artifact.content or b"")

        caps = renderer.capabilities
        degraded = (artifact.metadata or {}).get("degraded") or []
        print(
            f"  {name:<18} interactive={str(caps.interactive):<5} "
            f"{len(artifact.content or b''):>8,} bytes  degraded={len(degraded)}"
        )
        print(f"  {'':<18} → {path.relative_to(REPO_ROOT)}")

        if name == "interactive-html":
            interactive_path = path

    return interactive_path


# ═══════════════════════════════════════════════════════════════════════════
# The --live lane
# ═══════════════════════════════════════════════════════════════════════════


async def live_lane(agent: A2UIDashboardAgent) -> Optional[Dict[str, Any]]:
    """Ask the agent for the dashboard and let the LLM drive the toolkit.

    This is the lane the deterministic steps stand in for. The LLM assembles the
    blocks with ``infographic_build_block`` — which derives chart/table blocks
    from a DataFrame, so it cannot get the field names wrong the way a
    hand-written JSON block can — then calls ``infographic_render``. The agent
    spots the ``InfographicRenderResult`` among the tool calls, sees it carries
    an ``a2ui_envelope``, and routes it through ``finalize_a2ui_response``, which
    sets ``output_mode`` to ``A2UI`` and bypasses the legacy ``OutputFormatter``
    entirely.

    The prompt spells the six ``build_block`` calls out positionally. That is
    not ceremony: the template contract (step 2) declares block *types* and
    counts but not each block model's *fields*, so an unguided LLM reliably
    invents ``chart.data`` instead of ``chart.labels`` + ``chart.series[].values``.
    A wrong guess comes back as a structured ``BLOCK_SCHEMA_INVALID`` the model
    can retry against, but spending turns on it is avoidable.

    Requires a configured provider key for ``A2UIDashboardAgent.llm``.

    Args:
        agent: The opened agent.

    Returns:
        The v1.0 envelope the agent produced, or ``None`` if it answered in prose
        without rendering (in which case the mode is downgraded to ``DEFAULT``).
    """
    rule("--live — agent.ask(..., output_mode=OutputMode.A2UI)")
    print(f"  question: {LIVE_QUESTION}\n")

    response = await agent.ask(LIVE_QUESTION, output_mode=OutputMode.A2UI)

    envelope = getattr(response, "a2ui_envelope", None)
    print(f"  output_mode    : {getattr(response, 'output_mode', None)}")
    print(f"  a2ui_envelope  : {'present' if envelope else 'None'}")
    print(f"  response text  : {str(getattr(response, 'response', ''))[:160]}")

    if envelope is None:
        print("\n  The LLM answered without rendering a surface, so the output mode")
        print("  was downgraded to DEFAULT rather than dispatched to a renderer")
        print("  that has nothing to render. Check the log for a tool error.")
        return None

    live_path = OUTPUT_DIR / "06_live_envelope.json"
    live_path.write_text(json.dumps(envelope, indent=2))
    print(f"  wrote          : {live_path.relative_to(REPO_ROOT)}")
    return envelope


# ═══════════════════════════════════════════════════════════════════════════
# Serving
# ═══════════════════════════════════════════════════════════════════════════


def serve(directory: Path, filename: str, port: int = 8080) -> None:
    """Serve ``directory`` over HTTP and open ``filename`` in a browser.

    The interactive renderer's output needs an HTTP origin — ``file://`` breaks
    its canvas rendering and scripts.

    Call this from synchronous code, NOT from inside ``asyncio.run``: uvloop
    installs its own SIGINT handling, so a ``KeyboardInterrupt`` raised while a
    blocking ``serve_forever()`` runs inside the loop never reaches this
    ``except`` and Ctrl+C appears to hang.

    Args:
        directory: Directory to serve.
        filename: File within it to open.
        port: Port to bind.
    """
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        url = f"http://127.0.0.1:{port}/{filename}"
        print(f"\n  serving {directory} at {url}")
        print("  press Ctrl+C to stop.")
        opener = threading.Timer(0.5, lambda: webbrowser.open(url))
        opener.daemon = True  # a pending timer must never hold the process open
        opener.start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  stopped.")
        finally:
            httpd.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════


async def main(args: argparse.Namespace) -> Optional[Path]:
    """Run the walkthrough.

    Args:
        args: Parsed command-line arguments.

    Returns:
        The path to the interactive surface, or ``None`` when there is nothing
        to serve. Serving is the caller's job — it must happen outside
        ``asyncio.run`` for Ctrl+C to work (see :func:`serve`).
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    monthly = build_monthly_metrics()
    plans = build_plan_mix(monthly)
    print(f"Synthetic data: metrics={monthly.shape}, plans={plans.shape} (seeded, reproducible)")

    backend = ConversationSQLiteBackend(path=str(OUTPUT_DIR / "artifacts.db"))
    await backend.initialize()
    artifact_store = ArtifactStore(backend, build_overflow_store())

    agent, toolkit = await step1_agent({"metrics": monthly, "plans": plans}, artifact_store)
    try:
        await step2_contract(toolkit)

        if args.live:
            envelope_dump = await live_lane(agent)
            if envelope_dump is None:
                return None
        else:
            blocks = step3_blocks(monthly, plans)
            envelope_dump = await step4_render(toolkit, agent, artifact_store, blocks)

        surface = step5_wire(envelope_dump)
        lowered = step6_lowering(surface)
        step7_baking(lowered)
        interactive = await step8_render_surfaces(surface)
    finally:
        await agent.__aexit__(None, None, None)
        # aiosqlite runs a non-daemon worker thread; without this the process
        # finishes its work and then simply never exits.
        await backend.close()

    rule("Done")
    print(f"  artifacts in: {OUTPUT_DIR.relative_to(REPO_ROOT)}")
    for path in sorted(OUTPUT_DIR.glob("0*")):
        print(f"    {path.name:<32} {path.stat().st_size:>9,} bytes")

    return interactive


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        The parsed namespace.
    """
    parser = argparse.ArgumentParser(
        description="A2UI v1.0 dashboard walkthrough — InfographicToolkit + output modes.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="ask the LLM to build the dashboard instead of building the blocks in Python "
        "(requires a configured provider key).",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="serve the output directory over HTTP and open the interactive surface.",
    )
    parser.add_argument("--port", type=int, default=8080, help="port for --open (default: 8080).")
    return parser.parse_args()


if __name__ == "__main__":
    _args = _parse_args()
    _interactive = asyncio.run(main(_args))
    # Serving happens OUTSIDE asyncio.run so Ctrl+C is an ordinary
    # KeyboardInterrupt in the main thread (see serve()'s docstring).
    if _args.open:
        if _interactive is not None:
            serve(OUTPUT_DIR, _interactive.name, port=_args.port)
        else:
            print("\n  nothing interactive to open (renderers unavailable).")
