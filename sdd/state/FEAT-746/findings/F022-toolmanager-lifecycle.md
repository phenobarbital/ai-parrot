---
id: F022
query_id: Q003
type: wiki_query
intent: "Orient: ToolManager registration and toolkit lifecycle (verify no mount/unmount per category)."
executed_at: 2026-10-25T22:44:49Z
duration_ms: 0
parent_id: null
depth: 1
lane_origin: FW-004-toolmanager-lifecycle
---

# F022 — ToolManager: guard-chain execute_tool, ranker/search, keep-first toolkit re-registration, cleanup_toolkits; no category mount/unmount lifecycle surfaced

## Summary

The wiki has no file page outline for `parrot/tools/manager.py` itself (queries rank tests/specs), but the surrounding pages fix the facts that matter: `ToolManager.execute_tool()` runs a TOOL_CALL guard chain in which `PBACToolCallGuardrail` runs FIRST, before `GrantGuard`/`ConfirmationGuard` (pbac.py docstring); `ToolManager.rank_tools()`/`search_tools()` exist (TASK-2285 relevance ranker) — a precedent for `catalog.search`; FEAT-391 added `cleanup_toolkits()` and the `_open/_close/_ensure_open` lazy lifecycle; FEAT-721 made toolkit re-registration keep-first. Nothing in the wiki describes a per-category mount/unmount of tool *definitions* from the LLM context, nor a ToolDefinition enforcement path for dynamically added remote tools beyond FEAT-474 parity. The absence claim in the brainstorm (D8 VERIFY) stands on wiki evidence; the codebase lane should confirm against manager.py.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py`
  symbol: `PBACToolCallGuardrail`
  wiki_page_id: file:packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py (score 1.00)
  excerpt: |
    Guard-chain position (resolved spec review Q8): this guardrail runs FIRST in
    ToolManager.execute_tool(), before GrantGuard/ConfirmationGuard
- path: `packages/ai-parrot/tests/test_toolmanager_ranker.py`
  symbol: `ToolManager.rank_tools`
  wiki_page_id: file:packages/ai-parrot/tests/test_toolmanager_ranker.py (score 0.92)
  excerpt: |
    Unit tests for ToolManager.rank_tools() and the search_tools() wrapper
- path: `packages/ai-parrot/tests/tools/test_toolkit_reregistration.py`
  wiki_page_id: file:packages/ai-parrot/tests/tools/test_toolkit_reregistration.py (score 1.00)
  excerpt: |
    FEAT-721 — ToolManager keep-first toolkit re-registration.
- path: `sdd/specs/per-tool-connection.spec.md`
  wiki_page_id: file:sdd/specs/per-tool-connection.spec.md (score 0.67)
  excerpt: |
    Feature Specification: Per-Tool Connection Lifecycle (FEAT-391) — _open/_close/_ensure_open, ToolManager.cleanup_toolkits
- path: `sdd/specs/toolmanager-tooldefinition-enforcement.spec.md`
  wiki_page_id: file:sdd/specs/toolmanager-tooldefinition-enforcement.spec.md
  excerpt: |
    ToolManager ToolDefinition Enforcement Parity (G7 remediation) — execute_tool() enforcement parity for the ToolDefinition branch
- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  symbol: `WorkingMemoryToolkit.exclude_tools`
  excerpt: |
    exclude_tools: tuple[str, ...] = ("store",)   # per-instance hiding of tools is the only "unmount" precedent (AC13 FEAT-538)

## Notes

- `exclude_tools` on a toolkit instance + `_generate_tools()` is the only existing mechanism that changes the published tool set; it is static at generation time, not a runtime mount/unmount.
- [cross-lane: type=read, intent=read packages/ai-parrot/src/parrot/tools/manager.py (ToolManager: register_tool/remove_tool/get_tools/execute_tool) to confirm the absence of a category mount/unmount API and how tool definitions reach the client]
