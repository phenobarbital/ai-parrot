"""End-to-end integration tests for FEAT-326 (Module 6): DataAgent Infographic.

Proves the whole feature on the real budget-variance use case:

- ``test_e2e_budget_variance_one_shot`` — sample CSVs → DatasetManager → tier-1
  ``generate_infographic`` (data-splice) → HTML persisted to local disk with the
  ``{"days": {...}}`` payload spliced into the ``report-data`` marker.
- ``test_e2e_publish_and_replay`` — tier-2 ``publish_recipe`` → ``RecipeRunner.run``
  under the system-account principal reproduces the artifact with fresh data.
- ``test_e2e_delivery_config`` — a published recipe carries ``RenderSpec.delivery``
  and replay reaches the delivery path (mock notification provider).

Plus ``TestDomainTransformers`` — the finance transformers ``day_totals`` /
``division_breakdown`` (already registered by FEAT-324's ``recipes.library`` —
ported there from ``sdd/artifacts/executive_summary.py``) are resolvable by name
and match the reference math.
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

# ---------------------------------------------------------------------------
# Renderer registration (interactive-html) — same boilerplate as FEAT-324's
# tests/integration/infographic_recipes/test_e2e.py: the ai-parrot-visualizations
# satellite must self-register its renderers, and its parrot.outputs subpackage
# must be merged into the already-cached namespace __path__.
# ---------------------------------------------------------------------------
_VISUALIZATIONS_SRC = (
    Path(__file__).resolve().parents[4] / "packages" / "ai-parrot-visualizations" / "src"
)
if str(_VISUALIZATIONS_SRC) not in sys.path:
    sys.path.insert(0, str(_VISUALIZATIONS_SRC))

import parrot.outputs as _parrot_outputs  # noqa: E402

_vis_outputs_path = str(_VISUALIZATIONS_SRC / "parrot" / "outputs")
if _vis_outputs_path not in _parrot_outputs.__path__:
    _parrot_outputs.__path__.insert(0, _vis_outputs_path)

import parrot.outputs.a2ui_renderers.interactive_html  # noqa: F401,E402

from parrot.bots.data import PandasAgent  # noqa: E402
from parrot.bots.mixins import InfographicAuthoringMixin  # noqa: E402
from parrot.outputs.a2ui.recipes import library as _recipe_library  # noqa: F401,E402
from parrot.outputs.a2ui.recipes.store import FileRecipeStore  # noqa: E402
from parrot.outputs.a2ui.recipes.transformers import transformer_registry  # noqa: E402
from parrot.storage.artifacts import ArtifactStore  # noqa: E402
from parrot.storage.backends import build_overflow_store  # noqa: E402
from parrot.storage.backends.sqlite import ConversationSQLiteBackend  # noqa: E402
from parrot.tools.dataset_manager.tool import DatasetManager  # noqa: E402
from parrot.tools.infographic_recipes.runner import RecipeRunner  # noqa: E402
from parrot.tools.infographic_sections import SectionDescriptor, SectionSpec  # noqa: E402
from parrot.auth.system_account import (  # noqa: E402
    SystemAccount,
    resolve_system_account_context,
)

pytestmark = pytest.mark.asyncio

_MONEY_COLS = ["rev_actual", "rev_budget", "ebitda_actual", "ebitda_budget"]
_CSV_COLS = ["division", "project", *_MONEY_COLS]

# Three synthetic snapshots (first-of-month, yesterday, today) — compact
# 6-column shape daily_report.py produces.
_SNAPSHOTS = {
    "20260701": [
        ["North", "P1", 100000, 90000, 20000, 18000],
        ["South", "P2", 50000, 55000, 8000, 9000],
    ],
    "20260721": [
        ["North", "P1", 110000, 90000, 22000, 18000],
        ["South", "P2", 52000, 55000, 8500, 9000],
    ],
    "20260722": [
        ["North", "P1", 120000, 90000, 25000, 18000],
        ["South", "P2", 55000, 55000, 9000, 9000],
    ],
}


class _AuthoringAgent(InfographicAuthoringMixin, PandasAgent):
    pass


class _MixinHolder(InfographicAuthoringMixin):
    """Lightweight publish-only holder (avoids the heavy PandasAgent init)."""

    def __init__(self, dm, recipe_store):
        import logging
        self._dataset_manager = dm
        self._infographic_toolkit = SimpleNamespace(_recipe_store=recipe_store)
        self.logger = logging.getLogger("test.mixin_holder")


def _combined_frame() -> pd.DataFrame:
    frames = []
    for date_str, rows in _SNAPSHOTS.items():
        df = pd.DataFrame(rows, columns=_CSV_COLS)
        df["snapshot"] = date_str
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def _extract_report_data(html_doc: str) -> dict:
    match = re.search(
        r'<script type="application/json" id="report-data">(.*?)</script>',
        html_doc, re.DOTALL,
    )
    assert match is not None, "report-data script block not found"
    return json.loads(match.group(1))


# ---------------------------------------------------------------------------
# Domain transformers
# ---------------------------------------------------------------------------

class TestDomainTransformers:
    def test_registered_by_name(self):
        assert transformer_registry.get("day_totals") is not None
        assert transformer_registry.get("division_breakdown") is not None

    def test_day_totals_matches_reference_math(self):
        fn = transformer_registry.get("day_totals").func
        frame = pd.DataFrame(_SNAPSHOTS["20260722"], columns=_CSV_COLS)
        out = fn({"snapshots": frame}, {})  # no snapshot col → single record
        # rev_actual = 120000 + 55000; rev_budget = 90000 + 55000
        assert out["rev_actual"] == pytest.approx(175000)
        assert out["rev_budget"] == pytest.approx(145000)
        assert out["rev_variance"] == pytest.approx(30000)
        assert out["ebitda_variance"] == pytest.approx((25000 + 9000) - (18000 + 9000))

    def test_division_breakdown_matches_reference_math(self):
        fn = transformer_registry.get("division_breakdown").func
        frame = pd.DataFrame(_SNAPSHOTS["20260722"], columns=_CSV_COLS)
        out = fn({"snapshots": frame}, {})
        assert set(out) == {"North", "South"}
        assert out["North"]["rev_variance"] == pytest.approx(120000 - 90000)
        assert out["North"]["projects"][0]["name"] == "P1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def budget_variance_template_dir(tmp_path):
    """Provide a self-contained data-splice template in a tmp ``template_dirs`` root.

    The reference ``sdd/artifacts/budget_variance_dashboard_Template.html`` is
    gitignored (``.gitignore``: ``artifacts/``) — absent from worktrees and CI —
    so this synthesizes an equivalent compact template carrying the same
    ``<script type="application/json" id="report-data">`` marker the real
    dashboard uses. (The >200 KB offload-to-disk behavior of the real 259 KB
    template is proven deterministically by ``test_local_overflow_roundtrip``.)
    """
    dst = tmp_path / "templates"
    dst.mkdir()
    html = (
        "<!doctype html><html><head><title>Budget Variance</title></head>"
        "<body><h1>Budget Variance</h1>"
        '<script type="application/json" id="report-data">\n{}\n</script>'
        "<div id='app'></div></body></html>"
    )
    (dst / "budget_variance.html").write_text(html, encoding="utf-8")
    return dst


@pytest.fixture
def local_artifact_store(tmp_path, monkeypatch):
    """ArtifactStore over ConversationSQLiteBackend + local-filesystem overflow."""
    overflow_dir = tmp_path / "overflow"
    monkeypatch.setenv("PARROT_OVERFLOW_STORE", "local")
    monkeypatch.setenv("PARROT_OVERFLOW_LOCAL_PATH", str(overflow_dir))
    backend = ConversationSQLiteBackend(path=str(tmp_path / "conv.db"))
    overflow = build_overflow_store()
    store = ArtifactStore(backend, overflow)
    return SimpleNamespace(store=store, backend=backend, overflow_dir=overflow_dir)


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------

class TestBudgetVarianceE2E:
    async def test_e2e_budget_variance_one_shot(
        self, budget_variance_template_dir, local_artifact_store,
    ):
        await local_artifact_store.backend.initialize()
        agent = _AuthoringAgent(
            name="reporter",
            artifact_store=local_artifact_store.store,
            template_dirs=[str(budget_variance_template_dir)],
        )
        await agent._dataset_manager.add_dataset(
            name="snapshots", dataframe=_combined_frame()
        )

        # The exact client-side payload shape the template consumes.
        payload = {"days": {date: rows for date, rows in _SNAPSHOTS.items()}}

        async def _build(descriptor, params):
            return payload, {"snapshots": "2026-07-22T00:00:00+00:00"}

        agent._build_section_payload = _build  # scripted build (no live LLM)

        descriptor = SectionDescriptor(
            template="budget_variance.html",
            mode="data-splice",
            splice_marker_id="report-data",
            sections=[
                SectionSpec(name="days", target="/days", datasets=["snapshots"],
                            shape="mapping"),
            ],
        )
        result, provenance = await agent.generate_infographic(
            "budget_variance.html", descriptor
        )

        assert result.artifact_id
        assert provenance.tier == "one-shot"
        assert not any("code" in f or "source" in f for f in provenance.model_dump())

        # The data-splice render produced the payload inside the report-data
        # marker (compact template → returned inline on the result envelope).
        assert result.html_inline is not None
        spliced = _extract_report_data(result.html_inline)
        assert set(spliced["days"]) == set(_SNAPSHOTS)  # {"days": {date: rows}}
        assert spliced["days"]["20260722"] == _SNAPSHOTS["20260722"]

        # Persisted to the on-disk store (SQLite backend + local overflow) and
        # retrievable from disk with the spliced payload intact.
        user_id, agent_id, session_id = agent._infographic_toolkit._resolve_scope(agent)
        stored = await local_artifact_store.store.get_artifact(
            user_id, agent_id, session_id, result.artifact_id
        )
        assert _extract_report_data(stored.definition["html"])["days"]["20260722"] == \
            _SNAPSHOTS["20260722"]
        assert Path(local_artifact_store.backend._path).exists()  # SQLite DB on disk

    async def test_e2e_publish_and_replay(self, tmp_path):
        dm = DatasetManager()
        await dm.add_dataset(name="snapshots", dataframe=_combined_frame())
        store = FileRecipeStore(tmp_path / "recipes")
        holder = _MixinHolder(dm, store)

        descriptor = SectionDescriptor(
            template="budget_variance.html",
            mode="data-splice",
            sections=[
                SectionSpec(name="day_totals", target="/day_totals",
                            datasets=["snapshots"], shape="mapping"),
                SectionSpec(name="division_breakdown", target="/division_breakdown",
                            datasets=["snapshots"], shape="mapping"),
            ],
            params={"snapshot_col": "snapshot"},
        )
        recipe = await holder.publish_recipe("budget_daily", descriptor)
        assert {s.transformer for s in recipe.transforms} == {
            "day_totals", "division_breakdown"
        }

        # Replay under the system-account principal (never a falsy pctx).
        pctx = resolve_system_account_context(account=SystemAccount(account_id="svc-reports"))
        runner = RecipeRunner(store, dm)
        artifact = await runner.run("budget_daily", pctx=pctx)

        assert artifact.mime_type == "text/html"
        data_model = _extract_report_data(artifact.content.decode())
        assert "day_totals" in data_model
        assert "division_breakdown" in data_model
        # Fresh data reflected: latest snapshot North rev_actual = 120000.
        assert data_model["division_breakdown"]["North"]["rev_actual"] == pytest.approx(120000)

    async def test_e2e_delivery_config(self, tmp_path):
        dm = DatasetManager()
        await dm.add_dataset(name="snapshots", dataframe=_combined_frame())
        store = FileRecipeStore(tmp_path / "recipes")
        holder = _MixinHolder(dm, store)

        delivery = {"recipients": ["ops@example.com"], "provider": "email"}
        descriptor = SectionDescriptor(
            template="budget_variance.html",
            mode="data-splice",
            sections=[
                SectionSpec(name="day_totals", target="/day_totals",
                            datasets=["snapshots"], shape="mapping"),
            ],
            params={"snapshot_col": "snapshot"},
        )
        recipe = await holder.publish_recipe(
            "budget_delivery", descriptor, delivery=delivery
        )
        assert recipe.render.delivery == delivery

        fake_owner = SimpleNamespace(
            send_notification=AsyncMock(return_value={"status": "sent"})
        )
        pctx = resolve_system_account_context(account=SystemAccount(account_id="svc-reports"))
        runner = RecipeRunner(store, dm, owner=fake_owner)
        await runner.run("budget_delivery", pctx=pctx)

        fake_owner.send_notification.assert_awaited_once()
        call_args, call_kwargs = fake_owner.send_notification.call_args
        recipients = call_kwargs.get(
            "recipients", call_args[1] if len(call_args) > 1 else None
        )
        assert recipients == ["ops@example.com"]
