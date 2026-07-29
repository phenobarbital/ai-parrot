"""End-to-end integration tests for FEAT-324 (Module 9): the
`budget-variance-daily` example recipe running through Modules 1-8 —
DatasetManager -> RecipeRunner -> registered transformers -> A2UI envelope
-> renderer -> (optional) delivery. Fixture CSVs are synthetic, derived from
`sdd/artifacts/daily_report.py`'s compact-row format (division, project,
rev_actual, rev_budget, ebitda_actual, ebitda_budget) — the reference
artifacts themselves are gitignored/non-importable; only their row SHAPE is
reproduced here.

No pixel/screenshot assertions (no browser in CI, per spec) — structure is
asserted via the embedded dataModel JSON's key set and static HTML markers;
value changes are asserted on the dataModel's actual numbers.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd
import pytest

# This test needs ai-parrot-visualizations (the interactive-html/ssr_html
# renderers). Tests under packages/ai-parrot/ get their rootdir from
# packages/ai-parrot/pyproject.toml's [tool.pytest.ini_options] (closer than
# the worktree-root pytest.ini), so pytest's conftest collection stops there
# and never reaches the worktree-root conftest.py's ai-parrot-visualizations
# sys.path entry (added for TASK-1871). `parrot.outputs` may ALSO already be
# imported (and its `pkgutil.extend_path`-merged `__path__` cached) by the
# time this module loads, so a plain sys.path insert is not enough — extend
# the already-cached `__path__` directly. Scoped to this module rather than
# touching shared conftest files further for one test.
_VISUALIZATIONS_SRC = Path(__file__).resolve().parents[5] / "packages" / "ai-parrot-visualizations" / "src"
if str(_VISUALIZATIONS_SRC) not in sys.path:
    sys.path.insert(0, str(_VISUALIZATIONS_SRC))

import parrot.outputs as _parrot_outputs  # noqa: E402

_vis_outputs_path = str(_VISUALIZATIONS_SRC / "parrot" / "outputs")
if _vis_outputs_path not in _parrot_outputs.__path__:
    # INSERT at position 0 (not append): `a2ui_renderers` is a REGULAR
    # subpackage (its own __init__.py, not a namespace package) shipped by
    # BOTH the main-repo editable install and this worktree — Python's
    # import system resolves it from the FIRST matching directory in
    # `__path__` and never looks further, so the worktree's copy must come
    # first or it is silently shadowed by the main-repo one.
    _parrot_outputs.__path__.insert(0, _vis_outputs_path)

# Ensure the satellite's renderers self-register (interactive-html, ssr_html).
import parrot.outputs.a2ui_renderers.interactive_html  # noqa: F401,E402
import parrot.outputs.a2ui_renderers.ssr_html  # noqa: F401,E402
from parrot.outputs.a2ui.builders import build_infographic  # noqa: E402
from parrot.outputs.a2ui.recipes import InfographicRecipe  # noqa: E402
from parrot.outputs.a2ui.recipes.store import FileRecipeStore  # noqa: E402
from parrot.tools.dataset_manager.tool import DatasetManager  # noqa: E402
from parrot.tools.infographic_recipes.freeze import freeze_session_envelope  # noqa: E402
from parrot.tools.infographic_recipes.runner import RecipeRunner  # noqa: E402

pytestmark = pytest.mark.asyncio

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_EXAMPLE_RECIPE_PATH = (
    Path(__file__).resolve().parents[5] / "examples" / "infographic_recipes" / "budget-variance-daily.yaml"
)
_DATASET_NAME = "in_month_projections"


def _load_combined_frame(rows_override: dict[str, list[dict]] | None = None) -> pd.DataFrame:
    """Load the 3 fixture CSVs into one frame with a `snapshot` column.

    Args:
        rows_override: Optional ``{snapshot_date: [row dicts]}`` replacing a
            given day's rows entirely (used by the re-run/updated-data test).
    """
    frames = []
    for path in sorted(_FIXTURES_DIR.glob("snapshot_*.csv")):
        date_str = path.stem.replace("snapshot_", "")
        if rows_override and date_str in rows_override:
            df = pd.DataFrame(rows_override[date_str])
        else:
            df = pd.read_csv(path)
        df["snapshot"] = date_str
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


async def _make_dataset_manager(rows_override=None) -> DatasetManager:
    dm = DatasetManager()
    await dm.add_dataset(name=_DATASET_NAME, dataframe=_load_combined_frame(rows_override))
    return dm


def _load_example_recipe() -> InfographicRecipe:
    return InfographicRecipe.from_yaml(_EXAMPLE_RECIPE_PATH.read_text())


def _extract_data_model(html_doc: str) -> dict:
    match = re.search(
        r'<script type="application/json" id="report-data">(.*?)</script>', html_doc, re.DOTALL
    )
    assert match is not None, "report-data script block not found in rendered HTML"
    return json.loads(match.group(1))


@pytest.fixture
def recipe_store(tmp_path):
    return FileRecipeStore(tmp_path)


class TestBudgetVarianceE2E:
    async def test_e2e_budget_variance_recipe(self, recipe_store):
        """Fixtures -> DatasetManager -> recipe -> interactive HTML RenderedArtifact."""
        dm = await _make_dataset_manager()
        recipe = _load_example_recipe()
        await recipe_store.save(recipe)

        runner = RecipeRunner(recipe_store, dm)
        errors = await runner.dry_run(recipe)
        assert errors == []

        artifact = await runner.run(recipe.name)

        assert artifact.mime_type == "text/html"
        assert artifact.surface == "interactive-html"
        html_doc = artifact.content.decode()
        assert html_doc.startswith("<!DOCTYPE html>")

        data_model = _extract_data_model(html_doc)
        assert {"day_totals", "division_breakdown", "variance_analysis", "top_movers", "chart_data"} <= set(
            data_model
        )
        # Sanity: the latest snapshot's revenue total matches the fixture data.
        assert data_model["variance_analysis"]["last_totals"]["rev_actual"] == pytest.approx(
            120000 + 55000 + 32000 + 10000 + 5000
        )

    async def test_rerun_updates_values_keeps_structure(self, recipe_store):
        """Re-running with changed fixture data yields updated numbers, identical structure."""
        dm = await _make_dataset_manager()
        recipe = _load_example_recipe()
        await recipe_store.save(recipe)
        runner = RecipeRunner(recipe_store, dm)

        artifact_1 = await runner.run(recipe.name)
        data_model_1 = _extract_data_model(artifact_1.content.decode())

        # Change the LATEST snapshot's numbers (simulates "today's" fresh data).
        changed_rows = {
            "2026-07-22": [
                {"division": "Sales", "project": "Alpha", "rev_actual": 999000, "rev_budget": 110000,
                 "ebitda_actual": 999000, "ebitda_budget": 22000},
                {"division": "Sales", "project": "Beta", "rev_actual": 55000, "rev_budget": 70000,
                 "ebitda_actual": 4000, "ebitda_budget": 9000},
                {"division": "Ops", "project": "Gamma", "rev_actual": 32000, "rev_budget": 31000,
                 "ebitda_actual": 4500, "ebitda_budget": 4200},
                {"division": "Ops", "project": "Delta", "rev_actual": 10000, "rev_budget": 12000,
                 "ebitda_actual": -1000, "ebitda_budget": 500},
                {"division": "Marketing", "project": "Epsilon", "rev_actual": 5000, "rev_budget": 5000,
                 "ebitda_actual": 500, "ebitda_budget": 500},
            ]
        }
        dm2 = await _make_dataset_manager(rows_override=changed_rows)
        runner2 = RecipeRunner(recipe_store, dm2)
        artifact_2 = await runner2.run(recipe.name)
        data_model_2 = _extract_data_model(artifact_2.content.decode())

        # Identical STRUCTURE: same top-level dataModel keys, same layout markers.
        assert set(data_model_1) == set(data_model_2)
        html_1, html_2 = artifact_1.content.decode(), artifact_2.content.decode()
        for marker in ("data-chart-config=", "data-sort-table", "Daily Budget Variance"):
            assert marker in html_1 and marker in html_2

        # Updated VALUES: the latest snapshot's revenue total changed.
        assert (
            data_model_1["variance_analysis"]["last_totals"]["rev_actual"]
            != data_model_2["variance_analysis"]["last_totals"]["rev_actual"]
        )
        assert data_model_2["variance_analysis"]["last_totals"]["rev_actual"] == pytest.approx(
            999000 + 55000 + 32000 + 10000 + 5000
        )

    async def test_e2e_freeze_then_replay(self, recipe_store):
        """A simulated session envelope -> freeze -> replay produces an equivalent
        envelope without the LLM."""
        dm = await _make_dataset_manager()
        runner = RecipeRunner(recipe_store, dm)

        # Simulated live-session envelope (as an LLM would have produced via
        # infographic_render/build_infographic during a chat turn).
        envelope = build_infographic(
            title="Daily Budget Variance (session draft)",
            sections=[
                {
                    "heading": "Snapshot",
                    "components": [
                        {
                            "component": "KPICard",
                            "properties": {
                                "label": "Revenue (latest)",
                                "value": {"$bind": "/variance_analysis/last_totals/rev_actual"},
                            },
                        }
                    ],
                }
            ],
        )

        frozen = await freeze_session_envelope(
            envelope,
            dataset_names={"snapshots": _DATASET_NAME},
            transform_steps=[
                {
                    "transformer": "variance_analysis",
                    "inputs": ["snapshots"],
                    "params": {"snapshot_col": "snapshot"},
                    "output_key": "variance_analysis",
                }
            ],
            name="frozen-budget-variance",
            title="Frozen Budget Variance",
            runner=runner,
            render_profile="interactive-html",
        )
        await recipe_store.save(frozen)

        # Replay TWICE from the store — deterministic, no LLM involved.
        replay_1 = await runner.run(frozen.name)
        replay_2 = await runner.run(frozen.name)

        assert replay_1.mime_type == replay_2.mime_type == "text/html"
        data_model_1 = _extract_data_model(replay_1.content.decode())
        data_model_2 = _extract_data_model(replay_2.content.decode())
        assert data_model_1 == data_model_2  # same store, same data -> byte-identical dataModel

    async def test_e2e_static_profile_delivery(self, recipe_store):
        """Same recipe rendered via the static ssr_html profile -> deliver_artifact
        (mock notification provider)."""
        dm = await _make_dataset_manager()
        recipe = _load_example_recipe()
        recipe = recipe.model_copy(
            update={
                "render": recipe.render.model_copy(
                    update={
                        "profile": "ssr_html",
                        "delivery": {"recipients": ["ops@example.com"], "provider": "email"},
                    }
                )
            }
        )
        await recipe_store.save(recipe)

        fake_owner = SimpleNamespace(send_notification=AsyncMock(return_value={"status": "sent"}))
        runner = RecipeRunner(recipe_store, dm, owner=fake_owner)

        artifact = await runner.run(recipe.name)

        assert artifact.mime_type == "text/html"
        assert artifact.surface == "ssr_html"
        fake_owner.send_notification.assert_awaited_once()
        call_args, call_kwargs = fake_owner.send_notification.call_args
        # deliver_artifact calls send_notification(message, recipients, ...) positionally.
        recipients = call_kwargs.get("recipients", call_args[1] if len(call_args) > 1 else None)
        assert recipients == ["ops@example.com"]
