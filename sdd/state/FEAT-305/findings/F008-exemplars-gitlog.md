---
id: F008
query_id: Q005+Q010
type: read
intent: Exemplar tool + recent git activity in parrot/tools
executed_at: 2026-07-13T22:44:00Z
parent_id: null
depth: 0
---

# F008 — WorkIQTool exemplar + recent tools/ activity

## Summary

`WorkIQTool` (parrot/tools/workiq_tool.py) is the house style for a single
`AbstractTool`: class attrs `name`, `description`, `args_schema`
(subclass of `AbstractToolArgsSchema` with Field descriptions), optional
`credential_provider`, async `_execute(**kwargs) -> str`. Recent git activity
in parrot/tools/ is credential-broker work (FEAT-263/264), infographic
render_template, and Bedrock tool-schema adapters — nothing colliding with a
new company-research toolkit.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/workiq_tool.py`
  lines: 44-58
  symbol: `_WorkIQArgs`
  excerpt: |
    class _WorkIQArgs(AbstractToolArgsSchema):
        query: str = Field(..., description="...")
- path: `packages/ai-parrot/src/parrot/tools/workiq_tool.py`
  lines: 60-110
  symbol: `WorkIQTool`
  excerpt: |
    class WorkIQTool(AbstractTool):
        name = "workiq_ask"
        credential_provider: str = "workiq"
        args_schema = _WorkIQArgs
        async def _execute(self, query: str = "", ...) -> str: ...
- path: `packages/ai-parrot/src/parrot/tools/`
  symbol: git log
  excerpt: |
    452c1cefa Merge branch 'feat-302-bedrock-client-llm' into dev
    c76ee58a7 feat(infographic): add render_template tool usable by any agent
    793b3ca21 feat(unified-credential-broker): TASK-1676 ...
