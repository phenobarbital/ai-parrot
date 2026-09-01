"""Flex Program Dashboard — offline end-to-end demo (FEAT-491 TASK-2699).

Lineage: this is a domain-specific retelling of ``examples/agents/a2ui/
deterministic_refresh_dashboard.py`` (FEAT-324/326 x FEAT-469) for the Flex
program agent (`agents/flex_dashboard.py`, FEAT-491). Same shape: publish a
deterministic recipe once (`FlexDashboard.dashboard_descriptor()`), replay
it forever via `RecipeRunner`, and expose a `refresh_dashboard` agent
function through the A2UI Agent Functions runtime (FEAT-469) so a renderer
can ask for a re-render with inline filter state.

Fully offline — no database, no network, no LLM:

1. **Synthetic data** (`flex_synthetic_data.py`) — the six Flex dataset
   aliases (spec §2), injected directly via ``DatasetManager.add_dataframe``
   (bypassing `FlexDashboard.register_datasets()`'s lazy `QuerySlugSource`
   registration entirely — slug data is prod-only, spec §7 "Slug data is
   prod-only"; this demo never touches QuerySource).
2. **Publish** — ``InfographicAuthoringMixin.publish_recipe()`` maps the
   descriptor's ten sections to registered transformers
   (`agents/flex_dashboard/transformers.py`) and persists an
   ``InfographicRecipe`` whose ``LayoutSpec`` (v2) is used verbatim.
3. **Deterministic replay** — ``RecipeRunner.run()`` twice with the same
   params produces byte-identical HTML; a params override (month/pay_code)
   gives a filtered variant. No narrator is configured — the
   `flex_narrative_facts` step stays absent, proving the recipe replays
   with no LLM (spec §5 "Recipe replays deterministically with NO narrator
   configured").
4. **The RPC leg** — an ``A2UIRuntime`` over the agent's own ``ToolManager``:
   ``action`` + ``dataModel`` pushes inline filter state; `callAgentFunction`
   → `refresh_dashboard` re-runs the recipe (explicit args win over the
   persisted surface state).
5. **Capabilities** — ``export_functions()`` / ``agent_capabilities()`` show
   what a renderer discovers.

**Server lane** (proposal U3, no code here): once a recipe is published to
a SHARED recipe store (not this demo's throwaway ``tmp``-rooted
``FileRecipeStore``), it is servable as-is through the existing
``infographic_recipes`` / ``infographic_render`` handlers
(``ai-parrot-server/src/parrot/handlers/infographic_recipes.py``) — no new
server code is needed; only the store location changes from a local
directory to whatever store the deployment's handlers are wired to.

Prerequisites::

    pip install ai-parrot ai-parrot-visualizations[a2ui]

Usage::

    source .venv/bin/activate
    python examples/agents/a2ui/flex_dashboard_demo.py
    python examples/agents/a2ui/flex_dashboard_demo.py --serve

.. note::

   The ``interactive-html`` renderer output needs an HTTP origin — opening
   the files as ``file://`` breaks Chart.js canvas rendering. Use ``--serve``.
"""

from __future__ import annotations

import argparse
import asyncio
import http.server
import importlib.util
import json
import os
import re
import socketserver
import sys
import threading
import webbrowser
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
_AGENTS_DIR = REPO_ROOT / "agents"
_FLEX_PACKAGE_DIR = _AGENTS_DIR / "flex_dashboard"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT))  # repo root, for `agents.*` cross-imports

from flex_synthetic_data import build_flex_frames
from parrot.auth.permission import build_principal_context
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.catalog.export import (
    agent_capabilities,
    export_functions,
)
from parrot.outputs.a2ui.recipes.store import FileRecipeStore
from parrot.outputs.a2ui.runtime import (
    A2UICallContext,
    A2UIRuntime,
    FunctionCallRecord,
    SurfaceState,
)
from parrot.outputs.a2ui.runtime.adapters import ToolManagerExecutor
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.backends import build_overflow_store
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.tools.infographic_recipes.runner import (
    RecipeRunException,
    RecipeRunner,
)
from parrot.tools.infographic_sections import GapReport

# The ``interactive-html`` renderer registers itself on import; it ships from
# ai-parrot-visualizations (namespace-merged). Without it, RecipeRunner's
# default render profile cannot resolve.
try:
    import parrot.outputs.a2ui_renderers.interactive_html  # noqa: F401

    _HAS_RENDERER = True
except ImportError:
    _HAS_RENDERER = False


def _load_module(name: str, path: Path, search_dir: Path | None = None):
    """File-path-load *path* under module *name* (worktree-safe).

    ``agents/flex_dashboard.py`` (the agent FILE) and ``agents/
    flex_dashboard/`` (the sibling PACKAGE for transformers/skills/kb) share
    the same name — Python's FileFinder always resolves a plain ``import
    agents.flex_dashboard`` to the PACKAGE, never the file (verified
    empirically; same finding as this feature's test suite). This mirrors
    how production actually loads agent files:
    ``parrot.registry.registry.AgentRegistry._load_modules_from_directory``
    globs ``agents/*.py`` and loads each one via
    ``importlib.util.spec_from_file_location`` under a synthetic module
    name — never a plain dotted ``agents.<name>`` import.
    """
    if name in sys.modules:
        return sys.modules[name]
    kwargs = {"submodule_search_locations": [str(search_dir)]} if search_dir else {}
    spec = importlib.util.spec_from_file_location(name, path, **kwargs)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {name!r} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _load_flex_dashboard_class():
    # Pre-register the real "agents.flex_dashboard" package chain so the
    # agent file's own `import agents.flex_dashboard.transformers` resolves
    # deterministically, THEN load the agent file itself under its own
    # distinct name (never "agents.flex_dashboard" — that name is reserved
    # for the package).
    _load_module("agents", _AGENTS_DIR / "__init__.py", _AGENTS_DIR)
    _load_module("agents.flex_dashboard", _FLEX_PACKAGE_DIR / "__init__.py", _FLEX_PACKAGE_DIR)
    _load_module("agents.flex_dashboard.normalize", _FLEX_PACKAGE_DIR / "normalize.py")
    _load_module("agents.flex_dashboard.transformers", _FLEX_PACKAGE_DIR / "transformers.py")
    module = _load_module("flex_dashboard_agent_module", _AGENTS_DIR / "flex_dashboard.py")
    return module.FlexDashboard


FlexDashboard = _load_flex_dashboard_class()

OUTPUT_DIR = REPO_ROOT / "artifacts" / "flex_dashboard_demo"

RECIPE_NAME = FlexDashboard.DASHBOARD_RECIPE_NAME
#: RecipeRunner assembles the envelope with surface_id=f"{recipe.name}-infographic",
#: so the surface id is stable across runs — the renderer can key its state on it.
SURFACE_ID = f"{RECIPE_NAME}-infographic"
SESSION_ID = "sess-flex-demo"


def rule(title: str) -> None:
    """Print a section rule with a title."""
    print("\n" + "═" * 72)
    print(f"  {title}")
    print("═" * 72)


# ═══════════════════════════════════════════════════════════════════════════
# Step 1 — In-memory runtime adapters (Protocol-shaped, no Redis needed)
# ═══════════════════════════════════════════════════════════════════════════
#
# Production uses ConversationMemorySurfaceStore (both protocols over
# ConversationMemory metadata). The runtime takes the Protocols by injection,
# so a dict-backed pair is all a self-contained example needs.


class InMemorySurfaceStore:
    """Dict-backed ``SurfaceStateStore``: the last ``dataModel`` per surface."""

    def __init__(self) -> None:
        self._store: dict[tuple, SurfaceState] = {}

    async def get(self, session_id: str, surface_id: str) -> SurfaceState | None:
        return self._store.get((session_id, surface_id))

    async def put(self, session_id: str, state: SurfaceState) -> None:
        self._store[(session_id, state.surface_id)] = state

    async def delete(self, session_id: str, surface_id: str) -> None:
        self._store.pop((session_id, surface_id), None)


class InMemoryPendingCalls:
    """Dict-backed ``PendingCallRegistry`` with the standard TTL semantics."""

    def __init__(self) -> None:
        self._store: dict[tuple, FunctionCallRecord] = {}

    async def add(self, session_id: str, record: FunctionCallRecord) -> None:
        self._store[(session_id, record.function_call_id)] = record

    async def resolve(
        self, session_id: str, function_call_id: str, value: Any, error: Any
    ) -> FunctionCallRecord | None:
        key = (session_id, function_call_id)
        record = self._store.get(key)
        if record is None:
            return None
        if datetime.now(UTC) > record.created_at + timedelta(seconds=record.ttl_seconds):
            del self._store[key]
            return None
        del self._store[key]
        return record


# ═══════════════════════════════════════════════════════════════════════════
# Step 2 — Demo lanes
# ═══════════════════════════════════════════════════════════════════════════


async def lane_publish(agent: FlexDashboard, recipe_store: FileRecipeStore) -> bool:
    """Publish the dashboard recipe and declare its run-time filter params."""
    rule("1 — publish_recipe: sections → registered transformers → recipe")

    recipe = await agent.publish_recipe(RECIPE_NAME, FlexDashboard.dashboard_descriptor(), overwrite=True)
    if isinstance(recipe, GapReport):
        print("  ✗ GAPS — unregistered transformers:")
        for gap in recipe.gaps:
            print(f"    - {gap.section}")
        return False

    # publish_recipe carries descriptor.params onto every TransformStep, but
    # the DECLARED run-time params (name/default, override whitelist) are the
    # recipe author's call — declare them and re-save (FlexDashboard.
    # recipe_params(), TASK-2697). An override for an undeclared name raises
    # (typo protection).
    recipe.params = FlexDashboard.recipe_params()
    await recipe_store.save(recipe)

    print(f"  recipe        : {recipe.name}")
    print(f"  transforms    : {[t.transformer for t in recipe.transforms]}")
    print(f"  data_sources  : {[ds.alias for ds in recipe.data_sources]}")
    print(f"  declared params: {({p.name: p.default for p in recipe.params})}")
    print(f"  surface_id    : {SURFACE_ID}  (stable across replays)")
    return True


#: The interactive-html renderer mints per-render DOM element ids
#: (``chart-<hex8>``, ``tabs-<hex8>``, ``nested-<hex8>`` via ``uuid4``) — the
#: one thing in the output that is NOT replay-stable. The FEAT-324 determinism
#: guarantee lives at the data plane (params → transforms → dataModel →
#: envelope, all replay-stable, surfaceId included); these ids are internal
#: renderer wiring with no data content. Normalize them before comparing.
_VOLATILE_DOM_ID = re.compile(rb"(chart|tabs|nested)-[0-9a-f]{8}")


def _normalize_render(content: bytes) -> bytes:
    """Replace the renderer's per-render DOM ids with a stable token."""
    return _VOLATILE_DOM_ID.sub(rb"\1-x", content)


async def lane_deterministic_replay(runner: RecipeRunner, pctx: Any) -> None:
    """Prove the refresh is deterministic, then replay with filter overrides."""
    rule("2 — RecipeRunner.run: deterministic replay + filtered variants")

    first = await runner.run(RECIPE_NAME, pctx=pctx)
    second = await runner.run(RECIPE_NAME, pctx=pctx)
    identical = _normalize_render(first.content or b"") == _normalize_render(second.content or b"")
    print(f"  replay #1     : {len(first.content or b''):,} bytes")
    print(f"  replay #2     : {len(second.content or b''):,} bytes")
    print(f"  identical     : {identical}  (modulo the renderer's per-render DOM")
    print("                  element ids — every number, label, series and the")
    print("                  surfaceId itself is replay-stable; no narrator is")
    print("                  configured, so flex_narrative_facts stays absent)")
    if not identical:
        print("  ⚠ unexpected: same params should produce identical content")

    (OUTPUT_DIR / "01_dashboard_default.html").write_bytes(first.content or b"")

    filtered = await runner.run(RECIPE_NAME, params={"month": "2025-10", "pay_code": "Field Time"}, pctx=pctx)
    (OUTPUT_DIR / "02_dashboard_2025-10_field-time.html").write_bytes(filtered.content or b"")
    print(f"  filtered      : month=2025-10 pay_code='Field Time' → " f"{len(filtered.content or b''):,} bytes")

    try:
        await runner.run(RECIPE_NAME, params={"moth": "oops"}, pctx=pctx)
    except RecipeRunException as exc:
        print(f"  typo guard    : undeclared override rejected — {exc.error.detail}")


async def lane_rpc(
    runtime: A2UIRuntime,
    ctx: A2UICallContext,
    surfaces: InMemorySurfaceStore,
    refresh_tool: Any,
) -> None:
    """Drive the four FEAT-469 flows the way a renderer would."""
    rule("3 — action + dataModel: the surface pushes its inline filter state")

    action_env = {
        "version": "v1.0",
        "action": {
            "name": "filters_changed",
            "surfaceId": SURFACE_ID,
            "sourceComponentId": "filter-bar",
            "timestamp": datetime.now(UTC).isoformat(),
            "context": {},
            "dataModel": {"filters": {"month": "2025-09", "flex_type": "Flex"}},
        },
    }
    res = await runtime.dispatch(action_env, ctx)
    print(f"  responses     : {res.messages or '(none — actions ack silently)'}")
    print(f"  user_turn     : {res.user_turn}")
    stored = await surfaces.get(SESSION_ID, SURFACE_ID)
    print(f"  surface state : {stored.data_model if stored else None}")

    rule("4 — callAgentFunction: the renderer asks for a filtered refresh")

    call_env = {
        "version": "v1.0",
        "callAgentFunction": {
            "surfaceId": SURFACE_ID,
            "functionCallId": "fc-refresh-1",
            "callFunction": {
                "call": "refresh_dashboard",
                "args": {"month": "2025-10"},  # explicit arg wins over state
                "catalogId": DEFAULT_CATALOG_ID,
            },
        },
    }
    res = await runtime.dispatch(call_env, ctx)
    reply = res.messages[0]
    print(f"  envelope key  : {[k for k in reply if k != 'version']}")
    value = reply.get("agentFunctionResponse", {}).get("value")
    print(f"  tool result   : {json.dumps(value, indent=2) if value else reply}")

    rule("5 — surface-state refresh: no args, filters come from the dataModel")

    state = await surfaces.get(SESSION_ID, SURFACE_ID)
    result = await refresh_tool.execute(_a2ui_surface_state=state)
    print(f"  tool result   : {json.dumps(result.result, indent=2)}")

    rule("6 — callRendererFunction: the agent calls the renderer back")

    fc_id, outbound = await runtime.call_renderer(
        SESSION_ID,
        SURFACE_ID,
        "updateDataModel",
        {"path": "/lastRefreshed", "value": datetime.now(UTC).isoformat()},
    )
    print(f"  outbound      : {json.dumps(outbound)}")

    response_env = {
        "version": "v1.0",
        "rendererFunctionResponse": {"functionCallId": fc_id, "value": {"applied": True}},
    }
    res = await runtime.dispatch(response_env, ctx)
    print(f"  correlated    : {'yes (no error envelope)' if not res.messages else res.messages}")


def lane_capabilities(executor: ToolManagerExecutor) -> None:
    """Show what a renderer discovers about this agent."""
    rule("7 — export_functions / agent_capabilities: the discovery documents")

    functions = export_functions(executor)
    capabilities = agent_capabilities([DEFAULT_CATALOG_ID])

    print(f"  functions     : {sorted(functions)}")
    print(f"  capabilities  : {json.dumps(capabilities)}")

    doc = OUTPUT_DIR / "03_capabilities.json"
    doc.write_text(json.dumps({"functions": functions, "capabilities": capabilities}, indent=2))
    print(f"  wrote         : {doc.relative_to(REPO_ROOT)}")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════


async def main() -> None:
    """Wire storage + agent + runtime, then run every lane."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not _HAS_RENDERER:
        print("✗ ai-parrot-visualizations[a2ui] is not importable — the recipe's")
        print("  'interactive-html' render profile cannot resolve. Install it first.")
        return

    backend = ConversationSQLiteBackend(path=str(OUTPUT_DIR / "artifacts.db"))
    await backend.initialize()
    artifact_store = ArtifactStore(backend, build_overflow_store())
    recipe_store = FileRecipeStore(OUTPUT_DIR / "recipes")

    agent = FlexDashboard(
        name="flex-dashboard-demo",
        artifact_store=artifact_store,
        recipe_store=recipe_store,
        injection_detection=False,
    )

    # Offline injection lane (spec §7: slug data is prod-only — this demo
    # NEVER touches QuerySource). Bypasses `register_datasets()`'s lazy
    # `add_query(query_slug=...)` registration entirely; each alias is
    # registered directly as an in-memory frame instead.
    for alias, frame in build_flex_frames().items():
        agent._dataset_manager.add_dataframe(alias, frame, description=f"Synthetic {alias} frame")

    if not await lane_publish(agent, recipe_store):
        return

    pctx = build_principal_context("demo-user", channel="script")
    runner = RecipeRunner(recipe_store, agent._dataset_manager)
    await lane_deterministic_replay(runner, pctx)

    # --- FEAT-469 runtime over the agent's own ToolManager ---
    refresh_tool = agent.build_refresh_tool(pctx)

    executor = ToolManagerExecutor(agent.tool_manager)
    surfaces = InMemorySurfaceStore()
    runtime = A2UIRuntime(executor=executor, surfaces=surfaces, pending=InMemoryPendingCalls())
    ctx = A2UICallContext(
        agent_id="flex_dashboard",
        user_id="demo-user",
        session_id=SESSION_ID,
        surface_id=SURFACE_ID,
        transport="http",
        permission_context=pctx,
    )

    await lane_rpc(runtime, ctx, surfaces, refresh_tool)
    lane_capabilities(executor)

    rule("Done")
    print(f"  artifacts in  : {OUTPUT_DIR.relative_to(REPO_ROOT)}")
    for f in sorted(OUTPUT_DIR.glob("*.html")):
        print(f"    - {f.name}")


def _serve_and_open(directory: Path, port: int = 8092) -> None:
    """Serve OUTPUT_DIR over HTTP and open the default dashboard."""
    os.chdir(directory)
    socketserver.TCPServer.allow_reuse_address = True
    try:
        httpd = socketserver.TCPServer(("", port), http.server.SimpleHTTPRequestHandler)
    except OSError as exc:
        print(f"  ⚠ could not bind port {port}: {exc}")
        return

    url = f"http://localhost:{port}/01_dashboard_default.html"
    print(f"\n  🌐 serving at {url} — Ctrl+C to stop\n")
    threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  server stopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Flex Program Dashboard — offline deterministic demo",
    )
    parser.add_argument("--serve", action="store_true", help="serve + open the output")
    parser.add_argument("--port", type=int, default=8092)
    args = parser.parse_args()

    asyncio.run(main())

    if args.serve:
        _serve_and_open(OUTPUT_DIR, port=args.port)

    # Some parrot subsystems may leave non-daemon threads alive; flush + _exit
    # is the same belt-and-suspenders guard the sibling examples use.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
