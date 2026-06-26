---
id: F005
query_id: Q005
type: read
intent: Survey tool/skill patterns for wiki toolkit design
executed_at: 2026-06-26T00:00:00Z
duration_ms: 1500
parent_id: null
depth: 0
---

# F005 — Toolkits & Skills: Established Patterns for Agent-Facing APIs

## Summary

The AbstractToolkit pattern auto-generates tools from async methods with Pydantic schemas. Existing toolkits: PageIndexToolkit (pageindex prefix), GraphIndexToolkit (graphindex prefix), FileManagerToolkit, WorkingMemoryToolkit, DatabaseQueryToolkit, OpenAPIToolkit, etc. Tools are exposed to agents via ToolManager with permission gating, lifecycle hooks (_pre_execute, _post_execute), and output scrubbing. The skills system provides two-tier discovery (boot-time file registry + on-demand DB store) with YAML frontmatter markdown files. Agents integrate via SkillRegistryMixin.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  symbol: `AbstractToolkit`
  excerpt: |
    class AbstractToolkit:
        exclude_tools: tuple[str, ...]
        tool_prefix: Optional[str]
        def get_tools(self) -> List[AbstractTool]

- path: `packages/ai-parrot/src/parrot/tools/filemanager.py`
  symbol: `FileManagerToolkit`

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  symbol: `WorkingMemoryToolkit`

## Notes

The LLMWiki toolkit should follow the same AbstractToolkit pattern with a `tool_prefix = "wiki"`. It should compose PageIndexToolkit and GraphIndexToolkit rather than reimplementing their functionality. The wiki toolkit adds the orchestration layer: ingest (multi-page update), query (combined search + answer filing), lint (cross-reference health check), and bookkeeping (index.md / log.md management).
