---
id: F033
query_id: Q053
type: grep
intent: "Toolkit hooks: AbstractToolkit _pre_execute/_post_execute + requires_auth declaration state."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-034]
---

# F033 — _pre_execute/_post_execute exist on AbstractToolkit; credential_provider exists on both AbstractTool (:306) and AbstractToolkit (:331, propagated to generated tools :717); `requires_auth` does NOT exist

## Summary

`tools/toolkit.py`: `credential_provider: str | None = None` (:331), set from kwarg (:376), `_pre_execute(tool_name, /, **kwargs)` (:491), `_post_execute(tool_name, result, /, **kwargs)` (:506), propagated to each `ToolkitTool` (:717-718). `tools/abstract.py`: `credential_provider: Optional[str] = None` (:306), seam at :1013-1035, `current_credential()` ContextVar helper (:39-48). Grep for `requires_auth`: 0 hits.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 331
  symbol: `AbstractToolkit.credential_provider`
  excerpt: |
    credential_provider: str | None = None
- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 491-506
  symbol: `AbstractToolkit._pre_execute/_post_execute`
  excerpt: |
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None
    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any
- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 717-718
  symbol: `AbstractToolkit._generate_tools`
  excerpt: |
    if self.credential_provider:
        tool.credential_provider = self.credential_provider
- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 306
  symbol: `AbstractTool.credential_provider`
  excerpt: |
    credential_provider: Optional[str] = None
- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 39-48
  symbol: `current_credential`
  excerpt: |
    # Set by AbstractTool.execute() when the tool declares credential_provider; tools call current_credential() inside _execute

## Notes

Brainstorm's proposed `requires_auth = AuthRequirement(provider, scopes)` has a near-equivalent: `credential_provider` (provider id only, no scopes). Toolkit-level default + per-tool override already exists.
