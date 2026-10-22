---
id: F015
query_id: Q015
type: read
intent: How do existing consumers compose descriptions/comments today (follow-up from F011).
executed_at: 2026-10-07T22:57:00Z
duration_ms: 1500
parent_id: F011
depth: 1
---

# F015 — dev_loop ResearchNode hand-builds the description with f-strings and a 30 000-char cap

## Summary

`ResearchNode._build_description` (research.py L915-957) renders a body via the static `_render_body` (L959-978) — an f-string template: "Affected component / Details / Acceptance criteria / Log excerpts / Reporter / Escalation assignee". It applies progressive degradation against `_MAX_DESCRIPTION_CHARS = 30_000` (L71): LLM-summarize excerpts, then hard-truncate with a "... (truncated)" marker, citing Atlassian's 32 767-char cap. This is exactly the kind of inline composition a template file would replace, and the length guard is a behaviour any toolkit-level template renderer should preserve. The wiki also surfaced `crew/tool_node.py::resolve_templates` (recursive placeholder resolution) and `bots/prompts/identity.py` (file-based loader) as adjacent precedents.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py`
  lines: 71
  symbol: `_MAX_DESCRIPTION_CHARS`
  excerpt: |
    _MAX_DESCRIPTION_CHARS = 30_000
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py`
  lines: 915-957
  symbol: `ResearchNode._build_description`
  excerpt: |
    async def _build_description(self, brief: BugBrief, excerpts: List[str]) -> str:
        body = self._render_body(brief, excerpts)
        if len(body) > _MAX_DESCRIPTION_CHARS: ... digest = await self._summarize_excerpts(excerpts) ...
        if len(body) > _MAX_DESCRIPTION_CHARS: body = body[: _MAX_DESCRIPTION_CHARS - 32].rstrip() + "\n\n... (truncated)"
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py`
  lines: 959-978
  symbol: `ResearchNode._render_body`
  excerpt: |
    return (f"Affected component: {brief.affected_component}\n\n" f"{details_block}"
            f"Acceptance criteria:\n{criteria_lines}\n\n" f"Log excerpts:\n{excerpts_block}\n\n"
            f"Reporter: {brief.reporter}\n" f"Escalation assignee on failure: {brief.escalation_assignee}\n")
- path: `packages/ai-parrot/src/parrot/bots/flows/crew/tool_node.py`
  symbol: `resolve_templates`
  excerpt: |
    wiki: Recursively resolve template placeholders inside a value.
- path: `packages/ai-parrot/src/parrot/bots/prompts/identity.py`
  excerpt: |
    wiki: File-based identity loader (FEAT-321 — PromptBuilder Identity Capability).
