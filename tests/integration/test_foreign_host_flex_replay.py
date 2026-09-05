"""Foreign-host replay: the FieldSync shape (FEAT-528 TASK-2873).

End-to-end proof that a host with NO ``agents`` package of its own can:
register flex's transformers via ``load_transformer_module``, register the
six dataset aliases on a ``DatasetManager`` over in-memory frames (never
querysource), read the flex recipe from ``PgRecipeStore``, and produce an
envelope — with no ``FlexDashboard`` instance anywhere in the process.

Runs the whole thing in a SUBPROCESS whose ``cwd`` has no ``agents``
directory, so the absence of a top-level ``agents`` package is genuine, not
just "not imported yet in this interpreter" — and asserts
``"agents" not in sys.modules`` INSIDE that subprocess.

Render profile note: see ``test_pg_recipe_store_replay.py``'s module
docstring — ``"ssr_html"`` sidesteps a pre-existing, unrelated
``get_a2ui_renderer`` defect for the ``"interactive-html"`` name (recorded
in this task's Completion Note, not fixed here per the task's own "no
production change" instruction).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.integration

_SCRIPT = textwrap.dedent("""
    import asyncio
    import gc
    import os
    import sys
    from datetime import UTC, datetime
    from pathlib import Path
    import importlib.util

    import pandas as pd

    REPO = Path({repo!r})
    DSN = os.environ["NAVIGATOR_PG_DSN"]


    async def main():
        from parrot.tools.infographic_recipes import load_transformer_module, RecipeRunner
        from parrot.handlers.models.recipes import PgRecipeStore
        from parrot.outputs.a2ui.recipes.models import (
            DataSourceSpec, InfographicRecipe, RenderSpec, TransformStep,
        )
        from parrot.tools.dataset_manager.tool import DatasetManager
        from parrot.auth.permission import build_principal_context

        # 1) Register flex's transformers with NO agent instantiated.
        load_transformer_module(REPO / "agents" / "flex_dashboard" / "transformers.py")

        # 2) Read FlexDashboard's classmethods by loading the agent FILE by
        #    location (production's own loading strategy) -- never
        #    `FlexDashboard(...)`.
        spec = importlib.util.spec_from_file_location(
            "flex_mod_foreign_host", REPO / "agents" / "flex_dashboard.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        FlexDashboard = mod.FlexDashboard

        # 3) Build the InfographicRecipe the way InfographicAuthoringMixin
        #    .publish_recipe does (bots/mixins/infographic_authoring.py:281-420),
        #    without instantiating the agent (its own toolkit/store wiring
        #    needs ai-parrot-visualizations + is orthogonal to this proof).
        descriptor = FlexDashboard.dashboard_descriptor()
        transform_steps = [
            TransformStep(
                transformer=section.name,
                inputs=list(section.datasets),
                params=dict(descriptor.params),
                output_key=section.target.lstrip("/"),
            )
            for section in descriptor.sections
        ]
        declared_output_keys = {{step.output_key for step in transform_steps}}
        aliases: list[str] = []
        for section in descriptor.sections:
            for alias in section.datasets:
                if alias in declared_output_keys or alias in aliases:
                    continue
                aliases.append(alias)
        data_sources = [DataSourceSpec(dataset=a, alias=a) for a in aliases]

        recipe = InfographicRecipe(
            name=FlexDashboard.DASHBOARD_RECIPE_NAME,
            title="Flex Program Dashboard",
            params=FlexDashboard.recipe_params(),
            data_sources=data_sources,
            transforms=transform_steps,
            layout=descriptor.layout,
            render=RenderSpec(profile="ssr_html"),
            section_descriptor=descriptor,
            narrative=descriptor.narrative,
            updated_at=datetime.now(UTC),
        )

        store = PgRecipeStore(DSN)
        await store.ensure_schema()
        await store.save(recipe)

        # 4) Six in-memory frames -- never querysource. Columns copied from
        #    agents/flex_dashboard/transformers.py's own requires_columns.
        dm = DatasetManager(generate_guide=False)
        dm.add_dataframe("hours", pd.DataFrame({{
            "month_start": ["2025-10-01"] * 4,
            "hours": [10.0, 20.0, 5.0, 8.0],
            "pay_code": ["Reg", "OT", "Admin Time", "Reg"],
        }}))
        dm.add_dataframe("finance", pd.DataFrame({{
            "month": ["2025-10-31"], "Payroll": [1000.0], "Revenue": [5000.0],
        }}))
        dm.add_dataframe("rep_utilization", pd.DataFrame({{
            "bop_date": ["2025-10-01"], "region": ["East"], "catagory": ["A"],
            "employees_worked": [8], "average_active": [10],
        }}))
        dm.add_dataframe("region_utilization", pd.DataFrame({{
            "BOP Date": ["2025-10-01"], "FM Region": ["East"], "Category": ["A"],
            "Employee Utilization": [0.75],
        }}))
        dm.add_dataframe("msl", pd.DataFrame({{
            "store_name": ["Store1"], "latitude": [40.0], "longitude": [-75.0],
        }}))
        dm.add_dataframe("employees", pd.DataFrame({{
            "display_name": ["Alice"], "latitude": [40.1], "longitude": [-75.1],
        }}))

        # 5) Read the recipe from Postgres and replay through RecipeRunner.
        runner = RecipeRunner(store, dm)
        pctx = build_principal_context("host-user", channel="foreign-host")
        artifact = await runner.run(
            FlexDashboard.DASHBOARD_RECIPE_NAME, pctx=pctx, include_envelope=True
        )
        envelope = artifact.metadata["source_envelope"]
        tabs = envelope["components"][0]["sections"]

        assert "agents" not in sys.modules
        assert not any(type(o).__name__ == "FlexDashboard" for o in gc.get_objects())

        db = store._get_db()
        async with await db.connection() as conn:
            await conn.execute(
                f"DELETE FROM {{store.schema}}.infographic_recipes WHERE name = $1",
                FlexDashboard.DASHBOARD_RECIPE_NAME,
            )

        print("TABS", len(tabs))
        print("OK")


    asyncio.run(main())
    """)


def test_replay_flex_recipe_from_foreign_host(tmp_path, pg_dsn):
    if not pg_dsn:
        pytest.skip("NAVIGATOR_PG_DSN not set")
    code = _SCRIPT.format(repo=str(REPO))
    env = {**__import__("os").environ, "NAVIGATOR_PG_DSN": pg_dsn}
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "TABS 5" in r.stdout and "OK" in r.stdout, r.stderr
