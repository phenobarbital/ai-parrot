"""Import-boundary guard for ``wikitoolkit`` and the ``parrot.bots`` eager surface.

``pip install ai-parrot[wiki,mcp]`` (no ai-parrot-server, no ai-parrot-tools)
must be enough to run ``wikitoolkit``. These tests run a fresh interpreter with
both satellite distributions blocked on ``sys.meta_path`` and assert that the
CLI entry point imports, and that the base ``parrot.bots`` hierarchy never
drags the concrete agents in eagerly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[5]
_SERVER_SRC = _REPO / "packages" / "ai-parrot-server" / "src"
_TOOLS_SRC = _REPO / "packages" / "ai-parrot-tools" / "src"

_PROBE = r"""
import importlib, importlib.machinery, json, sys, traceback
BLOCK = tuple(json.loads(sys.argv[1]))
class Boundary(importlib.machinery.PathFinder):
    @classmethod
    def find_spec(cls, name, path=None, target=None):
        if not name.startswith("parrot"):
            return None
        spec = super().find_spec(name, path, target)
        if spec is None:
            return None
        origin = spec.origin or ""
        locs = list(spec.submodule_search_locations or [])
        blocked = any(b in origin for b in BLOCK) or (
            not spec.has_location and locs and all(any(b in l for b in BLOCK) for l in locs)
        )
        if blocked:
            raise ModuleNotFoundError(f"No module named {name!r} (satellite blocked)", name=name)
        return None
sys.meta_path.insert(0, Boundary)
result = {"errors": {}}
for mod in json.loads(sys.argv[2]):
    try:
        importlib.import_module(mod)
    except Exception as exc:  # noqa: BLE001 — reported to the test
        chain = [f"{f.filename.rsplit('/src/', 1)[-1]}:{f.lineno}" for f in traceback.extract_tb(exc.__traceback__) if "/parrot" in f.filename]
        result["errors"][mod] = f"{type(exc).__name__}: {exc} via {chain}"
result["loaded"] = sorted(m for m in sys.modules if m.startswith(("parrot", "parrot_tools")))
print("@@RESULT@@" + json.dumps(result))
"""


def _probe(modules: list[str]) -> dict:
    if not (_SERVER_SRC.is_dir() and _TOOLS_SRC.is_dir()):
        pytest.skip("workspace layout not available — cannot block satellite distributions")
    block = [f"{os.sep}{_SERVER_SRC.relative_to(_REPO)}{os.sep}", f"{os.sep}{_TOOLS_SRC.relative_to(_REPO)}{os.sep}"]
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, json.dumps(block), json.dumps(modules)],
        capture_output=True,
        text=True,
        # ``import parrot`` chdirs the pytest process to navconfig's SITE_ROOT (the primary
        # checkout); pin cwd so relative PYTHONPATH entries resolve against THIS checkout.
        cwd=str(_REPO),
        env=os.environ.copy(),
        check=False,
    )
    marker = "@@RESULT@@"
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(marker)), None)
    assert line is not None, f"probe crashed:\nSTDOUT:\n{proc.stdout[-2000:]}\nSTDERR:\n{proc.stderr[-4000:]}"
    return json.loads(line[len(marker):])


def test_wikitoolkit_imports_without_server_or_tools_distributions() -> None:
    """``wikitoolkit`` must import with only the core distribution present."""
    result = _probe(["parrot.knowledge.wiki.entry", "parrot.knowledge.wiki.cli"])
    assert result["errors"] == {}, result["errors"]
    loaded = set(result["loaded"])
    forbidden = {
        "parrot.handlers.models",
        "parrot_tools",
        "parrot.bots.database.agent",
        "parrot.bots.database.cache",
        "parrot.bots.data",
    }
    assert not (loaded & forbidden), sorted(loaded & forbidden)


def test_parrot_bots_eager_surface_is_base_hierarchy_only() -> None:
    """``import parrot.bots`` loads AbstractBot/BaseBot/BasicAgent/Agent and nothing concrete."""
    result = _probe(["parrot.bots"])
    assert result["errors"] == {}, result["errors"]
    loaded = set(result["loaded"])
    concrete = {
        "parrot.bots.basic",
        "parrot.bots.chrome",
        "parrot.bots.search",
        "parrot.bots.voice",
        "parrot.bots.info",
        "parrot.bots.database",
        "parrot.bots.data",
    }
    assert not (loaded & concrete), sorted(loaded & concrete)


def test_parrot_bots_lazy_exports_still_resolve() -> None:
    """Every name in ``parrot.bots.__all__`` resolves, lazily, to a class."""
    import parrot.bots as bots

    for name in ("BasicBot", "Chatbot", "WebAgent", "WebSearchAgent"):
        assert isinstance(getattr(bots, name), type), name
    assert set(bots.__all__) <= set(dir(bots))


def test_bot_model_lives_in_core_and_server_shim_reexports() -> None:
    """``BotModel`` is defined in core ``parrot.models.bots``; the server path re-exports it."""
    from parrot.models.bots import BotModel

    assert BotModel.__module__ == "parrot.models.bots"
    pytest.importorskip("parrot.handlers.models.bots")
    from parrot.handlers.models.bots import BotModel as ShimBotModel

    assert ShimBotModel is BotModel


def test_sqlglot_dialect_map_is_shared() -> None:
    """The dialect map is one object, reachable from parrot.tools and the SQL toolkit."""
    from parrot.tools import SQLGLOT_DIALECT_MAP
    from parrot.tools.sql_dialects import _SQLGLOT_DIALECT_MAP
    from parrot.bots.database.toolkits.sql import _SQLGLOT_DIALECT_MAP as legacy

    assert SQLGLOT_DIALECT_MAP is _SQLGLOT_DIALECT_MAP is legacy
    assert SQLGLOT_DIALECT_MAP["postgresql"] == "postgres"
