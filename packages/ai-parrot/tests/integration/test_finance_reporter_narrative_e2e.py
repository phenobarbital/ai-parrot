"""End-to-end integration tests for FEAT-420 (Module 8): FinanceReporter's
A2UI + narrative path.

Proves the feature's headline claims end-to-end (pipeline-wide properties a
unit test cannot establish):

- ``test_publish_recipe_succeeds_not_gapreport`` — **G-A**.
- ``test_report_profile_replay_no_narrator`` /
  ``test_report_profile_replay_with_narrator`` — **G-E**: a no-narrator
  replay renders successfully with narrative elements ABSENT; an injected
  narrator's prose appears.
- ``test_dashboard_profile_replay`` — the Infographic profile renders
  KPI/table content from the registered transformers, no hand-rolled
  aggregation (**G-B**).
- ``test_interactive_html_renders_report_root`` — regression lock on the
  verified renderer behaviour this feature depends on.
- ``test_scheduled_refresh_with_narrator`` /
  ``test_scheduled_refresh_without_system_account_fails_closed`` — the
  scheduled-refresh path narrates fresh data and still fails closed without
  a provisioned system account.
- ``test_end_to_end_no_fabricated_figures`` — **G-H**: an invented figure
  discards ALL prose, not just the offending sentence.

Uses an in-memory dataset (alias ``"snapshots"``, matching
``FinanceReporter.FINANCE_DATASET``) instead of a live
``troc.finance_projection`` — mirrors
``tests/integration/infographic_recipes/test_e2e.py``'s established fixture
approach (TASK-2196's own Codebase Contract: a live DB is explicitly NOT
required). No live LLM call anywhere — a deterministic fake ``Narrator``
throughout.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import pytest

import parrot.outputs.a2ui_renderers.interactive_html  # noqa: F401

_REPO_ROOT = Path(__file__).resolve().parents[4]

from parrot.auth.exceptions import SystemAccountNotProvisioned
from parrot.auth.permission import build_principal_context
from parrot.auth.system_account import (  # noqa: E402
    SystemAccount,
    resolve_system_account_context,
    run_scheduled_refresh,
)
from parrot.outputs.a2ui.recipes.store import FileRecipeStore  # noqa: E402
from parrot.storage.artifacts import ArtifactStore  # noqa: E402
from parrot.storage.backends import build_overflow_store  # noqa: E402
from parrot.storage.backends.sqlite import ConversationSQLiteBackend  # noqa: E402
from parrot.tools.infographic_recipes.figure_guard import figures_are_derivable  # noqa: E402
from parrot.tools.infographic_recipes.runner import RecipeRunner  # noqa: E402
from parrot.tools.infographic_sections import GapReport  # noqa: E402

pytestmark = pytest.mark.asyncio


def _load_finance_reporter():
    """Load `agents.finance_reporter` directly by file path.

    Some `parrot` submodule imports above trigger a settings bootstrap
    (`navconfig.conf`) that `os.chdir()`s to wherever `navconfig` resolves
    `BASE_DIR`, which can make a plain `import agents.finance_reporter`
    resolve inconsistently when tests run from a git worktree — the same
    technique `tests/unit/conftest.py`'s `_load_module` helper uses for an
    analogous worktree-vs-main-repo import problem.
    """
    module_name = "agents.finance_reporter"
    if module_name in sys.modules:
        return sys.modules[module_name]
    path = _REPO_ROOT / "agents" / "finance_reporter.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


_finance_reporter_module = _load_finance_reporter()
FinanceReporter = _finance_reporter_module.FinanceReporter
FINANCE_DATASET = _finance_reporter_module.FINANCE_DATASET


# ---------------------------------------------------------------------------
# Fixture data — 3 snapshots x 2 divisions x 3 projects, exercising:
#   - Retail/Alpha materially negative (< -5000) at every snapshot, and
#     Retail's ONLY project -> division net negative -> "concentrated"
#   - Wholesale/Gamma materially negative but Wholesale/Beta offsets it,
#     division net positive -> "offset_by"
#   - Wholesale/Gamma absent at the FIRST snapshot -> trend is None
# Mirrors the branch coverage of TASK-2186's unit fixture.
# ---------------------------------------------------------------------------
_COLUMNS = [
    "snapshot_date", "division", "project",
    "rev_actual", "rev_budget", "ebitda_actual", "ebitda_budget",
]
_ROWS = [
    ("2026-07-01", "Retail", "Alpha", 100000.0, 110000.0, 10000.0, 20000.0),
    ("2026-07-01", "Wholesale", "Beta", 200000.0, 190000.0, 50000.0, 40000.0),
    ("2026-07-15", "Retail", "Alpha", 98000.0, 110000.0, 8000.0, 20000.0),
    ("2026-07-15", "Wholesale", "Beta", 205000.0, 190000.0, 52000.0, 40000.0),
    ("2026-07-22", "Retail", "Alpha", 95000.0, 110000.0, 5000.0, 20000.0),
    ("2026-07-22", "Wholesale", "Beta", 210000.0, 190000.0, 55000.0, 40000.0),
    # Gamma is NEW at the latest snapshot only -> trend is None for it.
    ("2026-07-22", "Wholesale", "Gamma", 20000.0, 25000.0, 3000.0, 10000.0),
]


def _snapshots_frame() -> pd.DataFrame:
    return pd.DataFrame(_ROWS, columns=_COLUMNS)


class _FakeNarrator:
    """Deterministic narrator — no LLM. Variants drive the two safety tests.

    Applies the figure guard itself, exactly as `NarrativeMixin` does — the
    `Narrator` protocol assigns guard enforcement to the IMPLEMENTATION
    (spec §2 Overview / TASK-2192), not to `RecipeRunner`
    (`_apply_narrative_best_effort` trusts whatever the narrator returns).
    A bare stub that skips this step would not exercise criterion G-H at
    all — it would just always emit the fixed prose regardless of the
    facts, defeating `test_end_to_end_no_fabricated_figures`'s purpose.
    """

    def __init__(self, prose: Optional[str]):
        self._prose = prose
        self.calls: list[tuple[dict[str, Any], str]] = []

    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]:
        self.calls.append((facts, skill))
        if not self._prose:
            return None
        ok, _offending = figures_are_derivable(self._prose, facts)
        if not ok:
            return None
        return self._prose


# No figures at all -> figures_are_derivable trivially passes regardless of
# the real facts content (this fixture's numbers are irrelevant to it).
DERIVABLE = "Revenue is behind budget and the gap is narrowing."
# A figure absent from ANY fact -> the guard discards the WHOLE narrative.
INVENTED = "Revenue is behind budget; a further $999.9M evaporated."


@pytest.fixture
async def recipe_store(tmp_path):
    return FileRecipeStore(tmp_path / "recipes")


@pytest.fixture
async def wired_agent(tmp_path, recipe_store):
    """A configured FinanceReporter with an IN-MEMORY dataset registered."""
    backend = ConversationSQLiteBackend(path=str(tmp_path / "artifacts.db"))
    await backend.initialize()
    artifact_store = ArtifactStore(backend, build_overflow_store())
    agent = FinanceReporter(
        name="finance-reporter-test",
        artifact_store=artifact_store,
        recipe_store=recipe_store,
        injection_detection=False,
    )
    # Bypass register_datasets() (a live troc.finance_projection Postgres
    # table) — register the SAME alias ("snapshots") as an in-memory frame,
    # per TASK-2196's own Codebase Contract guidance.
    await agent._dataset_manager.add_dataset(
        name=FINANCE_DATASET, dataframe=_snapshots_frame()
    )
    return agent


@pytest.fixture
def pctx():
    """A real PermissionContext — never None (runner.py fails open on falsy)."""
    return build_principal_context("finance-reporter-test", channel="test")


@pytest.fixture
async def published_report_recipe(wired_agent, recipe_store):
    return await wired_agent.publish_recipe(
        FinanceReporter.REPORT_RECIPE_NAME,
        FinanceReporter.report_descriptor(),
        overwrite=True,
    )


@pytest.fixture
async def published_dashboard_recipe(wired_agent, recipe_store):
    return await wired_agent.publish_recipe(
        FinanceReporter.DASHBOARD_RECIPE_NAME,
        FinanceReporter.dashboard_descriptor(),
        overwrite=True,
    )


class TestFinanceReporterNarrativeE2E:
    async def test_publish_recipe_succeeds_not_gapreport(self, published_report_recipe):
        """G-A."""
        assert not isinstance(published_report_recipe, GapReport)
        assert {t.transformer for t in published_report_recipe.transforms} == {
            "variance_analysis", "top_movers", "division_breakdown", "narrative_facts",
        }

    async def test_published_recipe_carries_replay_sql(self, published_report_recipe):
        """The REAL dataset is a TableSource — it rejects a fetch with no SQL.

        This fixture registers `snapshots` in memory (which ignores `sql`),
        so nothing else here would notice the descriptor's `dataset_sql`
        going missing — while a live replay would abort at the `data` stage.
        """
        by_alias = {ds.alias: ds for ds in published_report_recipe.data_sources}
        assert set(by_alias) == {FINANCE_DATASET}
        assert "troc.finance_projection" in (by_alias[FINANCE_DATASET].sql or "")

    async def test_report_profile_replay_no_narrator(
        self, wired_agent, recipe_store, published_report_recipe, pctx
    ):
        """G-E: no narrator -> renders, numbers present, narrative elements absent."""
        runner = RecipeRunner(recipe_store, wired_agent._dataset_manager)
        artifact = await runner.run(FinanceReporter.REPORT_RECIPE_NAME, pctx=pctx)

        html_doc = artifact.content.decode()
        assert "a2ui-body" not in html_doc
        assert "a2ui-summary" not in html_doc
        assert "a2ui-card" in html_doc  # the report still rendered

    async def test_report_profile_replay_with_narrator(
        self, wired_agent, recipe_store, published_report_recipe, pctx
    ):
        runner = RecipeRunner(
            recipe_store, wired_agent._dataset_manager, narrator=_FakeNarrator(DERIVABLE)
        )
        artifact = await runner.run(FinanceReporter.REPORT_RECIPE_NAME, pctx=pctx)

        html_doc = artifact.content.decode()
        assert "gap is narrowing" in html_doc
        assert "a2ui-body" in html_doc

    async def test_dashboard_profile_replay(
        self, wired_agent, recipe_store, published_dashboard_recipe, pctx
    ):
        """G-B: KPI/table content renders from the registered transformers."""
        runner = RecipeRunner(recipe_store, wired_agent._dataset_manager)
        artifact = await runner.run(FinanceReporter.DASHBOARD_RECIPE_NAME, pctx=pctx)

        html_doc = artifact.content.decode()
        assert 'data-variant="infographic"' in html_doc
        assert "a2ui-value" in html_doc  # KPICard(s) rendered
        assert 'data-sort-key="division"' in html_doc  # DataTable rendered

    async def test_interactive_html_renders_report_root(
        self, wired_agent, recipe_store, published_report_recipe, pctx
    ):
        """Regression lock: Report roots + per-section text already render
        (verified during spec research — no satellite change needed)."""
        runner = RecipeRunner(
            recipe_store, wired_agent._dataset_manager, narrator=_FakeNarrator(DERIVABLE)
        )
        artifact = await runner.run(FinanceReporter.REPORT_RECIPE_NAME, pctx=pctx)

        assert artifact.mime_type == "text/html"
        assert artifact.surface == "interactive-html"
        html_doc = artifact.content.decode()
        assert html_doc.startswith("<!DOCTYPE html>")
        assert "a2ui-card" in html_doc

    async def test_end_to_end_no_fabricated_figures(
        self, wired_agent, recipe_store, published_report_recipe, pctx
    ):
        """G-H: an invented figure yields ZERO prose, not a wrong number."""
        runner = RecipeRunner(
            recipe_store, wired_agent._dataset_manager, narrator=_FakeNarrator(INVENTED)
        )
        artifact = await runner.run(FinanceReporter.REPORT_RECIPE_NAME, pctx=pctx)

        html_doc = artifact.content.decode()
        assert "999.9" not in html_doc
        assert "behind budget" not in html_doc  # ALL prose discarded, not just the figure
        assert "a2ui-body" not in html_doc
        assert "a2ui-card" in html_doc  # deterministic numbers still rendered

    async def test_scheduled_refresh_with_narrator(
        self, wired_agent, recipe_store, published_report_recipe
    ):
        runner = RecipeRunner(
            recipe_store, wired_agent._dataset_manager, narrator=_FakeNarrator(DERIVABLE)
        )
        account = SystemAccount(account_id="svc-finance-reporter")
        artifact = await run_scheduled_refresh(
            runner, FinanceReporter.REPORT_RECIPE_NAME, account=account
        )
        html_doc = artifact.content.decode()
        assert "gap is narrowing" in html_doc

    async def test_scheduled_refresh_without_system_account_fails_closed(
        self, wired_agent, recipe_store, published_report_recipe, monkeypatch
    ):
        """No regression: unprovisioned system account still raises, never
        forwards a falsy pctx."""
        monkeypatch.delenv("PARROT_SYSTEM_ACCOUNT_ID", raising=False)
        runner = RecipeRunner(recipe_store, wired_agent._dataset_manager)
        with pytest.raises(SystemAccountNotProvisioned):
            await run_scheduled_refresh(runner, FinanceReporter.REPORT_RECIPE_NAME)

    async def test_resolve_system_account_context_smoke(self):
        """Sanity: an explicit account always resolves to a truthy context."""
        ctx = resolve_system_account_context(
            account=SystemAccount(account_id="svc-finance-reporter")
        )
        assert ctx
