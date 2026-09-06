---
id: F006
query_id: Q008
type: read
intent: Check whether an existing coding-agent CLI detector (wiki/coding_agents.py) can be reused for LLM-provider defaulting
executed_at: 2026-09-06T03:12:10Z
duration_ms: 300
parent_id: null
depth: 0
---

# F006 — `coding_agents.py` names the three CLIs but only installs wiki hooks, not LLM defaults

## Summary

`packages/ai-parrot/src/parrot/knowledge/wiki/coding_agents.py` hardcodes an `_AGENTS` dict
for `codex`, `claude`, `gemini` (instruction file, settings file, hook event/matcher per
agent), used by `install()`/`hook()` to wire the "query the wiki first" nudge into each CLI's
own hook system. It never checks whether the CLI binary or SDK is actually present/importable
— it just writes config files assuming the target agent exists. Not reusable as-is for
LLM-provider detection, but it does confirm the three canonical CLI identifiers to standardize
on (`codex`, `claude`, and, out of scope here, `gemini`).

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/coding_agents.py`
  lines: 45-49
  excerpt: |
    _AGENTS = {
        "codex": ("AGENTS.md", ".codex/hooks.json", "PreToolUse", "Bash|Grep|Glob|Read"),
        "claude": ("CLAUDE.md", ".claude/settings.json", "PreToolUse", "Bash|Grep|Glob|Read"),
        "gemini": (...),
    }
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/coding_agents.py`
  lines: 85-90
  symbol: `install`
  excerpt: |
    def install(agent: str, root: Path = Path.cwd()) -> list[str]:
        """Install one agent integration and return changed asset descriptions."""

## Notes

No `shutil.which` / availability probe exists anywhere in this file — the new detection helper
is genuinely new code, not an extraction of existing logic.
