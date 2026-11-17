---
id: F017
query_id: Q030
type: read
intent: "Toolkit config model"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-017]
---

# F017 — ToolkitSection: class/enabled/kwargs/include/exclude/llm/llm_kwargs/env; nothing identity-related

## Summary

`ToolkitSection` fields: `class_path` (alias `class`), `enabled`, `kwargs`, `include`, `exclude`, `llm`, `llm_kwargs`, `env` (env vars written into installer entries). `load_toolkits_config(root, config_path)` reads only `.parrot/mcp-toolkits.yaml`; nothing is implicit (FEAT-570). No field names a user, principal, token or credential provider.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/toolkit_config.py`
  lines: 20-59, 90-123
  symbol: `ToolkitSection / load_toolkits_config`
  excerpt: |
    class ToolkitSection(BaseModel):
        class_path: str = Field(..., alias="class"); enabled: bool = True
        kwargs: dict[str, Any]; include: list[str] | None; exclude: list[str] | None
        llm: str | None; llm_kwargs: dict[str, Any]; env: dict[str, str]
    def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig:
        if config_path is None: config_path = root / ".parrot" / "mcp-toolkits.yaml"

## Notes

-
