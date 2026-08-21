"""Simple InfographicToolkit + A2UI example — in-memory data, no external services.

Demonstrates both tiers of the infographic authoring workflow with zero
external dependencies (no Postgres, no Redis, no skills, no narrative):

**Demo 1 — Tier 1 (Toolkit direct):**
    ``InfographicToolkit.render_template()`` with an inline Jinja template.
    Raw data → styled HTML in one call, no agent needed.

**Demo 2 — Tier 2 (A2UI publish + replay):**
    Register custom ``@infographic_transformer`` functions, publish a
    declarative recipe via ``InfographicAuthoringMixin.publish_recipe()``,
    then replay deterministically with ``RecipeRunner``.

Prerequisites::

    pip install ai-parrot
    # For tier-2 replay rendering:
    pip install ai-parrot-visualizations[a2ui]

Usage::

    source .venv/bin/activate
    python examples/simple_infographic_agent.py            # generate only
    python examples/simple_infographic_agent.py --serve     # generate + open in browser

.. note::

   The Tier-2 A2UI ``interactive-html`` renderer produces self-contained HTML
   with embedded Chart.js and interactive scripts.  These **require HTTP
   serving** — opening them as ``file://`` triggers browser same-origin
   restrictions that break canvas rendering and script execution.  Use
   ``--serve`` to auto-start a local HTTP server, or serve manually::

       cd artifacts/simple_infographic && python -m http.server 8080
"""
from __future__ import annotations

import argparse
import asyncio
import http.server
import os
import socketserver
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "artifacts" / "simple_infographic"

# PEP-420 bootstrap: ai-parrot-visualizations ships the ``interactive-html``
# A2UI renderer as a namespace-merged ``parrot.outputs.a2ui_renderers``
# subpackage.  When the package is pip-installed this happens automatically;
# during development from a checkout we extend ``parrot.outputs.__path__``
# manually (same dance as ``budget_variance_infographic.py``).
_VISUALIZATIONS_SRC = REPO_ROOT / "packages" / "ai-parrot-visualizations" / "src"
_HAS_VISUALIZATIONS = False
if (_VISUALIZATIONS_SRC / "parrot" / "outputs").is_dir():
    if str(_VISUALIZATIONS_SRC) not in sys.path:
        sys.path.insert(0, str(_VISUALIZATIONS_SRC))
    import parrot.outputs as _po  # noqa: E402

    _vis_path = str(_VISUALIZATIONS_SRC / "parrot" / "outputs")
    if _vis_path not in _po.__path__:
        _po.__path__.insert(0, _vis_path)
    try:
        import parrot.outputs.a2ui_renderers.interactive_html  # noqa: F401,E402

        _HAS_VISUALIZATIONS = True
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Parrot imports
# ---------------------------------------------------------------------------
from parrot.auth.permission import build_principal_context  # noqa: E402
from parrot.bots.data import PandasAgent  # noqa: E402
from parrot.bots.mixins import InfographicAuthoringMixin  # noqa: E402
from parrot.outputs.a2ui.recipes.models import LayoutSpec  # noqa: E402
from parrot.outputs.a2ui.recipes.store import FileRecipeStore  # noqa: E402
from parrot.outputs.a2ui.recipes.transformers import infographic_transformer  # noqa: E402
from parrot.registry import register_agent  # noqa: E402
from parrot.storage.artifacts import ArtifactStore  # noqa: E402
from parrot.storage.backends import build_overflow_store  # noqa: E402
from parrot.storage.backends.sqlite import ConversationSQLiteBackend  # noqa: E402
from parrot.tools.infographic_recipes.runner import (  # noqa: E402
    RecipeRunException,
    RecipeRunner,
)
from parrot.tools.infographic_sections import (  # noqa: E402
    GapReport,
    SectionDescriptor,
    SectionSpec,
)
from parrot.tools.infographic_toolkit import InfographicToolkit  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════
# 1. Sample data
# ═══════════════════════════════════════════════════════════════════════════

def _build_sales_data() -> pd.DataFrame:
    """16-row sales dataset: 4 regions × 2 products × 2 quarters."""
    return pd.DataFrame(
        {
            "region": ["North", "North", "South", "South",
                       "East", "East", "West", "West"] * 2,
            "product": ["Widget", "Gadget"] * 8,
            "quarter": ["Q1"] * 8 + ["Q2"] * 8,
            "revenue": [
                12000, 8500, 9800, 11200, 7600, 13400, 10500, 6800,
                13500, 9200, 10100, 12800, 8900, 14100, 11200, 7500,
            ],
            "units_sold": [
                120, 85, 98, 112, 76, 134, 105, 68,
                135, 92, 101, 128, 89, 141, 112, 75,
            ],
        }
    )


# ═══════════════════════════════════════════════════════════════════════════
# 2. Jinja template for Tier-1 (inline, self-contained HTML)
# ═══════════════════════════════════════════════════════════════════════════

JINJA_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{{ data.title or "Sales Report" }}</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:system-ui,-apple-system,sans-serif;max-width:900px;
         margin:2rem auto;padding:0 1.5rem;color:#1a1a2e;background:#fafafa}
    h1{margin-bottom:1.5rem;color:#16213e}
    .kpi-row{display:flex;gap:1rem;margin-bottom:1.5rem;flex-wrap:wrap}
    .kpi{flex:1;min-width:140px;padding:1rem;background:#fff;
         border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,.08);text-align:center}
    .kpi .value{font-size:1.6rem;font-weight:700;color:#0a3d62}
    .kpi .label{font-size:.8rem;color:#777;margin-top:.25rem}
    table{width:100%;border-collapse:collapse;background:#fff;
          border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}
    th{background:#16213e;color:#fff;padding:.75rem 1rem;text-align:left;font-size:.85rem}
    td{padding:.6rem 1rem;border-bottom:1px solid #eee}
    tr:last-child td{border-bottom:none}
    tr:hover td{background:#f0f4ff}
    .num{text-align:right;font-variant-numeric:tabular-nums}
  </style>
</head>
<body>
  <h1>{{ data.title }}</h1>
  <div class="kpi-row">
    <div class="kpi">
      <div class="value">${{ "{:,.0f}".format(data.grand_total) }}</div>
      <div class="label">Total Revenue</div>
    </div>
    <div class="kpi">
      <div class="value">{{ "{:,}".format(data.total_units) }}</div>
      <div class="label">Units Sold</div>
    </div>
    <div class="kpi">
      <div class="value">{{ data.region_count }}</div>
      <div class="label">Regions</div>
    </div>
  </div>
  <table>
    <thead>
      <tr>
        <th>Region</th><th>Product</th><th>Quarter</th>
        <th class="num">Revenue</th><th class="num">Units</th>
      </tr>
    </thead>
    <tbody>
    {% for row in data.rows %}
      <tr>
        <td>{{ row.region }}</td>
        <td>{{ row.product }}</td>
        <td>{{ row.quarter }}</td>
        <td class="num">${{ "{:,.0f}".format(row.revenue) }}</td>
        <td class="num">{{ row.units_sold }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</body>
</html>
"""

# ═══════════════════════════════════════════════════════════════════════════
# 3. Custom transformers for Tier-2 (registered at import time)
# ═══════════════════════════════════════════════════════════════════════════
#
# Each @infographic_transformer function receives:
#   inputs: dict[str, pd.DataFrame]  — keyed by the section's dataset alias
#   params: dict[str, Any]           — shared descriptor.params
# and returns a plain dict whose keys become the data_model entries that
# LayoutSpec.$bind pointers reference.

@infographic_transformer(
    name="sales_by_region",
    requires_columns={"sales": ["region", "revenue", "units_sold"]},
    description="Aggregate revenue and units sold by region.",
)
def sales_by_region(
    inputs: Dict[str, pd.DataFrame], params: Dict[str, Any]
) -> Dict[str, Any]:
    """Group by region, return per-region totals + grand totals."""
    df = inputs["sales"]
    grouped = (
        df.groupby("region", dropna=False)
        .agg(total_revenue=("revenue", "sum"), total_units=("units_sold", "sum"))
        .reset_index()
    )
    return {
        "by_region": grouped.to_dict(orient="records"),
        "grand_total_revenue": float(df["revenue"].sum()),
        "grand_total_units": int(df["units_sold"].sum()),
        "region_count": int(df["region"].nunique()),
    }


@infographic_transformer(
    name="top_products",
    requires_columns={"sales": ["product", "revenue"]},
    description="Rank products by total revenue, descending.",
)
def top_products(
    inputs: Dict[str, pd.DataFrame], params: Dict[str, Any]
) -> Dict[str, Any]:
    """Rank products by revenue — top seller first."""
    df = inputs["sales"]
    ranked = (
        df.groupby("product", dropna=False)
        .agg(total_revenue=("revenue", "sum"), total_units=("units_sold", "sum"))
        .reset_index()
        .sort_values("total_revenue", ascending=False)
    )
    return {
        "ranking": ranked.to_dict(orient="records"),
        "top_product": str(ranked.iloc[0]["product"]) if len(ranked) > 0 else "N/A",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 4. Section descriptor + LayoutSpec for Tier-2
# ═══════════════════════════════════════════════════════════════════════════

def _sales_descriptor() -> SectionDescriptor:
    """Declarative recipe descriptor: transforms + A2UI layout.

    Each section's ``name`` must match a registered ``@infographic_transformer``
    (normalised to a Python identifier).  ``target`` becomes the
    ``TransformStep.output_key`` (the data_model key).  ``$bind`` pointers in
    the ``LayoutSpec`` reference those keys to wire data into A2UI components.
    """
    return SectionDescriptor(
        template="unused-with-layout",  # overridden by LayoutSpec
        mode="data-splice",
        sections=[
            SectionSpec(
                name="sales_by_region",
                target="/sales_by_region",
                datasets=["sales"],
                shape="mapping",
            ),
            SectionSpec(
                name="top_products",
                target="/top_products",
                datasets=["sales"],
                shape="mapping",
            ),
        ],
        layout=LayoutSpec(
            component="Infographic",
            properties={
                "title": "Sales Performance Dashboard",
                "sections": [
                    {
                        "heading": "Regional Performance",
                        "components": [
                            {
                                "component": "KPICard",
                                "properties": {
                                    "label": "Total Revenue",
                                    "value": {
                                        "$bind": "/sales_by_region/grand_total_revenue"
                                    },
                                },
                            },
                            {
                                "component": "KPICard",
                                "properties": {
                                    "label": "Total Units",
                                    "value": {
                                        "$bind": "/sales_by_region/grand_total_units"
                                    },
                                },
                            },
                            {
                                "component": "KPICard",
                                "properties": {
                                    "label": "Regions",
                                    "value": {
                                        "$bind": "/sales_by_region/region_count"
                                    },
                                },
                            },
                            {
                                "component": "Chart",
                                "properties": {
                                    "title": "Revenue by Region",
                                    "type": "bar",
                                    "x": "region",
                                    "y": ["total_revenue", "total_units"],
                                    "showLegend": True,
                                    "data": {
                                        "$bind": "/sales_by_region/by_region"
                                    },
                                },
                            },
                            {
                                "component": "DataTable",
                                "properties": {
                                    "columns": [
                                        {"name": "region"},
                                        {"name": "total_revenue"},
                                        {"name": "total_units"},
                                    ],
                                    "data": {
                                        "$bind": "/sales_by_region/by_region"
                                    },
                                },
                            },
                        ],
                    },
                    {
                        "heading": "Product Ranking",
                        "components": [
                            {
                                "component": "KPICard",
                                "properties": {
                                    "label": "Top Product",
                                    "value": {
                                        "$bind": "/top_products/top_product"
                                    },
                                },
                            },
                            {
                                "component": "Chart",
                                "properties": {
                                    "title": "Revenue by Product",
                                    "type": "bar",
                                    "x": "product",
                                    "y": ["total_revenue"],
                                    "showLegend": False,
                                    "data": {
                                        "$bind": "/top_products/ranking"
                                    },
                                },
                            },
                            {
                                "component": "DataTable",
                                "properties": {
                                    "columns": [
                                        {"name": "product"},
                                        {"name": "total_revenue"},
                                        {"name": "total_units"},
                                    ],
                                    "data": {
                                        "$bind": "/top_products/ranking"
                                    },
                                },
                            },
                        ],
                    },
                ],
            },
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════
# 5. Agent class (Tier-2 only — Tier-1 uses the toolkit directly)
# ═══════════════════════════════════════════════════════════════════════════

@register_agent(name="simple_reporter")
class SimpleReporter(InfographicAuthoringMixin, PandasAgent):
    """Minimal A2UI reporting agent — in-memory data, no external deps.

    Composes ``InfographicAuthoringMixin`` onto ``PandasAgent`` so that
    ``publish_recipe()`` is available.  The ``llm`` is declared but never
    called — all logic in this example is programmatic.
    """

    agent_id: str = "simple_reporter"
    llm = "google:gemini-3.5-flash"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(
            *args,
            llm=kwargs.pop("llm", None) or self.llm,
            **kwargs,
        )


# ═══════════════════════════════════════════════════════════════════════════
# 6. Demo runners
# ═══════════════════════════════════════════════════════════════════════════

async def demo_tier1(
    sales_df: pd.DataFrame, artifact_store: ArtifactStore
) -> None:
    """Tier-1: InfographicToolkit.render_template() — data → HTML directly.

    No agent, no mixin, no recipes.  The shortest path from a dict of data
    to a persisted, styled HTML artifact.
    """
    print("\n" + "=" * 64)
    print("  Demo 1: Tier-1 — InfographicToolkit.render_template()")
    print("=" * 64)

    # Construct the toolkit with an in-memory Jinja template.
    toolkit = InfographicToolkit(
        artifact_store=artifact_store,
        templates={"sales_table.html": JINJA_TEMPLATE},
    )

    # Render: the ``data`` dict is available as ``{{ data.* }}`` in Jinja.
    result = await toolkit.render_template(
        "sales_table.html",
        data={
            "title": "Q1–Q2 Sales Report",
            "rows": sales_df.to_dict(orient="records"),
            "grand_total": float(sales_df["revenue"].sum()),
            "total_units": int(sales_df["units_sold"].sum()),
            "region_count": int(sales_df["region"].nunique()),
        },
    )

    print(f"  artifact_id : {result.artifact_id}")
    print(f"  html_url    : {result.html_url}")
    inline_len = len(result.html_inline) if result.html_inline else 0
    print(f"  html_inline : {inline_len:,} chars")

    # Save to disk for inspection.
    if result.html_inline:
        out = OUTPUT_DIR / "tier1_sales_table.html"
        out.write_text(result.html_inline)
        print(f"  saved to    : {out}")


async def demo_tier2(
    sales_df: pd.DataFrame,
    artifact_store: ArtifactStore,
    recipe_store: FileRecipeStore,
) -> None:
    """Tier-2: publish_recipe + RecipeRunner — declarative A2UI pipeline.

    1. Instantiate a ``SimpleReporter`` with in-memory data.
    2. ``publish_recipe()`` maps each section to a registered transformer
       and saves a deterministic ``InfographicRecipe``.
    3. ``RecipeRunner.run()`` replays the recipe: fetch data → transform →
       assemble A2UI envelope → render HTML.
    """
    print("\n" + "=" * 64)
    print("  Demo 2: Tier-2 — publish_recipe + RecipeRunner")
    print("=" * 64)

    # --- Agent setup (LLM declared but never called) ---
    agent = SimpleReporter(
        name="simple-reporter",
        artifact_store=artifact_store,
        recipe_store=recipe_store,
        injection_detection=False,
    )

    # Register the DataFrame as an in-memory dataset named "sales".
    # The transformer's ``inputs["sales"]`` receives this frame.
    agent._dataset_manager.add_dataframe(
        "sales",
        sales_df,
        description="Quarterly sales data by region and product",
    )

    # --- Publish the recipe ---
    descriptor = _sales_descriptor()
    recipe = await agent.publish_recipe(
        "simple-sales-dashboard",
        descriptor,
        overwrite=True,
    )

    # publish_recipe returns InfographicRecipe on full coverage,
    # or GapReport if any section has no matching transformer.
    if isinstance(recipe, GapReport):
        print("  ✗ GAPS — unregistered transformers:")
        for gap in recipe.gaps:
            print(f"    - {gap.section}: register "
                  f"@infographic_transformer(name='{gap.section}')")
        return

    print(f"  recipe       : {recipe.name}")
    print(f"  transforms   : {len(recipe.transforms)} step(s)")
    for step in recipe.transforms:
        print(f"    → {step.transformer}  inputs={step.inputs}  "
              f"output_key={step.output_key}")
    print(f"  data_sources : {[ds.alias for ds in recipe.data_sources]}")
    print(f"  layout       : {recipe.layout.component}")

    # --- Replay the recipe ---
    if not _HAS_VISUALIZATIONS:
        print("\n  ⚠ ai-parrot-visualizations[a2ui] not available — "
              "skipping replay.")
        print("    Install it for full A2UI rendering:")
        print("    pip install ai-parrot-visualizations[a2ui]")
        return

    pctx = build_principal_context("simple-example", channel="script")
    runner = RecipeRunner(recipe_store, agent._dataset_manager)

    try:
        artifact = await runner.run("simple-sales-dashboard", pctx=pctx)
    except RecipeRunException as exc:
        print(f"\n  ✗ replay BLOCKED — [{exc.error.stage}] {exc.error.detail}")
        return

    rendered_len = len(artifact.content or b"")
    print(f"\n  replay       : {rendered_len:,} bytes rendered")

    out = OUTPUT_DIR / "tier2_sales_dashboard.html"
    out.write_bytes(artifact.content or b"")
    print(f"  saved to     : {out}")


# ═══════════════════════════════════════════════════════════════════════════
# 7. Main
# ═══════════════════════════════════════════════════════════════════════════

async def main() -> None:
    """Set up local storage, build sample data, run both demos."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- Storage: all local, zero external services ---
    backend = ConversationSQLiteBackend(
        path=str(OUTPUT_DIR / "artifacts.db")
    )
    await backend.initialize()
    artifact_store = ArtifactStore(backend, build_overflow_store())
    recipe_store = FileRecipeStore(OUTPUT_DIR / "recipes")

    # --- Sample data ---
    sales_df = _build_sales_data()
    print(f"Sample data: {len(sales_df)} rows × {len(sales_df.columns)} cols")
    print(sales_df.to_string(index=False, max_rows=6))

    # --- Run demos ---
    await demo_tier1(sales_df, artifact_store)
    await demo_tier2(sales_df, artifact_store, recipe_store)

    print("\n" + "=" * 64)
    print("  Done.  Output → artifacts/simple_infographic/")
    print("=" * 64)


def _serve_and_open(directory: Path, port: int = 8090) -> None:
    """Start a local HTTP server and open the tier-2 dashboard in the browser.

    The A2UI ``interactive-html`` renderer embeds Chart.js and interactive
    scripts that **require HTTP serving** — opening them as ``file://``
    triggers the browser's same-origin policy, breaking canvas rendering
    and sortable-table scripts.
    """
    os.chdir(directory)
    handler = http.server.SimpleHTTPRequestHandler
    # Allow port reuse so re-runs don't fail with "address already in use".
    socketserver.TCPServer.allow_reuse_address = True

    try:
        httpd = socketserver.TCPServer(("", port), handler)
    except OSError as exc:
        print(f"  ⚠ Could not bind port {port}: {exc}")
        print(f"    Serve manually: cd {directory} && python -m http.server")
        return

    url = f"http://localhost:{port}/tier2_sales_dashboard.html"
    print(f"\n  🌐 Serving at {url}")
    print("     Press Ctrl+C to stop.\n")

    # Open the browser after a short delay so the server is ready.
    threading.Timer(0.5, webbrowser.open, args=(url,)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Simple InfographicToolkit + A2UI example",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="After generating, start a local HTTP server and open "
             "the tier-2 dashboard in the browser.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8090,
        help="Port for the local HTTP server (default: 8090).",
    )
    args = parser.parse_args()

    asyncio.run(main())

    if args.serve:
        _serve_and_open(OUTPUT_DIR, port=args.port)
    else:
        print("\n  💡 Tip: run with --serve to view the A2UI dashboard")
        print("     in the browser (required for Chart.js / interactive features).")

    # Safety: some parrot subsystems (TF-based injection classifier, navconfig
    # bootstrap) may leave non-daemon threads alive.  ``injection_detection=
    # False`` skips the classifier, but flush + _exit is a belt-and-suspenders
    # guard copied from ``budget_variance_infographic.py``.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
