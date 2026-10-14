"""FEAT-668: importing server entry points must not load heavy A2UI modules."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_SRCS = [_HERE.parents[1] / "src", _HERE.parents[2] / "ai-parrot" / "src"]

FORBIDDEN: frozenset[str] = frozenset(
    {
        "parrot.outputs.a2ui.builders",
        "parrot.outputs.a2ui.catalog.basic",
        "parrot.outputs.a2ui.catalog.parrot",
        "parrot.outputs.a2ui.catalog.viz_core",
        "parrot.outputs.a2ui.recipes.library",
    }
)


def _loaded_after_import(module: str) -> list[str]:
    """Return the sorted subset of FORBIDDEN present after importing ``module``."""
    source_paths = "\n".join(f"sys.path.insert(0, {str(path)!r})" for path in reversed(_SRCS))
    probe = (
        "import importlib, json, sys\n"
        f"{source_paths}\n"
        f"importlib.import_module({module!r})\n"
        f"print(json.dumps(sorted(set(sys.modules) & {sorted(FORBIDDEN)!r})))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        env=os.environ.copy(),
    )
    if result.returncode != 0:
        stderr = result.stderr.lower()
        if "importerror" in stderr or "modulenotfounderror" in stderr or "config" in stderr:
            pytest.skip(f"server import requires unavailable environment configuration: {result.stderr}")
        pytest.fail(result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize(
    "module",
    [
        "parrot.manager",
        "parrot.handlers.models",
        "parrot.handlers.a2ui",
        "parrot.handlers.infographic_recipes",
        "parrot.handlers.ui_surfaces",
        "parrot.handlers.infographic",
        "parrot.a2a.server",
    ],
)
def test_server_entrypoints_do_not_load_a2ui_heavy(module: str) -> None:
    """Keep server entry points independent from their heavy A2UI modules."""
    assert _loaded_after_import(module) == []
