---
id: F006
query_id: Q006
type: read
intent: Check AbstractTool for existing delegation metadata flags
executed_at: 2026-09-21T22:10:00Z
depth: 0
parent_id: null
---

# F006 — AbstractTool base: no delegate_safe flag exists

## Summary

AbstractTool in `parrot/tools/abstract.py` defines `_execute()` (abstract), `execute()` (public wrapper with args_schema validation), and `args_schema`. No metadata flags for delegation safety exist — no `delegate_safe`, no `delegate_description` attribute. The ToolManager has a `ToolSchemaAdapter` for Bedrock format conversion but no generic `ToolSpec` model for cross-backend schema exchange. All three (`delegate_safe`, `delegate_description`, `ToolSpec`) would be new additions.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 200-201
  symbol: `_execute`
  excerpt: |
    @abstractmethod
    async def _execute(self, **kwargs) -> Any:

- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 375
  symbol: `execute`
  excerpt: |
    async def execute(self, ...):
        # validates args via args_schema, runs permission checks, invokes _execute

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  symbol: `ToolSchemaAdapter._clean_for_bedrock`
  excerpt: |
    # Adapts tool schema to the AWS Bedrock Converse API envelope.
    # No generic ToolSpec model exists.

## Notes

The `delegate_safe: bool` flag (default False) proposed for AbstractTool would gate which tools a delegate node can call without explicit `allow_side_effects`. Read-only/idempotent tools (web fetch, scrape, read queries) would opt in. This is a cross-cutting change to the tool base class.
