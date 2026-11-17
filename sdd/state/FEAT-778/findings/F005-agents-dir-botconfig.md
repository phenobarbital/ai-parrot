---
id: F005
query_id: Q024
type: grep
intent: "Find BotConfig / agent-definition models and the YAML loading path (fields an expert manifest would extend)."
executed_at: 2026-10-30T16:42:58Z
duration_ms: 600
parent_id: null
depth: 0
merged_from: [FC-005-agents-dir-botconfig]
---

# F005 — `AGENTS_DIR` (conf.py) is the workspace root for per-agent assets (prompts/, queries/, kb/, skills/, templates/, flows/); YAML agent definitions live in `AGENTS_DIR/agents/`

## Summary

30 matches. `AGENTS_DIR` is configured in `parrot/conf.py:181` (default `BASE_DIR/agents`), created if missing and inserted at `sys.path[0]`. Agents already use a per-agent subtree: `AGENTS_DIR/{agent_id}/prompts`, `/queries` (agent.py), `/kb` (stores/local.py), `/skills` + `/templates` (fireflies_insights.py), and `AGENTS_DIR/flows/{name}.json` (flow loader). `BotConfig` and `load_agent_definitions` are in `registry/registry.py` (see FC-006). No `experts/` or `.parrot/` convention exists.

## Citations

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 181-194
  symbol: `AGENTS_DIR`
  excerpt: |
    AGENTS_DIR = config.get("AGENTS_DIR", fallback=BASE_DIR.joinpath("agents"))
    if not AGENTS_DIR.exists(): AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, agents_dir_str)

- path: `packages/ai-parrot/src/parrot/bots/agent.py`
  lines: 506-522
  symbol: `Agent (prompt/query file resolution)`
  excerpt: |
    file = AGENTS_DIR.joinpath(self.agent_id, "prompts", prompt_file)
    directory = AGENTS_DIR.joinpath(self.agent_id, "queries")

- path: `packages/ai-parrot/src/parrot/bots/fireflies_insights.py`
  lines: 115-139
  symbol: `skill_paths`
  excerpt: |
    skill_paths: list[Path] = [AGENTS_DIR / "fireflies_insights" / "skills"]
    ... AGENTS_DIR / "fireflies_insights" / "templates"

- path: `packages/ai-parrot/src/parrot/bots/flows/flow/loader.py`
  lines: 59-64
  symbol: `flow loader`
  excerpt: |
    """Load from file path or AGENTS_DIR/flows/{name}.json."""

- path: `packages/ai-parrot/src/parrot/bots/stores/local.py`
  lines: 5
  symbol: `local KB dir`
  excerpt: |
    the agent's local directory structure (AGENTS_DIR/<agent_name>/kb/).

## Notes

The natural home for a workspace expert bundle by precedent is `AGENTS_DIR/experts/<slug>/` (or `AGENTS_DIR/{agent_id}/experts`), not a new `.parrot/` root.
