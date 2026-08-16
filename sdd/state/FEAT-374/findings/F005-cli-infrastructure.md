# F005 — Existing CLI infrastructure: LazyGroup + `parrot agent` REPL precedent

- **Query**: Q002/Q004/Q010 (wiki query + reads)
- **Citations**:
  - `packages/ai-parrot/pyproject.toml:110-115` — `[project.scripts]`:
    `parrot = "parrot.cli:cli"`, plus `parrot-graphindex`, `wikitoolkit`.
  - `packages/ai-parrot/src/parrot/cli/__init__.py:60-78` — `LazyGroup`
    click group; subcommands registered in `cli._lazy_commands` dict
    (`"agent": "parrot.cli.agent_repl"`, `"mcp"`, `"wiki"`, …).
    **`parrot devloop` = add one dict entry + one module.**
  - `packages/ai-parrot/src/parrot/cli/` — full REPL stack from FEAT
    console-cli-agents: `agent_repl.py` (Click entry), `repl.py` (AgentREPL
    engine), `renderer.py` (Rich response renderer), `commands.py`
    (SlashCommandDispatcher), `loaders.py` (**StandaloneAgentLoader vs
    ServerAgentProxy — dual standalone/server mode precedent**).
  - `packages/ai-parrot/pyproject.toml:77-82` — `rich>=13.0`,
    `click>=8.1.7`, `prompt_toolkit>=3.0` are already **core** deps
    (textual is NOT a dependency).
  - `sdd/proposals/console-cli-agents.brainstorm.md` + completed task index
    `sdd/tasks/index/console-cli-agents.json` (e.g. TASK-1136 "CLI Command
    Wiring", commit 35e17ccca).
