---
id: F008
query_id: Q019
type: read
intent: Measure refactor blast radius via the second consumer of AgentREPL
executed_at: 2026-09-02T22:00:30Z
parent_id: null
depth: 0
---

# F008 — `agentd` is a second consumer of `AgentREPL`/`ResponseRenderer` and already monkeypatches around a missing hook

## Summary

`parrot attach` (ai-parrot-integrations) imports `AgentREPL`, `REPLConfig` and
`ResponseRenderer` from core and drives the same loop. To flush daemon job
events after each turn it shadows `repl.send`/`repl.send_stream` at the instance
level, with a docstring stating the reason outright: `AgentREPL.run()`'s loop is
"a monolithic method with no exposed post-turn hook". Any refactor must (a) keep
these three imports working or coordinate a cross-package change, and (b) has a
clear opportunity to retire the monkeypatch by exposing a real hook.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/cli.py`
  lines: 19-22
  symbol: cross-package imports
  excerpt: |
    from parrot.cli.renderer import ResponseRenderer
    from parrot.cli.repl import AgentREPL, REPLConfig
    from rich.console import Console
    from rich.markdown import Markdown

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/cli.py`
  lines: 158-181
  symbol: `attach` command
  excerpt: |
    renderer = ResponseRenderer()
    ...
    config = REPLConfig(agent_name=display_name, streaming=not no_stream)
    repl = AgentREPL(bot=bot, config=config, renderer=renderer)

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/cli.py`
  lines: 205-230
  symbol: `_wrap_with_event_drain`
  excerpt: |
    """Flush queued job-event lines after each turn, never mid-stream.

    `AgentREPL.run()`'s loop is a monolithic method with no exposed
    post-turn hook, and modifying `parrot.cli.repl` is out of scope for
    this feature. Instead, this wraps `repl.send`/`repl.send_stream` at
    the INSTANCE level ...
    """
    repl.send = _send_with_drain
    repl.send_stream = _send_stream_with_drain

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/cli.py`
  lines: 30,309
  symbol: independent Console + renderer reuse
  excerpt: |
    console = Console()
    ...
    ResponseRenderer().render_info(
