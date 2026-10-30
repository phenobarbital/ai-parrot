---
id: FC-015
query_id: Q034
type: read
intent: "Read the crew definition / models module found by Q033 (or crew.py from_definition region)."
executed_at: 2026-10-30T16:44:46Z
duration_ms: 400
parent_id: null
depth: 0
---

# FC-015 — `AgentCrew.from_definition()` resolves agent classes and tools via injected `class_resolver`/`tool_resolver` callables (BasicAgent fallback)

## Summary

`crew.py` line 781: classmethod taking `crew_def`, keyword-only `class_resolver: Callable[[str], Optional[type]]`, optional `tool_resolver`, `google_api_key`, **kwargs. Unknown class → `BasicAgent`. This resolver-injection seam is where an "expert resolver" (name → expert bundle → configured Agent) would plug in without changing the crew engine.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: 781-800
  symbol: `AgentCrew.from_definition`
  excerpt: |
    def from_definition(cls, crew_def: "CrewDefinition", *,
        class_resolver: Callable[[str], Optional[type]],
        tool_resolver: Optional[Callable[[str], Optional[AbstractTool]]] = None,
        google_api_key: Optional[str] = None, **kwargs) -> "AgentCrew":
        """... When it returns None the agent falls back to BasicAgent."""

## Notes

Server-side wrapper: `BotManager._create_crew_from_definition` (ai-parrot-server, from wiki orientation).
