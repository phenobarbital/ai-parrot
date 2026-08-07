"""End-to-end FEAT-420 example: publish + replay the budget-variance recipes.

Runs the **tier-2** authoring flow of ``agents/finance_reporter.py`` (the
tier-1 data-splice path this example drove before FEAT-420 was removed —
see TASK-2194's Completion Note):

1. Instantiate ``FinanceReporter`` (``NarrativeMixin + InfographicAuthoringMixin
   + PandasAgent``) and register ``troc.finance_projection`` (alias
   ``"snapshots"``) on its ``DatasetManager``.
2. ``publish_recipe`` the ``Report`` profile (criterion G-A: this now
   SUCCEEDS — a saved :class:`InfographicRecipe`, never a ``GapReport``).
3. Replay the saved recipe TWICE via :class:`RecipeRunner`:
   - **without** a narrator — facts only, no prose (criterion G-E: a pure
     replay never fails for lack of an LLM).
   - **with** a narrator (``agent`` itself, via ``NarrativeMixin``) — the
     same numbers, plus a figure-guarded prose narrative.
4. Print both rendered artifacts' sizes side by side.

Prerequisite: ``python examples/seed_finance_projection.py`` (once).

Usage::

    source .venv/bin/activate
    ENV=prod python examples/budget_variance_infographic.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "artifacts"
WORK_DIR = OUTPUT_DIR / "infographic_store"

sys.path.insert(0, str(REPO_ROOT))  # make agents/ importable

# `ai-parrot-visualizations` ships the interactive-html renderer as a
# PEP-420-merged `parrot.outputs.a2ui_renderers` subpackage. Mirror the same
# bootstrap dance `tests/integration/infographic_recipes/test_e2e.py` uses:
# a plain sys.path insert is not enough once `parrot.outputs` is already
# imported and its `__path__` cached, so extend it directly.
_VISUALIZATIONS_SRC = REPO_ROOT / "packages" / "ai-parrot-visualizations" / "src"
if str(_VISUALIZATIONS_SRC) not in sys.path:
    sys.path.insert(0, str(_VISUALIZATIONS_SRC))

import parrot.outputs as _parrot_outputs  # noqa: E402

_vis_outputs_path = str(_VISUALIZATIONS_SRC / "parrot" / "outputs")
if _vis_outputs_path not in _parrot_outputs.__path__:
    _parrot_outputs.__path__.insert(0, _vis_outputs_path)

import parrot.outputs.a2ui_renderers.interactive_html  # noqa: F401,E402
from parrot.auth.permission import build_principal_context  # noqa: E402
from parrot.outputs.a2ui.recipes.models import RecipeRunError  # noqa: E402
from parrot.outputs.a2ui.recipes.store import FileRecipeStore  # noqa: E402
from parrot.storage.artifacts import ArtifactStore  # noqa: E402
from parrot.storage.backends import build_overflow_store  # noqa: E402
from parrot.storage.backends.sqlite import ConversationSQLiteBackend  # noqa: E402
from parrot.tools.infographic_recipes.runner import (  # noqa: E402
    RecipeRunException,
    RecipeRunner,
)
from parrot.tools.infographic_sections import GapReport  # noqa: E402


def _load_finance_reporter():
    """Load `agents.finance_reporter` directly by file path.

    Some `parrot` submodule imports above trigger a settings bootstrap
    (`navconfig.conf`) that `os.chdir()`s to wherever `navconfig` resolves
    `BASE_DIR` — which can make a plain `import agents.finance_reporter`
    resolve inconsistently. Load from this script's own known-good
    `REPO_ROOT` instead (the same technique
    `tests/unit/conftest.py`'s `_load_module` helper uses for an analogous
    worktree-vs-main-repo import problem).
    """
    import importlib.util

    module_name = "agents.finance_reporter"
    if module_name in sys.modules:
        return sys.modules[module_name]
    path = REPO_ROOT / "agents" / "finance_reporter.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


FinanceReporter = _load_finance_reporter().FinanceReporter


async def main() -> None:
    """Publish the Report recipe, then replay it with and without a narrator."""
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    recipe_store = FileRecipeStore(WORK_DIR / "recipes")

    # `InfographicAuthoringMixin` only builds its `InfographicToolkit` (and
    # therefore only exposes the wired `recipe_store` to `publish_recipe`)
    # when an `artifact_store` is ALSO supplied — see
    # `InfographicAuthoringMixin.__init__` / `_require_recipe_store`.
    backend = ConversationSQLiteBackend(path=str(WORK_DIR / "artifacts.db"))
    await backend.initialize()
    artifact_store = ArtifactStore(backend, build_overflow_store())

    # injection_detection=False skips loading the deBERTa prompt-injection
    # classifier (~1 min of TF/HF startup) — this runner drives the
    # authoring API programmatically, no conversational input reaches the bot.
    agent = FinanceReporter(
        name="finance-reporter",
        artifact_store=artifact_store,
        recipe_store=recipe_store,
        injection_detection=False,
    )
    await agent.register_datasets()

    # --- Tier 2: publishing now SUCCEEDS (criterion G-A) --------------------
    recipe = await agent.publish_recipe(
        FinanceReporter.REPORT_RECIPE_NAME,
        FinanceReporter.report_descriptor(),
        overwrite=True,
    )
    assert not isinstance(recipe, GapReport), f"publish_recipe returned a GapReport: {recipe!r}"
    print(f"published   : {recipe.name} with {len(recipe.transforms)} transform(s)")

    errors: list[RecipeRunError] = await RecipeRunner(
        recipe_store, agent._dataset_manager
    ).dry_run(recipe)
    print(f"dry_run     : {len(errors)} error(s)")
    for error in errors:
        print(f"  - [{error.stage}] {error.detail}")

    pctx = build_principal_context("finance-reporter-example", channel="script")

    # --- Replay WITHOUT a narrator: facts, no prose (criterion G-E) --------
    # --- Replay WITH a narrator: same numbers, plus figure-guarded prose ---
    #
    # KNOWN LIMITATION (discovered by actually running this example, as
    # TASK-2195 requires): `publish_recipe`'s generic SectionDescriptor path
    # builds every `DataSourceSpec` as `dataset=alias, alias=alias` with NO
    # `sql=` — but the registered `troc.finance_projection` dataset is a
    # `TableSource`, which REQUIRES an explicit SQL statement (a deliberate
    # safety guardrail against `SELECT *` on a large table). Separately,
    # `publish_recipe` also creates a bogus `DataSourceSpec` for each of
    # `narrative_facts`'s prior-step-output aliases (`variance_analysis`/
    # `top_movers`/`division_breakdown`), which are not real datasets
    # either. Both are pre-existing gaps in `publish_recipe`'s data_sources
    # construction (out of scope for `agents/finance_reporter.py` /
    # TASK-2195 — flagged in TASK-2194's Completion Note for TASK-2196,
    # the e2e task, to resolve with full test evidence). Replay therefore
    # currently fails at the fetch stage; this example demonstrates as much
    # of the flow as is functionally possible today and reports the rest
    # honestly rather than crashing.
    for label, runner in (
        ("no narrator", RecipeRunner(recipe_store, agent._dataset_manager)),
        ("narrated", RecipeRunner(recipe_store, agent._dataset_manager, narrator=agent)),
    ):
        try:
            artifact = await runner.run(recipe.name, pctx=pctx)
        except RecipeRunException as exc:
            print(f"{label:11}: BLOCKED — [{exc.error.stage}] {exc.error.detail}")
            continue
        rendered_len = len(artifact.content or b"")
        print(f"{label:11}: {rendered_len} bytes rendered")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR / f"budget_variance_report_{label.replace(' ', '_')}.html"
        out_path.write_bytes(artifact.content or b"")
        print(f"            report written to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
    # The ML stack PandasAgent pulls in (prompt-injection classifier / TF)
    # leaves non-daemon threads behind that keep the interpreter alive after
    # main() returns — force a clean exit once the reports are on disk.
    # `os._exit` skips normal interpreter teardown, which would otherwise
    # flush stdout/stderr — flush explicitly first or redirected/piped
    # output (block-buffered, unlike a TTY) is silently lost.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
