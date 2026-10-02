# TASK-3979: Adopt the resolver on bot build and the Studio resolvers — one-line shims (M2, part 1)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3975, TASK-3978
**Assigned-to**: unassigned
**Wave**: 2 (spec §9) · **Module**: M2 resolver-adoption

---

## Context

Spec §1 P1 table: seven Studio paths and the bot build each pick their own resolver; only the live assign and
execute paths see `plugins.tools`. Spec §3 M2: every P1 path calls `get_toolkit_resolver()`;
`_resolve_toolkit_class`, `_resolve_registry_class` and `_resolve_spec_class` become one-line shims (imports and
tests keep working); `_EXPLICIT` is replaced by the resolver's built-in entries; persisted specs whose slug no
longer resolves are kept and reported `unavailable` (already the FEAT-593 list behaviour through
`schema_for` raising `LookupError`, `toolkit_config.py:78-83`). The catalogue is TASK-3980.

---

## Scope

- `interfaces/tools.py::_resolve_spec_class` → `return get_toolkit_resolver().resolve(slug)`.
- `studio/toolkits.py::_resolve_toolkit_class` → same shim (drop `discover_from_registry` import if unused).
- `studio/testing.py::_resolve_registry_class` → same shim (drop `discover_all` import if unused).
- `studio/tooling_store.py`: delete `_EXPLICIT`; `schema_for` resolves through `get_toolkit_resolver().resolve(slug)`
  (built-ins come from the resolver). `_SERVER_MANAGED` stays until TASK-3987.
- `studio/toolkit_overrides.py::_spec` already goes through `store.schema_for` — **no edit**; verify by test.
- Create the server host fixture `tests/studio/_host_probe.py` (same probe package shape as the core one,
  plus `tp_probe_tool_write`, a write `AbstractTool` variant used by TASK-3982).
- Tests proving each shim returns the host class and the "unavailable but kept" FEAT-593 list behaviour.

**NOT in scope**: the catalogue (`tools_catalog.py`, TASK-3980); the cross-path integration test
`test_every_studio_path_sees_host_toolkit` (TASK-3980); policy wiring (TASK-3983/TK-10); server-managed
handling (TASK-3987). Do not touch `discovery.py` (ToolManager keeps `discover_*`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/tools.py` | MODIFY | _resolve_spec_class → resolver shim |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py` | MODIFY | _resolve_toolkit_class → resolver shim |
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` | MODIFY | _resolve_registry_class → resolver shim |
| `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` | MODIFY | delete _EXPLICIT; schema_for via resolver |
| `packages/ai-parrot-server/tests/studio/_host_probe.py` | CREATE | server host fixture (probe package + counters) |
| `packages/ai-parrot/tests/interfaces/test_resolve_spec_class_resolver.py` | CREATE | bot-build shim resolves host toolkit |
| `packages/ai-parrot-server/tests/studio/test_resolver_adoption.py` | CREATE | Studio shims + unavailable-but-kept list |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.tools.resolver import get_toolkit_resolver  # TASK-3975
from parrot.tools.config_schema import build_schema_envelope, secret_paths  # tooling_store.py:21
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/tools.py
    @staticmethod
    def _resolve_spec_class(slug: str) -> type | None:  # :176-186 ← anchor (occurrences: 1)
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py
def _resolve_toolkit_class(slug: str) -> type | None:  # :156-180 ← anchor (occurrences: 1); import :30
# packages/ai-parrot-server/src/parrot/handlers/studio/testing.py
def _resolve_registry_class(slug: str) -> type | None:  # :92-119 ← anchor (occurrences: 1); import :28
# packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py
_EXPLICIT = {"dataset_manager": DatasetManager, "wiki": LLMWikiToolkit, "infographic": InfographicToolkit}  # :39 (occurrences: 1)
def schema_for(self, slug: str) -> tuple[type, dict[str, Any]]:  # :138-144
    cls = _EXPLICIT.get(slug) or _resolve_toolkit_class(slug)  # :140
from .toolkits import _resolve_toolkit_class  # :36
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py:78-83 — list marks LookupError slugs `unavailable`
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py:83-91 — _spec → store.schema_for (no edit)
```

### Does NOT Exist
- ~~a `_resolve_*` that walks `plugins.tools` per call~~ — after this task none does; the resolver caches.
- ~~deleting persisted specs whose slug no longer resolves~~ — they are kept and reported `unavailable`.
- ~~`ToolkitResolver.register`~~ — the resolver has no write API.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/interfaces/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/testing.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/_host_probe.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/interfaces/test_resolve_spec_class_resolver.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_resolver_adoption.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/tools.py#ToolInterface._resolve_spec_class",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py#_resolve_toolkit_class",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/testing.py#_resolve_registry_class",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#AgentToolingStore.schema_for"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Shims keep their names and signatures so existing imports (`tooling_store.py:36`) and tests keep working.
- `schema_for` must still raise `LookupError` for an unknown or rule-5-unavailable slug, so the FEAT-593
  list keeps reporting it `unavailable`.
- Behaviour change to note: `_resolve_registry_class` (live assign / execute) used `discover_all()`; the resolver
  keeps the walk fallback (rule 3) so GLOBAL behaviour is unchanged when `plugins.tools` has no registry.

### Cross-feature ordering
- `interfaces/tools.py`: after TASK-3978, which merges before FEAT-621 W2; this task serialises after FEAT-621
  W2's builder edits on that file if any landed (package X16 "then TOOLKITS M2/M4 serialise").
- `studio/toolkits.py`, `studio/testing.py`, `studio/tooling_store.py` are Studio handler files edited by FEAT-621
  W2/W3: **this task merges after the FEAT-621 task for each of those files and rebases on it** (X16 per-file
  rule). `testing.py` additionally waits for FEAT-605 W1.3 (execute), which FEAT-621 W3 rebases on.
- `tooling_store.py` / `toolkit_overrides.py` are identity files: FEAT-621 M13 (its W1) merges first (X16).

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
1. Replace the three resolver bodies with one-line shims — *why*: G1, one authority.
2. Delete `_EXPLICIT` and route `schema_for` through the resolver — *why*: built-ins are resolver rule 1.
3. Create the server `_host_probe.py` (copy the core probe shape; add `tp_probe_tool_write`) — *why*: shared server fixture.
4. Write the tests; mutation: restore the old `discover_from_registry` body ⇒ the host-slug test RED.

### `packages/ai-parrot/src/parrot/interfaces/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _resolve_spec_class(slug: str) -> type | None:' interfaces/tools.py)
# REPLACE the body of `_resolve_spec_class` (verified: interfaces/tools.py:177-186) with:
    @staticmethod
    def _resolve_spec_class(slug: str) -> type | None:
        """Resolve a toolkit slug through the shared ToolkitResolver (FEAT-622 M2)."""
        return get_toolkit_resolver().resolve(slug)
# and replace `from parrot.tools.discovery import discover_from_registry, resolve_class` (:13) with
from parrot.tools.resolver import get_toolkit_resolver
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _resolve_toolkit_class(slug: str) -> type | None:' toolkits.py)
def _resolve_toolkit_class(slug: str) -> type | None:
    """Resolve ``slug`` through the shared ToolkitResolver (FEAT-622 M2 shim)."""
    return get_toolkit_resolver().resolve(slug)
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _resolve_registry_class(slug: str) -> type | None:' testing.py)
def _resolve_registry_class(slug: str) -> type | None:
    """Resolve ``slug`` through the shared ToolkitResolver (FEAT-622 M2 shim)."""
    return get_toolkit_resolver().resolve(slug)
# FILL IN: drop `discover_all` from the import at testing.py:28 when unused (keep `resolve_class` only if used)
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_EXPLICIT = {' tooling_store.py) — delete line :39
    def schema_for(self, slug: str) -> tuple[type, dict[str, Any]]:
        """Return the class and JSON schema for ``slug``."""
        cls = get_toolkit_resolver().resolve(slug)
        if cls is None:
            raise LookupError(slug)
        envelope = build_schema_envelope(slug, cls, server_managed=_SERVER_MANAGED.get(slug, frozenset()))
        return cls, envelope.schema
# FILL IN: remove now-unused imports (DatasetManager / InfographicToolkit / LLMWikiToolkit only if no other use)
```

### `packages/ai-parrot-server/tests/studio/_host_probe.py` (CREATE)
```python
"""Server host fixture (spec §4): tmp plugins/tools package with ProbeToolkit / ProbeTool / write variant."""
# FILL IN: same structure as packages/ai-parrot/tests/tools/_host_probe.py (TASK-3975) plus
#   TOOL_REGISTRY["tp_probe_tool_write"] → a standalone write AbstractTool with a write counter;
#   fixtures: host_plugins (tmp package + resolver reload), no_subprocess (patch
#   asyncio.create_subprocess_exec to record and fail; assert zero calls at teardown)
```

### FILL IN checklist
- [ ] `testing.py` / `toolkits.py` / `tooling_store.py` — unused-import cleanup; bounded by `ruff check --select F401` on the three files.
- [ ] `_host_probe.py` (server) — probe package + `no_subprocess`; bounded by spec §4 "Host fixture" / "Test Data / Fixtures".

---

## Acceptance Criteria

- [ ] `_resolve_spec_class`, `_resolve_toolkit_class`, `_resolve_registry_class` are one-line shims over `get_toolkit_resolver()`.
- [ ] `_EXPLICIT` no longer exists (`grep -n _EXPLICIT packages/ai-parrot-server/src` → 0).
- [ ] With the host fixture, each shim and `schema_for("tp_probe_tool")` resolve the host class (non-tenant-bound entry).
- [ ] An unresolvable persisted slug is kept and listed in `unavailable` by `GET …/toolkits`.
- [ ] Existing suites pass: `test_toolkits.py`, `test_tooling_store.py`, `test_toolkit_config.py`, `test_testing_surface.py`, `test_toolkit_overrides.py`.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/interfaces/test_resolve_spec_class_resolver.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_resolver_adoption.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_toolkits.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_tooling_store.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_toolkit_config.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_testing_surface.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_toolkit_overrides.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_resolver_adoption.py
from parrot.handlers.studio.testing import _resolve_registry_class
from parrot.handlers.studio.toolkits import _resolve_toolkit_class
from ._host_probe import host_plugins  # noqa: F401


def test_studio_shims_resolve_host_entry(host_plugins):
    assert _resolve_toolkit_class("tp_probe_tool") is _resolve_registry_class("TP_PROBE_TOOL") is not None


async def test_feat593_list_keeps_unresolvable_spec_as_unavailable(host_plugins):
    """A persisted spec whose slug no longer resolves is kept and reported `unavailable`, not deleted."""
    # FILL IN: real make_mocked_request handler (see test_toolkit_config.py helpers), state with slug "gone"


# packages/ai-parrot/tests/interfaces/test_resolve_spec_class_resolver.py
def test_resolve_spec_class_uses_resolver(monkeypatch):
    """_resolve_spec_class delegates to get_toolkit_resolver().resolve (mutation: old body ⇒ RED with host slug)."""
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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
**Mutation evidence**: <for each new assertion: the code reverted, the test that went RED>

**Deviations from spec**: none | describe if any
