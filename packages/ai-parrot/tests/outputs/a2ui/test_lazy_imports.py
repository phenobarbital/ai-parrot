"""FEAT-668: importing core entry points must not load heavy A2UI modules."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[3] / "src"

FORBIDDEN: frozenset[str] = frozenset(
    {
        "parrot.outputs.a2ui.builders",
        "parrot.outputs.a2ui.catalog.basic",
        "parrot.outputs.a2ui.catalog.parrot",
        "parrot.outputs.a2ui.catalog.viz_core",
        "parrot.outputs.a2ui.recipes.library",
    }
)

_BUILTIN_TRANSFORMERS: frozenset[str] = frozenset(
    {
        "day_totals",
        "division_breakdown",
        "variance_analysis",
        "top_movers",
        "narrative_facts",
        "groupby_aggregate",
        "pivot",
        "latest_vs_baseline",
    }
)


def _run_probe(body: str) -> subprocess.CompletedProcess[str]:
    """Run ``body`` in a fresh interpreter with this tree's src first on sys.path."""
    probe = f"import sys\nsys.path.insert(0, {str(_SRC)!r})\n{body}"
    return subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        env=os.environ.copy(),
    )


def _loaded_after_import(module: str) -> list[str]:
    """Return the sorted subset of FORBIDDEN present after importing ``module``."""
    body = (
        "import importlib, json\n"
        f"importlib.import_module({module!r})\n"
        f"print(json.dumps(sorted(set(sys.modules) & {sorted(FORBIDDEN)!r})))\n"
    )
    result = _run_probe(body)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize(
    "module",
    [
        "parrot.bots",
        "parrot.bots.data",
        "parrot.bots.database.agent",
        "parrot.bots.mixins.narrative",
        "parrot.tools.infographic_recipes.figure_guard",
        "parrot.outputs.a2ui.artifacts",
        "parrot.outputs.a2ui.recipes",
    ],
)
def test_core_entrypoints_do_not_load_a2ui_heavy(module: str) -> None:
    """Keep core A2UI entry points independent from their heavy modules."""
    assert _loaded_after_import(module) == []


def test_registry_singleton_loads_builtins_on_first_get() -> None:
    """Load the built-in library only when the singleton first resolves a name."""
    result = _run_probe(
        "import json, sys\n"
        "from parrot.outputs.a2ui.recipes.transformers import transformer_registry\n"
        "library = 'parrot.outputs.a2ui.recipes.library'\n"
        "before = library in sys.modules\n"
        "transformer_registry.get('day_totals')\n"
        "print(json.dumps([before, library in sys.modules]))\n"
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == [False, True]


def test_registry_list_returns_all_builtins() -> None:
    """Expose every built-in transformer through the lazy registry singleton."""
    result = _run_probe(
        "from parrot.outputs.a2ui.recipes.transformers import transformer_registry\n"
        "names = {manifest.name for manifest in transformer_registry.list()}\n"
        f"expected = {sorted(_BUILTIN_TRANSFORMERS)!r}\n"
        "assert set(expected) <= names, sorted(names)\n"
    )
    assert result.returncode == 0, result.stderr


def test_infographic_recipes_lazy_attrs_resolve() -> None:
    """Resolve every documented lazy package attribute and reject unknown names."""
    import parrot.tools.infographic_recipes as recipes

    for name in recipes.__all__:
        assert getattr(recipes, name) is not None

    with pytest.raises(AttributeError):
        getattr(recipes, "does_not_exist")
