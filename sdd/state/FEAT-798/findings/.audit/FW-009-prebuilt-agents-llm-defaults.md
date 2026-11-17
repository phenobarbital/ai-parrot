---
id: FW-009
query_id: Q009
type: wiki_query
intent: "Orient: pre-built agents under parrot.bots and which llm/model defaults they declare."
executed_at: 2026-11-04T01:40:08Z
duration_ms: 4000
parent_id: null
depth: 1
---

# FW-009 — Pre-built agents mostly default to 3.x strings; the 2.5 defaults are concentrated in the FEAT-796 component builtins

## Summary

`wikitoolkit query` ranks the FEAT-188 and FEAT-796 specs first (1.00 / 0.71), then `agentcrew-handler-default-key.spec.md` (0.61) and the FEAT-796 crew test module. Among concrete `parrot.bots` classes the graph surfaced `WebSearchAgent` (`bots/search.py:L45-250`) whose constructor defaults to `llm='google:gemini-3-flash'` (an id that is **not** in the enum — `GEMINI_3_FLASH` is an alias of `gemini-3.5-flash`, but the bare string `gemini-3-flash` would hit the conservative prefix path), and `ComputerAgent` (parrot_tools) whose test pins `llm == "google:gemini-3.8-flash"`. The graph did not surface a `parrot.bots` class hardcoding `gemini-2.5-*` as a default; the 2.5 defaults it knows are the FEAT-796 builtins (FW-005) and the FEAT-188 inventory (FW-004, possibly stale). A full literal sweep of `parrot/bots/` is the codebase lane's Q015.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/search.py`
  lines: 45-250 (ctor defaults ~L84-85)
  symbol: `WebSearchAgent.__init__`
  excerpt: |
    use_llm: str = 'google',
    llm: str = 'google:gemini-3-flash',

- path: `packages/ai-parrot-tools/tests/computer/test_agent.py`
  lines: 13-19
  symbol: `TestComputerAgentTools.test_computer_agent_default_model`
  excerpt: |
    assert base_init.call_args.kwargs["llm"] == "google:gemini-3.8-flash"

- path: `packages/ai-parrot/tests/bots/flows/crew/test_crew_llm_defaults.py`
  lines: n/a
  symbol: `test_crew_sequential_default_model` (0.54)
  excerpt: |
    A Google-family CREW_LLM model is the sequential default forwarded to agents.

- path: `sdd/specs/agentcrew-handler-default-key.spec.md`
  lines: n/a
  symbol: FEAT-575 CREW_AI_KEY spec (0.61)
  excerpt: |
    AgentCrew Handler Default Google Key (`CREW_AI_KEY`) — credential cascade, not model defaults

- path: `sdd/tasks/completed/TASK-1778-result-agent.md`
  lines: n/a
  symbol: `ResultAgent` (0.37)
  excerpt: |
    ResultAgent — Registered Agent for Infographic Rendering; falls back to GoogleModel.GEMINI_FLASH_LATEST when no llm is supplied (per FW-003)

## Notes

- `gemini-3-flash` in `WebSearchAgent` is itself a suspicious id (not a catalogue value); worth checking live, but out of the 2.5 scope.
- [cross-lane: type=grep, intent=literal sweep of packages/ai-parrot/src/parrot/bots/ for gemini-2.5 / GEMINI_2_5 / 'google:gemini' defaults, including bots/base.py, voice.py, scraper/, flows/, agents/]
