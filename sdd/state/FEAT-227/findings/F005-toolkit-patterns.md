---
id: F005
query_id: Q005
type: read
intent: Understand complex toolkit implementation patterns for the new ComputerInteractionToolkit
executed_at: 2026-06-05T00:00:00Z
duration_ms: 1500
parent_id: null
depth: 0
---

# F005 — Complex toolkit implementation patterns

## Summary

Three canonical toolkit patterns: (1) OpenAPIToolkit — dynamic tool generation from spec,
(2) FileManagerToolkit — static methods + filtering + namespacing with `tool_prefix`,
(3) JiraToolkit — static methods + multiple auth modes + `_pre_execute()` lifecycle hook.
All inherit AbstractToolkit; public async methods auto-become tools. Key patterns: factory
constructors, `_pre_execute()` for auth resolution, `exclude_tools` for dynamic filtering,
and `tool_prefix` for namespacing.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/openapitoolkit.py`
  symbol: `OpenAPIToolkit(AbstractToolkit)`
  excerpt: |
    # Dynamic tools from OpenAPI spec
    # _generate_dynamic_methods() creates bound async methods per operation

- path: `packages/ai-parrot/src/parrot/tools/filemanager.py`
  symbol: `FileManagerToolkit(AbstractToolkit)`
  excerpt: |
    tool_prefix: Optional[str] = "fs"
    # exclude_tools for dynamic filtering
    # Backend abstraction: local/S3/GCS via FileManagerInterface

- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  symbol: `JiraToolkit(AbstractToolkit)`
  excerpt: |
    input_class = JiraInput
    # _pre_execute() resolves per-user client in OAuth2 3LO mode
    # Config cascade: kwargs > navconfig > env vars

## Notes

- ComputerInteractionToolkit should follow FileManagerToolkit pattern: static methods with tool_prefix
- tool_prefix = "computer" → tools named computer_click_at, computer_navigate, etc.
- _pre_execute() can handle browser lifecycle (ensure browser is started)
- Existing WebScrapingToolkit tools (scrape, crawl, plan_*) could be composed alongside
