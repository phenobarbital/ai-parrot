# TASK-3985: server_managed_params ClassVar, ServerParam, both schema paths, generated-schema exclusion, built-in migration (M4, part 1)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3981, TASK-3982
**Assigned-to**: unassigned
**Wave**: 3 (spec §9) · **Module**: M4 server-managed-params (core declaration)

---

## Context

Spec P3 / G4: server-managed params are hard-coded in two server dicts (`_SERVER_MANAGED`,
`tooling_store.py:40-43`; `_KNOWN_APP_DEPS`, `testing.py:42-44`), a host cannot declare one, and
`model_config_schema` ignores them (`config_schema.py:122-143`). Spec §2 "Server-managed rules": a
`server_managed_params: ClassVar[Mapping[str, ServerParam]]` on `AbstractToolkit` and `AbstractTool`;
constructor params are marked `x-server-managed` on **both** schema paths; `tenant`/`caller`/`agent` sources are
forbidden on constructor params (`__init_subclass__` raises `TypeError`); method params are excluded from every
generated LLM args schema. Built-ins migrate: `LLMWikiToolkit` declares its three toolkits `source="server"`,
`InfographicToolkit` declares `artifact_store` `source="app", key="artifact_store"`. The server dicts are deleted
in TASK-3987; per-call drop/fill and build fill are TASK-3986.

**Design pass (spec §3 M4 "Needs a design pass during /sdd-task")** — fixed here for TASK-3985/12/13:
1. Declaration: one ClassVar; a name is a *constructor* param iff it is in `cls.__init__`'s signature, else a
   *method* param (a toolkit method's signature, or a standalone tool's `_execute`).
2. Schemas: constructor names → `x-server-managed` (introspection + `config_model`); method names → absent from
   generated args schemas (this task) and refused in custom schemas (TASK-3989, M3b).
3. Bot build order in `apply_tooling_specs` (TASK-3986): `hydrate_params(spec)` → strip every server-managed key
   with a warning (§7 "stripped on load") → DatasetManager branch unchanged (it declares none) → fill constructor
   params: `app` → `self.app[key]` (`self.app` is set by `configure()` before the call, `bots/abstract.py:1515-1517`),
   `server` → left to the bespoke builder (no generic core builder; an unfilled required param fails construction
   and the spec is skipped, as today).
4. Server handlers (TASK-3987) read the ClassVar instead of the dicts.

---

## Scope

- Create `parrot/tools/server_params.py` with `ServerParam(BaseModel, frozen=True)` (`source`, `key`; `key`
  required when `source == "app"` — model validator) and helpers `constructor_server_params(cls) -> frozenset[str]`,
  `method_server_params(cls) -> dict[str, ServerParam]`.
- `AbstractToolkit` and `AbstractTool`: `server_managed_params: ClassVar[Mapping[str, ServerParam]] = {}`.
- `AbstractToolkit.__init_subclass__` (new) and `AbstractTool.__init_subclass__` (new): refuse (`TypeError`) a
  constructor param whose source is `tenant`/`caller`/`agent`. Call `super().__init_subclass__(**kwargs)`.
- `config_schema.introspect_config_schema` and `model_config_schema` honour constructor names from the ClassVar
  (union with the explicit `server_managed` kwarg, which stays for compatibility).
- `ToolkitTool._generate_args_schema_from_method` skips method server-managed names of the owning toolkit.
- Migrate `LLMWikiToolkit` and `InfographicToolkit`; their schemas must equal a golden copy captured **before**
  the change (from `build_schema_envelope(slug, cls, server_managed=<today's dict value>)`).
- Extend the core probe: one constructor param `source="app"`, one method param `source="tenant"` on `whoami`.
- Tests `test_server_managed_ctor_param_marked_on_both_schema_paths`, `test_scope_source_on_ctor_param_is_typeerror`,
  `test_builtin_schemas_match_golden`.

**NOT in scope**: per-call drop/fill and bot-build fill (TASK-3986); deleting the server dicts and the
PUT/`/me`/assign/execute refusals (TASK-3987); custom-schema refusal and remote-executor refusal (TASK-3989).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/server_params.py` | CREATE | ServerParam + constructor/method helpers |
| `packages/ai-parrot/src/parrot/tools/toolkit.py` | MODIFY | server_managed_params ClassVar; __init_subclass__; generated-schema exclusion |
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | server_managed_params ClassVar; __init_subclass__ ctor-source refusal |
| `packages/ai-parrot/src/parrot/tools/config_schema.py` | MODIFY | introspection + config_model paths honour the ClassVar |
| `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` | MODIFY | LLMWikiToolkit declares 3 source='server' params |
| `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | MODIFY | InfographicToolkit declares artifact_store source='app' |
| `packages/ai-parrot/tests/tools/_host_probe.py` | MODIFY | probe ctor param (app) + method param (tenant) |
| `packages/ai-parrot/tests/tools/data/feat622_builtin_schemas_golden.json` | CREATE | pre-change wiki/infographic schema golden copy |
| `packages/ai-parrot/tests/tools/test_server_managed_params.py` | CREATE | M4 declaration/schema tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.tools.config_schema import build_schema_envelope, introspect_config_schema, model_config_schema  # :146, :92, :122
from parrot.knowledge.wiki import LLMWikiToolkit  # knowledge/wiki/toolkit.py:41
from parrot.tools.infographic_toolkit import InfographicToolkit  # tools/infographic_toolkit.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/config_schema.py
def introspect_config_schema(cls: type, *, server_managed: frozenset[str] = frozenset()) -> dict[str, Any]:  # :92
    if fragment is None or pname in server_managed:  # :103 → {"x-server-managed": True} :104
def model_config_schema(cls: type) -> dict[str, Any]:  # :122 ← anchor (occurrences: 1) — no server_managed today
def build_schema_envelope(slug, cls, *, server_managed=frozenset()) -> ToolkitSchemaEnvelope  # :146
# packages/ai-parrot/src/parrot/tools/toolkit.py
    def _generate_args_schema_from_method(self) -> type[BaseModel]:  # :95 — loop over sig.parameters :107-129
    read_tools: ClassVar[frozenset[str]] = frozenset()  # added by TASK-3981
# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):  # :41 — __init__(self, pageindex_toolkit, graphindex_toolkit, okf_toolkit, config...) :70-74
# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
#   __init__(self, ..., artifact_store: ArtifactStore, ...) :230-233
# server today (golden source; deleted in TASK-3987):
# tooling_store.py:40-43 _SERVER_MANAGED = {"wiki": {"pageindex_toolkit","graphindex_toolkit","okf_toolkit"}, "infographic": {"artifact_store"}}
```

### Does NOT Exist
- ~~`server_managed` honoured by `model_config_schema`~~ — it takes no such argument today (`config_schema.py:122`).
- ~~`__init_subclass__` on `AbstractToolkit` / `AbstractTool`~~ — none today; created here (TASK-3989 extends both).
- ~~`ServerParam`~~ — created here.
- ~~a generic core builder for `source="server"` params~~ — none; bespoke builders (e.g. `_assign_wiki`) stay in the server.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/server_params.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/tools/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/tools/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/tools/config_schema.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/tools/infographic_toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/tools/_host_probe.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/tools/data/feat622_builtin_schemas_golden.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_server_managed_params.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/config_schema.py#introspect_config_schema",
    "sym:packages/ai-parrot/src/parrot/tools/config_schema.py#model_config_schema",
    "sym:packages/ai-parrot/src/parrot/tools/config_schema.py#build_schema_envelope",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#ToolkitTool._generate_args_schema_from_method",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py#LLMWikiToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/infographic_toolkit.py#InfographicToolkit"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Capture the golden JSON **first** (step 1) on the unmodified tree, commit it with the test.
- `__init_subclass__` must stay cheap (it runs for every toolkit subclass at import): inspect only when the
  subclass's own `__dict__` defines `server_managed_params`.
- Keep `server_params.py` import-light (pydantic only) — `toolkit.py` and `abstract.py` import it at top.

### Cross-feature ordering
- Wave 3: core files only; no sibling handler file. Merges after TASK-3981/TK-08 on the shared core files.

### Key Constraints
- Async throughout; no blocking I/O in async paths; `self.logger` (or the module `logger`) — never `print`.
- Pydantic models for every new data structure; Google-style docstrings and strict type hints.
- Core (`packages/ai-parrot`) never imports `ai-parrot-server` (spec §7).
- ARCHITECTURE R4: no new/modified function above cyclomatic complexity 10 or 60 lines; run `flake8` on changed files.
- **Spec §4 test rule (applies to every test in this task):** build requests with `aiohttp.test_utils.make_mocked_request` and install the session the way `navigator_session` does (`request[SESSION_OBJECT] = ...`), or use `aiohttp_client` over a real app. Never a `Mock` / `SimpleNamespace` with hand-set `.session` / `.app`. Side-effect **counters** prove refusals, not mocks. Mutation-check every new assertion (revert the code, see RED) and record the evidence in the Completion Note.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Generate the golden copy from today's code (`build_schema_envelope(slug, cls, server_managed=…)` for `wiki`, `infographic`) — *why*: AC "byte-identical".
2. Create `server_params.py` — *why*: the declaration type.
3. Add the ClassVars + `__init_subclass__` refusals — *why*: instances are shared across callers, so scope sources are illegal on constructors.
4. Make both schema paths honour the ClassVar; exclude method names from generated args schemas.
5. Migrate wiki/infographic; extend the probe; write tests (mutation: drop the model-path marking ⇒ RED).

### `packages/ai-parrot/src/parrot/tools/server_params.py` (CREATE)
```python
"""Server-managed parameter declarations (FEAT-622 M4)."""
from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, model_validator

ServerParamSource = Literal["server", "app", "tenant", "caller", "agent"]
SCOPE_SOURCES: frozenset[str] = frozenset({"tenant", "caller", "agent"})


class ServerParam(BaseModel, frozen=True):
    """Where the server takes a param's value from; never the client or the LLM."""

    source: ServerParamSource
    key: str | None = None  # app key, required when source == "app"

    @model_validator(mode="after")
    def _app_needs_key(self) -> "ServerParam":
        if self.source == "app" and not self.key:
            raise ValueError("ServerParam(source='app') requires key")
        return self


def _declared(cls: type) -> Mapping[str, ServerParam]:
    return getattr(cls, "server_managed_params", None) or {}


def constructor_server_params(cls: type) -> frozenset[str]:
    """Declared names that are ``cls.__init__`` parameters."""
    ctor = inspect.signature(cls.__init__).parameters
    return frozenset(name for name in _declared(cls) if name in ctor)


def method_server_params(cls: type) -> dict[str, ServerParam]:
    """Declared names that are NOT constructor parameters (filled per call from the scope)."""
    ctor = constructor_server_params(cls)
    return {name: param for name, param in _declared(cls).items() if name not in ctor}


def validate_server_params(cls: type) -> None:
    """``TypeError`` when a constructor param declares a scope source (instances are shared)."""
    # FILL IN: for name in constructor_server_params(cls): if _declared(cls)[name].source in SCOPE_SOURCES → TypeError
```

### `packages/ai-parrot/src/parrot/tools/config_schema.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def model_config_schema(cls: type) -> dict\[str, Any\]:' config_schema.py)
# In model_config_schema (config_schema.py:122-143), after the properties loop add:
    for name in constructor_server_params(cls):
        if name in schema.get("properties", {}):
            schema["properties"][name] = {"x-server-managed": True}
# In introspect_config_schema (:92), first line of the body:
    server_managed = frozenset(server_managed) | constructor_server_params(cls)
# FILL IN: confirm the golden copies stay byte-identical (introspection path for wiki/infographic)
```

### `packages/ai-parrot/src/parrot/tools/toolkit.py` (MODIFY)
```python
# AFTER — insert below `    read_tools: ClassVar[frozenset[str]] = frozenset()` (added by TASK-3981)
    #: FEAT-622 — params the server fills (never client JSON, never the LLM). See parrot.tools.server_params.
    server_managed_params: ClassVar[Mapping[str, ServerParam]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "server_managed_params" in cls.__dict__:
            validate_server_params(cls)
# In _generate_args_schema_from_method (toolkit.py:107-110), next to the `self` skip:
#   FILL IN: skip param_name in method_server_params(type(owner)) where owner = self.bound_method.__self__ (if a toolkit)
```

### `packages/ai-parrot/src/parrot/tools/abstract.py` (MODIFY)
```python
# AFTER — insert below `    access: ClassVar[Optional[str]] = None` (added by TASK-3981)
    server_managed_params: ClassVar[Dict[str, Any]] = {}  # FEAT-622: Mapping[str, ServerParam]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "server_managed_params" in cls.__dict__:
            validate_server_params(cls)
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` and `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` (MODIFY)
```python
# LLMWikiToolkit (class body, near :41):
    server_managed_params = {
        "pageindex_toolkit": ServerParam(source="server"),
        "graphindex_toolkit": ServerParam(source="server"),
        "okf_toolkit": ServerParam(source="server"),
    }
# InfographicToolkit (class body):
    server_managed_params = {"artifact_store": ServerParam(source="app", key="artifact_store")}
```

### FILL IN checklist
- [ ] `server_params.py::validate_server_params` — bounded by `test_scope_source_on_ctor_param_is_typeerror`.
- [ ] `toolkit.py::_generate_args_schema_from_method` exclusion — bounded by "Server-managed names never appear in generated … LLM schemas".
- [ ] `config_schema.py` — golden equality for wiki/infographic.
- [ ] `_host_probe.py` — ctor `app` param + `whoami(tenant)` method param.

---

## Acceptance Criteria

- [ ] Introspection and `config_model` paths both emit `x-server-managed` for the probe's constructor param.
- [ ] A constructor param with `source="tenant"` raises `TypeError` at class creation.
- [ ] Generated args schema of `whoami` lacks `tenant`.
- [ ] wiki / infographic schemas equal the committed golden copy byte for byte.
- [ ] Existing `pytest packages/ai-parrot/tests/tools/test_config_schema.py packages/ai-parrot/tests/tools/test_toolkit_config_hooks.py -q` pass.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/tools/test_server_managed_params.py -q`
- `pytest packages/ai-parrot/tests/tools/test_config_schema.py -q`
- `pytest packages/ai-parrot/tests/tools/test_toolkit_config_hooks.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_server_managed_params.py
def test_server_managed_ctor_param_marked_on_both_schema_paths(host_plugins): ...
def test_scope_source_on_ctor_param_is_typeerror(): ...
def test_generated_args_schema_excludes_method_server_param(host_plugins): ...
def test_builtin_schemas_match_golden(): ...   # wiki + infographic vs data/feat622_builtin_schemas_golden.json
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-host-toolkits --feature-id FEAT-622`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-host-toolkits.json`, and every "Cross-feature ordering"
   line in Implementation Notes must be satisfied on `origin/dev`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-host-toolkits.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-id> agentstudio-host-toolkits verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below (including mutation-check evidence), then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (tramo B1, sequential fallback)
**Date**: 2026-10-02
**Notes**: ServerParam + constructor/method helpers (tools/server_params.py); server_managed_params ClassVar + __init_subclass__ ctor-scope-source TypeError on AbstractToolkit and AbstractTool; both schema paths honour constructor names; method params dropped from ToolkitTool generated args schema; wiki/infographic migrated; golden captured from pre-change code (build_schema_envelope with today's server dict) and equality asserted now WITHOUT the explicit server_managed kwarg. Core probe: ctor param app_store (source=app) + method param tenant on whoami. Test module intentionally has no 'from __future__ import annotations' (string annotations would make introspection mark every param server-managed).
**Mutation evidence**: model-path marking disabled => both_schema_paths RED; introspection union removed => json_typed_ctor_param RED; toolkit __init_subclass__ validate removed => typeerror RED; tool validate removed => typeerror RED; method exclusion removed => generated_args_schema RED; restored.

**Deviations from spec**: none (handler modules are now packages; edit sites re-anchored)
