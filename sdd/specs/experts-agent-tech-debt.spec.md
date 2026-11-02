---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [experts, tech-debt, ledger-fix, security-hardening]
---

# Feature Specification: Experts agent tech debt — FEAT-785

**Feature ID**: FEAT-785
**Date**: 2026-11-01
**Author**: agent:sdd-fix (Jesus Lara)
**Status**: approved
**Discovered-from**: `issue:230ac877bdf5` (FEAT-778 code review)

---

## 1. Problem

Three minor findings from the FEAT-778 (domain experts) code review, filed as
`issue:230ac877bdf5`:

1. **Unescaped XML attributes** — `render_knowledge()` in
   `parrot/experts/knowledge/render.py` interpolates `item.layer`,
   `item.source` and `item.revision` into
   `<section layer="…" source="…" revision="…">` without escaping. Today the
   values are controlled, but ADR and workspace sources can supply arbitrary
   names, so a `"` or `<` in a source name breaks the prompt markup (or
   injects attributes).
2. **Final tool list is unchecked** — `ExpertAgent.__init__` filters tools by
   the allowlist before `super().__init__`, and
   `test_allowlist_filters_tools` checks the list only **before**
   `configure()`. `Agent.configure()` adds tools after construction (a probe
   on 2026-11-01 showed `read_omitted_content` appearing after configure,
   next to `to_json` from `__init__`). Nothing stops a base-Agent change from
   injecting `spawn_sub_agent` there, and the PBAC deny rule is registered
   only when an evaluator exists, so the allowlist is the only default guard.
3. **`ExpertRegistry.get(name, tenant=...)` silently ignores `tenant`** —
   phase one has no tenant views, but a caller passing a tenant gets the
   global instance with no signal.

### Goals
- Escape every attribute value `render_knowledge` writes.
- Guarantee a configured `ExpertAgent` never exposes `spawn_sub_agent`, and
  test the final (post-`configure`) tool list.
- Make the ignored `tenant` argument visible to callers.

### Non-Goals
- Tenant-specific expert views (still a later phase).
- Re-applying the whole allowlist after `configure()`: framework tools
  (`to_json`, `read_omitted_content`) are legitimately added by the base
  `Agent` and must survive.
- Escaping section **content** (it is literal prompt text by design).

---

## 2. Solution

### M1 — Escape `render_knowledge` attributes (`render.py`)
Escape `layer`, `source` and `revision` with
`html.escape(str(value), quote=True)` before interpolating them into the
`<section …>` tag. Output for values without special characters is unchanged
byte for byte (the existing determinism/literal-layer tests keep passing).

### M2 — Post-configure spawn guard (`agent.py`)
At the end of `ExpertAgent.configure()`, after the knowledge layers are
installed, remove `SPAWN_TOOL_NAME` (`parrot.experts.models`) from
`self.tool_manager` if present (`ToolManager.get_tool` /
`ToolManager.unregister_tool`) and log a warning when it was found. The
removal is unconditional: `ExpertManifest` already rejects
`spawn_sub_agent` in `toolkits`/`tools_allow` and `effective_allowlist`
strips it, so it is never a legitimately allowlisted expert tool.

### M3 — Visible `tenant` on `ExpertRegistry.get` (`registry.py`)
When `tenant is not None`, log a warning (`self.logger.warning`) that
tenant-specific expert views are not implemented in phase one and the global
instance is returned. Behaviour (return value, `KeyError` on unknown name)
is otherwise unchanged; the docstring states it.

---

## 3. Files

| File | Module | Action |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/knowledge/render.py` | M1 | MODIFY |
| `packages/ai-parrot/src/parrot/experts/agent.py` | M2 | MODIFY |
| `packages/ai-parrot/src/parrot/experts/registry.py` | M3 | MODIFY |
| `packages/ai-parrot/tests/experts/test_render.py` | M1 | MODIFY |
| `packages/ai-parrot/tests/experts/test_agent_activation.py` | M2 | MODIFY |
| `packages/ai-parrot/tests/experts/test_registry.py` | M3 | MODIFY |

---

## 4. Test Specification

- `test_render.py::test_render_escapes_section_attributes` — a layer whose
  `source` is `a"b<c>&d` and `revision` is `r"1` renders
  `source="a&quot;b&lt;c&gt;&amp;d"` and `revision="r&quot;1"`; no raw `"`
  appears inside the attribute values.
- `test_agent_activation.py::test_configured_expert_excludes_spawn_tool` —
  after `await agent.configure()`, `spawn_sub_agent` is not in
  `agent.tool_manager.list_tools()` and the allowlisted `lookup_fact` is.
- `test_agent_activation.py::test_configure_removes_injected_spawn_tool` — a
  `spawn_sub_agent` tool registered on the agent's `tool_manager` (simulating
  a base-Agent injection) is gone after `configure()`, while framework tools
  added by the base `Agent` (`read_omitted_content`) remain.
- `test_registry.py::test_get_with_tenant_warns_and_returns_global` —
  `registry.get(name, tenant="acme")` returns the same instance as
  `registry.get(name)` and logs a warning mentioning the tenant.

### Validation Contract

tests:
- packages/ai-parrot/tests/experts/test_render.py
- packages/ai-parrot/tests/experts/test_agent_activation.py
- packages/ai-parrot/tests/experts/test_registry.py
markers: none

### Test Data / Fixtures

Existing helpers only: the `expert_bundle` fixture (`tests/experts/conftest.py`),
`_Toolkit` / `_make` in `test_agent_activation.py`, `_registry` in
`test_registry.py`, `_ctx` in `test_render.py`.

---

## 5. Acceptance Criteria

- AC1: `render_knowledge` escapes `layer`, `source` and `revision`; output for
  plain values is unchanged.
- AC2: A configured `ExpertAgent` never lists `spawn_sub_agent`, even when it
  was registered before or during `configure()`; framework tools survive.
- AC3: `ExpertRegistry.get(..., tenant=<not None>)` logs a warning and still
  returns the global instance.
- AC4: `pytest packages/ai-parrot/tests/experts/` passes and `ruff check` on
  the changed files is clean.

---

## 6. Codebase Contract

### Verified Imports
- `from parrot.experts.models import SPAWN_TOOL_NAME` (`models.py:12`, `"spawn_sub_agent"`)
- `import html` (stdlib)

### Existing Signatures
- `render_knowledge(ctx: KnowledgeContext) -> str` — `experts/knowledge/render.py`
- `ExpertAgent.configure(self, app: Any = None) -> None` — `experts/agent.py`
- `ExpertRegistry.get(self, name: str, *, tenant: str | None = None) -> ExpertAgent` — `experts/registry.py:61`; `self.logger` set in `__init__` (line 51)
- `ToolManager.get_tool(tool_name) -> Optional[Any]`, `ToolManager.unregister_tool(tool_name) -> bool`, `ToolManager.list_tools() -> List[str]` — `parrot/tools/manager.py`
- `KnowledgeLayer.layer: LayerName`, `.source: str`, `.revision: str` — `experts/models.py:137`

### Does NOT Exist
- No tenant-view builder on `ExpertRegistry`; do not invent one.
- No escaping helper in `parrot.experts`; use stdlib `html.escape`.

---

## 7. Open Questions

None. Decisions taken: warning (not an exception) for `tenant`, so existing
callers keep working; targeted spawn removal (not full allowlist re-apply),
so framework tools survive.

## Revision History
- 2026-11-01 — initial, from `issue:230ac877bdf5` via `/sdd-fix`.
