---
id: F004
query_id: Q004
type: read
intent: Locate bug intake, research, and development node classes and their result models.
executed_at: 2026-08-31T15:20:00+02:00
duration_ms: 210
parent_id: null
depth: 0
---

# F004 - Target nodes mutate shared state and external systems

## Summary

The target nodes are not pure computations. Bug intake may reproduce a failure and mutates the brief; research fetches logs, resolves or creates Jira state, provisions a repository/worktree, dispatches SDD research, validates worktree reuse, and writes `research_output`; development transitions Jira, dispatches workers, mutates a worktree, and writes `development_output`. Recovery must rehydrate shared keys and validate external artifacts, not only return a cached scalar.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/bug_intake.py`
  lines: 112-123
  symbol: `BugIntakeNode.execute`
  excerpt: |
    findings = await self._enrich(brief)
    shared["bug_findings"] = findings
    shared["bug_brief"] = brief
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py`
  lines: 271-334
  symbol: `ResearchNode.execute`
  excerpt: |
    excerpts = await self._collect_log_excerpts(...)
    existing_key = await self._find_existing_issue(brief)
    shared["jira_issue_key"] = issue_key
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py`
  lines: 423-473
  symbol: `ResearchNode.execute`
  excerpt: |
    research_out = await self._dispatcher.dispatch(...)
    worktree_reused = await self._ensure_worktree_safe(...)
    shared["research_output"] = research_out
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py`
  lines: 142-220
  symbol: `DevelopmentNode.execute`
  excerpt: |
    research: ResearchOutput = shared["research_output"]
    ...
    return await self._execute_pool(shared, research, pool_cfg, scheduler)

