---
id: F004
query_id: Q004
type: read
intent: Locate the AbstractTool result seam for in-bound scrub emplacement (a)
executed_at: 2026-06-23T03:55:00Z
parent_id: null
depth: 0
---

# F004 — AbstractTool.execute() is the single result seam (not hooked)

## Summary
`AbstractTool.execute()` is the one place every tool's raw output is normalized
into a `ToolResult` before returning to the caller/model: each branch (already a
ToolResult / dict / scalar) assigns `tool_result` and the method returns it at the
tail. This is exactly the brainstorm's emplacement (a) — a single chokepoint that
covers every tool for free. The committed work did **not** hook a scrubber here;
redaction lives in the Gemini client and inside python_repl instead. `ToolResult`
is the Pydantic carrier (`.result`, `.status`, `.metadata`).

## Citations
- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 473-616
  symbol: `AbstractTool.execute`
  excerpt: |
    # 576-603: normalise raw_result -> tool_result (ToolResult)
    # 616: return tool_result   <-- single in-bound scrub point (emplacement a)
- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 47-73
  symbol: `ToolResult`

## Notes
Resolves the brainstorm VERIFY item: the seam exists and is single. The `Raw Result
Type / output preview` NOTICE logs the brainstorm referenced are emitted around this
materialization. Hooking the scrubber here makes emplacement (a) load-bearing.
