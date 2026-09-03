---
id: F001
query_id: Q001,Q002
type: read
intent: Confirm how 'parrot agent <id>' is wired and which output path it uses
executed_at: 2026-09-02T21:57:00Z
parent_id: null
depth: 0
---

# F001 — `parrot agent` is already a Rich + prompt_toolkit console, not a print() console

## Summary

The `parrot agent` command is registered lazily in `cli/__init__.py` (`"agent":
"parrot.cli.agent_repl"`) and its module docstring already advertises a
"Rich-based response renderer". `agent_repl.py` imports `rich.console.Console`
at module level and routes every message, banner, error, and the `--list` table
through Rich. The source request's premise — "using direct print to stdout" — is
**false for this module**: it contains zero `print()` calls.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/__init__.py`
  lines: 6-12
  symbol: module docstring
  excerpt: |
    This package also provides the interactive agent REPL subpackage:
    - ``parrot.cli.agent_repl`` — ``parrot agent`` Click command
    - ``parrot.cli.renderer`` — Rich-based response renderer
    - ``parrot.cli.repl`` — AgentREPL engine

- path: `packages/ai-parrot/src/parrot/cli/__init__.py`
  lines: 110-130
  symbol: `cli._lazy_commands`
  excerpt: |
    cli._lazy_commands = {
        ...
        "agent": "parrot.cli.agent_repl",
        "devloop": "parrot.cli.devloop",

- path: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
  lines: 17-25
  symbol: module-level console
  excerpt: |
    from rich.console import Console
    ...
    console = Console(file=sys.__stdout__, force_terminal=True)

- path: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
  lines: 229-236
  symbol: `_print_banner`
  excerpt: |
    console.print(
        f"\n[bold green]Agent loaded:[/bold green] [bold]{name}[/bold] "
        f"([dim]{bot_class}[/dim]) • mode=[cyan]{mode}[/cyan]"

- path: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
  lines: 138-144
  symbol: `_run`
  excerpt: |
    config = REPLConfig(agent_name=name, streaming=not no_stream, ...)
    repl = AgentREPL(bot=bot, config=config, renderer=renderer)

## Notes

`streaming` defaults to True (`--no-stream` opts out) — so the default user
experience is the streaming path, which F003 shows is the degraded one.
