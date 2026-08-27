# TASK-2518: Toolkit config surfaces — schema introspection + assignment

**Feature**: FEAT-467 — Agent Studio — Management API
**Spec**: `sdd/specs/agentstudio-management.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2510, TASK-2511
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10. Some toolkits need configuration before they can be
assigned; the UI needs their config schemas. First-class support (resolved
in original request): `LLMWikiToolkit` (including `WikiConfig.storage_dir`
— the directory where the LLM wiki starts), `DatasetManager`,
`InfographicToolkit`. Resolved in brainstorm: wiki toolkit deps are
**reuse-else-build** — reuse the bot's captured pageindex/graphindex
toolkits when present, otherwise construct fresh from the submitted
`WikiConfig`.

---

## Scope

- Implement `StudioToolkitsHandler(StudioBaseView)` in
  `handlers/studio/toolkits.py`:
  - `GET /api/v1/astudio/toolkits/{slug}/schema` — JSON schema of the
    toolkit's configuration: introspect `__init__` signature (names,
    types, defaults, required) and, for the three first-class toolkits,
    hand-curated schema entries; mark non-client-suppliable params
    `server_managed: true` (`artifact_store`, `pageindex_toolkit`,
    `graphindex_toolkit`, `okf_toolkit`). For `wiki`, embed the
    `WikiConfig` Pydantic schema (`model_json_schema()`).
  - `POST /api/v1/astudio/agents/{name}/toolkits` — body
    `{slug, params}`:
    - `wiki`: build `WikiConfig(**params)`; reuse the bot's captured
      `_pageindex_toolkit`/`_graphindex_toolkit`/okf when present, else
      construct them from the config; instantiate `LLMWikiToolkit`;
      register via `bot.tool_manager.register_toolkit(instance)`.
    - `dataset_manager`: instantiate `DatasetManager(**params)` (all
      params optional) and register.
    - `infographic`: wire `artifact_store` from `app['artifact_store']`
      (422 when absent), pass client params, register.
    - Generic slugs: resolve via `TOOL_REGISTRY` and instantiate with
      params (422 listing missing required/server-managed args on
      TypeError).
    - Response: registered tool names + `reload_required: false` (live
      registration) and `persisted: false` caveat.
- Routes + tests (schema shape, wiki reuse-else-build both paths,
  infographic app-context wiring).

**NOT in scope**: persisting toolkit config into agent YAML (compose with
TASK-2512 create/persist or a follow-up); deterministic execution
(TASK-2517).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py` | CREATE | schema + assignment handler |
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | add routes |
| `packages/ai-parrot-server/tests/studio/test_toolkits.py` | CREATE | schema/assignment tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki import LLMWikiToolkit, WikiConfig  # wiki/__init__.py:45 (lazy PEP 562)
from parrot.tools.dataset_manager.tool import DatasetManager  # tool.py:501 (core)
from parrot.tools.infographic_toolkit import InfographicToolkit  # infographic_toolkit.py:178 (core)
from parrot_tools import TOOL_REGISTRY                        # parrot_tools/__init__.py:12
from parrot.tools.discovery import resolve_class              # discovery.py:139
import inspect                                                # stdlib — signature introspection
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:54
class LLMWikiToolkit(AbstractToolkit):
    tool_prefix: str = "wiki"  # :81
    def __init__(self, pageindex_toolkit, graphindex_toolkit, okf_toolkit,
                 config: WikiConfig, agent_id: str = "agent",
                 store: Optional[BaseWikiStore] = None, **kwargs) -> None: ...  # :83
# WikiConfig (knowledge/wiki/models.py:52): wiki_name* (:83),
#   storage_dir: Path* (:84 — wiki plane root), source_dir (:85, default
#   {storage_dir}/sources), storage_backend Literal["sqlite","memory","arangodb"]
#   ="sqlite" (:112), search_weights (:93), charter_path (:122)
# Bot capture points: interfaces/tools.py:190 stashes LLMWikiToolkit as
#   bot._llmwiki_toolkit; bots/abstract.py:402-404 declares
#   _pageindex_toolkit / _graphindex_toolkit / _llmwiki_toolkit

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:501
class DatasetManager(AbstractToolkit):
    def __init__(self, df_prefix="df", generate_guide=True,
                 include_summary_stats=False, auto_detect_types=True,
                 policy_guard=None, dataplane_guard=None,
                 usage_rules=None, **kwargs): ...  # :549 — all optional

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py:178
class InfographicToolkit(AbstractToolkit):
    def __init__(self, *, artifact_store: ArtifactStore, template_dirs=None,
                 templates=None, emit_a2ui=False, recipe_store=None,
                 recipe_runner=None, dataset_manager=None, **kwargs) -> None: ...  # :211
# artifact_store REQUIRED keyword-only; server wires app['artifact_store']
#   (manager/manager.py:2157)

# ToolManager.register_toolkit(toolkit, **kwargs) -> List[AbstractTool]  # manager.py:1008
# BotManager.reload_agent (TASK-2510) — available if assignment chooses to
#   rebuild instead of live-register (default: live-register)
```

### Does NOT Exist
- ~~`WikiToolkit`~~ — the class is `LLMWikiToolkit`; NOT in
  `TOOL_REGISTRY`; cannot be instantiated by slug lookup.
- ~~`InfographicToolkit` in `TOOL_REGISTRY`~~ — absent; only
  `dataset_manager` of the three has a registry slug
  (`"dataset_manager": "parrot.tools.dataset_manager.DatasetManager"`,
  parrot_tools/__init__.py:212).
- ~~Pageindex/graphindex toolkit factories in the server package~~ —
  construction helpers live near the wiki package; grep
  `parrot/knowledge/` for the pageindex/graphindex toolkit classes and
  their constructors before building fresh instances (verify at
  implementation time — construction args not pinned here).
- ~~A toolkit config-schema endpoint~~ — greenfield;
  `/api/v1/tools/catalog` lists slugs only.

---

## Implementation Notes

### Pattern to Follow
Schema generation: `inspect.signature(cls.__init__)` → parameter table
(skip `self`/`**kwargs`), augmented by a hand-curated dict for the three
first-class toolkits (types that introspection can't express +
`server_managed` markers). For `wiki`: `WikiConfig.model_json_schema()`
embedded under `config`.

### Key Constraints
- Reuse-else-build (resolved): check
  `getattr(bot, '_pageindex_toolkit', None)` etc. FIRST; only construct
  from `WikiConfig` when absent. Log which path was taken.
- `storage_dir` is user input — validate it is an absolute path or resolve
  under a configurable root; reject traversal into system paths.
- Assignment mutates the live shared instance; note `persisted: false`.
- 422 responses enumerate exactly which params are missing/server-managed.

### References in Codebase
- `handlers/tools_catalog.py:44 _build_catalog` — safe best-effort import
  pattern for metadata extraction.

---

## Acceptance Criteria

- [ ] Schema endpoint serves wiki/dataset_manager/infographic with correct
      required + `server_managed` markers; generic slugs introspected.
- [ ] Wiki assignment works via BOTH paths (reuse captured toolkits;
      construct fresh from `WikiConfig`).
- [ ] Infographic assignment wires `app['artifact_store']`; 422 when the
      app lacks it.
- [ ] `pytest packages/ai-parrot-server/tests/studio/test_toolkits.py -v` passes.
- [ ] `ruff check packages/ai-parrot-server/src/parrot/handlers/studio/` clean.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_toolkits.py
class TestToolkitSurfaces:
    async def test_wiki_schema_includes_storage_dir(self, studio_app): ...
    async def test_infographic_schema_marks_server_managed(self, studio_app): ...
    async def test_assign_wiki_reuses_captured_toolkits(self, studio_app): ...
    async def test_assign_wiki_builds_fresh_from_config(self, studio_app): ...
    async def test_assign_infographic_wires_artifact_store(self, studio_app): ...
    async def test_assign_missing_params_422(self, studio_app): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2510, TASK-2511 completed
3. **Verify the Codebase Contract** — especially grep the pageindex/
   graphindex toolkit constructors before the build-fresh path
4. **Update status** in `sdd/tasks/index/agentstudio-management.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-27
**Notes**:
- `StudioToolkitsHandler` (GET `toolkits/{slug}/schema`, POST
  `agents/{name}/toolkits`) implemented in `handlers/studio/toolkits.py`;
  routes appended to `setup_studio_routes`.
- Schema: `_introspect_params()` walks `inspect.signature(cls.__init__)`
  (skips `self`/`**kwargs`), marking `required`/`server_managed`/`type`/
  `default` per param. Wiki's `config` param is enriched with the real
  `WikiConfig.model_json_schema()`; `pageindex_toolkit`/
  `graphindex_toolkit`/`okf_toolkit` marked `server_managed`.
  `infographic`'s `artifact_store` marked required+`server_managed`.
  Generic slugs resolve via `discover_from_registry()` (declarative
  `TOOL_REGISTRY` only, per Codebase Contract) + `resolve_class()`.
- Wiki assignment: reuse-else-build resolved as specified —
  `getattr(bot, '_pageindex_toolkit'/'_graphindex_toolkit', None)`
  checked first; when absent, `pageindex_toolkit` is built fresh via
  `PageIndexToolkit(adapter=PageIndexLLMAdapter(client=bot.get_client()),
  storage_dir=.../pageindex)` and `graphindex_toolkit` via the (grepped,
  not pre-pinned in the contract) `build_graph_memory_toolkit()` factory
  in `parrot/knowledge/graphindex/factory.py` — an "open or create"
  helper that already handles the empty/nonexistent-plane case cleanly
  (zero nodes/edges, `HashingGraphEmbedder` fallback). Response reports
  `pageindex_source`/`graphindex_source` as `"reused"`/`"built"`.
- `storage_dir` validation: no dedicated wiki-storage-root config exists
  anywhere in the codebase (grepped `parrot/conf.py` and
  `knowledge/wiki/project.py`) — absolute paths are accepted after a
  system-path denylist check (`/etc`, `/root`, `/bin`, etc. — deliberately
  NOT `/` itself, since `/` is an ancestor of every absolute path and
  would reject all of them); relative paths are sandboxed under
  `AGENTS_DIR / "wiki_storage"` via the existing TASK-2511
  `resolve_safe_path` helper.
- Infographic assignment wires `app['artifact_store']`, 422
  `server_managed` with `details.missing=["artifact_store"]` when absent.
- `dataset_manager` and the generic path both proactively compute missing
  required params via signature introspection BEFORE instantiating (422
  `server_managed`), falling back to a `TypeError` catch as a safety net.
- Tests (14, all passing): schema shape for all three first-class
  toolkits + generic introspection + unknown-slug 404; wiki assignment
  both reuse and build-fresh paths (real `LLMWikiToolkit` +
  `build_graph_memory_toolkit` machinery against `tmp_path` — real
  SQLite/local-file backends, no network) + invalid-config 422;
  infographic wiring + missing-artifact_store 422; generic success +
  missing-params 422 + unknown-slug 404 + ownership 403. Full
  `packages/ai-parrot-server/tests/studio/` suite (136 tests) passes.
  `ruff check handlers/studio/` clean except the same pervasive
  pre-existing `BLE001` fail-open pattern noted in every other file in
  this directory (one instance in this task's own `except Exception:
  invalid JSON` guard, matching the established convention).

**Deviations from spec**:
- No bot-level capture attribute exists for the OKF toolkit anywhere in
  the codebase (only `_pageindex_toolkit`/`_graphindex_toolkit`/
  `_llmwiki_toolkit` are declared on `AbstractBot`), and `OKFToolkit`
  cannot be constructed from a bare `WikiConfig` — it requires an
  already-ingested, OKF-enriched PageIndex tree
  (`tree`/`graph`/`content_store`/`tree_name`, all required, no trivial
  "empty" degenerate form analogous to `PyDiGraph()`/`IndexFlatL2()`).
  `LLMWikiToolkit.__init__` only stores `okf_toolkit` — verified it is
  never touched during construction — so `None` is passed for it on
  BOTH the reuse and build-fresh wiki paths; OKF-specific wiki tools
  are unavailable until a real OKF toolkit is wired in through a
  separate mechanism. This narrows "reuse-else-build" (as literally
  worded in the task) to the two toolkits that actually have a
  capture point / a real fresh-build factory.
- `_WIKI_STORAGE_ROOT` (`AGENTS_DIR / "wiki_storage"`) is a new,
  task-local convention — no existing wiki-storage-root config was
  found to reuse (see Notes above).
